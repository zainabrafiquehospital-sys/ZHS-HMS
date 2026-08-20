"""SQLAlchemy models for the Pharmacy / Medicine Billing module.

Four entities:
- `Medicine` — the admin-managed price list. Deliberately carries no
  stock/quantity column: this build tracks price only, never inventory
  (out of scope — see the module's design notes). `is_active` is a soft
  "no longer sold" flag distinct from `deleted_at` (see below); the
  price list is read via `search`/`list_active` by Reception's
  autocomplete (active only) and `list_all` by the admin CRUD screen
  (active + inactive, so a deactivated medicine remains visible/
  re-activatable there).
- `MedicineBill` — one receptionist-built, multi-item medicine sale.
  `visit_id` is nullable (`ForeignKey("visit.id")`, a plain column, never
  a `relationship()` — see app/modules/billing/models.py's identical
  cross-module-reference convention): a medicine bill may be tied to a
  registered visit or stand alone as a walk-in sale. Who billed it is
  the inherited `created_by` (BaseEntity) — mirroring `Invoice`'s
  identical choice not to add a redundant actor column (see that
  model's module docstring); there is deliberately no separate
  `receptionist_id` column here either. `amount_paid`/`status`/`paid_at`
  mirror `Invoice`'s identical three fields — a maintained running
  total/derived status, not computed live from `MedicineBillPayment`.
  `manual_patient_name`/`manual_patient_age`/`manual_patient_phone` are
  a third, mutually-exclusive alternative to `visit_id`: purely
  display information for the printed slip when the receptionist wants
  a name/age/contact on the slip without an existing Patient/Visit
  record to link (patient not in the system, or a deliberate skip) —
  no Patient or Visit row is looked up or created for this.
  `discount_amount`/`discount_reason` (2026-08-19 addition) are an
  optional fixed-amount discount applied at creation time — see
  `discount_amount`'s own column docstring below and
  PharmacyService.create_bill's docstring for the full mechanism.
  `queue_token` (2026-08-20 addition) is this bill's own identifying
  number, drawn from the same unified Postgres sequence Visit uses —
  see that column's own docstring for the full mechanism, and
  permanently-nullable rationale for bills predating this feature. A
  bill has at most one of a linked `visit_id`, complete manual patient
  fields (all three together, never partial), or neither (an anonymous
  walk-in) — enforced by this table's own CHECK constraints below, not
  only in the service layer.
- `MedicineBillItem` — one line on a MedicineBill. Snapshots the
  medicine's name and unit price at billing time
  (`medicine_name_snapshot`/`unit_price_snapshot`) so a later edit to
  the price list (or deactivation) never rewrites the historical amount
  a patient was actually charged — the same "billed record is
  immutable, even if its source changes later" principle
  `InvoiceLineItem` already follows for `PendingBillingItem`.
- `MedicineBillPayment` — one payment against a MedicineBill, the same
  timestamped/attributed audit-trail role `InvoicePayment` plays for
  Invoice (see that model's docstring for the full rationale).

Money fields use `Numeric`, never `Float` — see
app/modules/billing/models.py's module docstring for why."""

from datetime import datetime
from decimal import Decimal
from enum import Enum as PyEnum
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base_entity import BaseEntity
from app.shared.payment_method import PaymentMethod

_MONEY = Numeric(10, 2)


class MedicineCategory(PyEnum):
    SACHET = "sachet"
    DROPS = "drops"
    TABLET = "tablet"
    INJECTION = "injection"


class MedicineBillStatus(PyEnum):
    UNPAID = "unpaid"
    PARTIALLY_PAID = "partially_paid"
    PAID = "paid"


class Medicine(BaseEntity):
    __tablename__ = "medicine"
    __table_args__ = (
        Index("ix_medicine_name", "name"),
        Index("ix_medicine_is_active", "is_active"),
        CheckConstraint("unit_price > 0", name="ck_medicine_unit_price_positive"),
    )

    name: Mapped[str] = mapped_column(String(150), nullable=False)
    category: Mapped[MedicineCategory] = mapped_column(
        Enum(
            MedicineCategory,
            name="medicine_category",
            native_enum=False,
            length=20,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
            create_constraint=True,
        ),
        nullable=False,
    )
    unit_price: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    # "No longer sold" — distinct from `deleted_at` (a hard mistake/undo),
    # this is the normal, expected end state of a medicine the pharmacy
    # stops carrying. Deactivated medicines are excluded from the
    # receptionist-facing search/autocomplete but remain visible (and
    # re-activatable) on the admin management screen, and every bill
    # that already line-itemed one keeps its snapshot regardless.
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class MedicineBill(BaseEntity):
    __tablename__ = "medicine_bill"
    __table_args__ = (
        Index("ix_medicine_bill_visit_id", "visit_id"),
        # Mirrors app/modules/visits/models.py's identical
        # `ix_visit_queue_token_active` — unique among active
        # (non-soft-deleted) rows, but a unique index never rejects
        # multiple NULLs (Postgres treats each NULL as distinct), which
        # is exactly what every pre-2026-08-20 bill has. Structurally,
        # two rows (of either MedicineBill or Visit) can never actually
        # collide on a real token value regardless, since both draw
        # from the same single Postgres sequence — this index is about
        # lookup performance/integrity, not preventing an impossible
        # collision.
        Index(
            "ix_medicine_bill_queue_token_active",
            "queue_token",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        CheckConstraint("total_amount >= 0", name="ck_medicine_bill_total_amount_non_negative"),
        CheckConstraint("amount_paid >= 0", name="ck_medicine_bill_amount_paid_non_negative"),
        CheckConstraint(
            "amount_paid <= total_amount", name="ck_medicine_bill_amount_paid_not_exceeding_total"
        ),
        CheckConstraint(
            "discount_amount >= 0", name="ck_medicine_bill_discount_amount_non_negative"
        ),
        # A linked visit and manual patient details are mutually
        # exclusive — see this module's docstring. Enforced here, not
        # only in PharmacyService.create_bill, the same "the database is
        # the real backstop" rigor every other cross-field invariant in
        # this codebase already gets (e.g. Invoice's single-open-invoice
        # index).
        CheckConstraint(
            "NOT (visit_id IS NOT NULL AND manual_patient_name IS NOT NULL)",
            name="ck_medicine_bill_not_both_visit_and_manual_patient",
        ),
        # The three manual fields are all-or-nothing — a half-filled
        # manual entry would render a broken slip (see
        # render_medicine_bill_receipt's reference-section branching).
        CheckConstraint(
            "(manual_patient_name IS NULL AND manual_patient_age IS NULL "
            "AND manual_patient_phone IS NULL) OR (manual_patient_name IS NOT NULL "
            "AND manual_patient_age IS NOT NULL AND manual_patient_phone IS NOT NULL)",
            name="ck_medicine_bill_manual_patient_fields_all_or_none",
        ),
    )

    # Nullable: a medicine bill may stand alone as a walk-in sale with no
    # registered Visit — see this module's docstring.
    visit_id: Mapped[UUID | None] = mapped_column(ForeignKey("visit.id"))
    # This bill's own identifying number (2026-08-20 addition) — drawn
    # from the exact same Postgres sequence Visit.queue_token uses (see
    # app/modules/visits/constants.py's QUEUE_TOKEN_SEQUENCE_NAME
    # docstring for the full unification rationale), formatted
    # identically ("Token #NNNNNN"). Deliberately *permanently*
    # nullable, unlike every other additive column this codebase has
    # backfilled to a real value: every bill created before this
    # feature existed has no honest value to backfill here — there is
    # no way to reconstruct where it would have fallen in a unified
    # sequence retroactively — so old rows simply stay NULL forever,
    # and only bills created from this point forward ever get a real
    # token. The printed slip falls back to the pre-existing
    # `MED-<uuid fragment>` display when this is NULL (see
    # render_medicine_bill_receipt's docstring).
    queue_token: Mapped[str | None] = mapped_column(String(20))
    total_amount: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    # Same shape as app/modules/billing/models.py's Invoice: amount_paid
    # is a maintained running total (updated in the same transaction as
    # each new MedicineBillPayment row, so it can never drift from
    # SUM(amount) there — see that table's own docstring), never derived
    # live. `status` is likewise the same three-state derivation
    # (UNPAID/PARTIALLY_PAID/PAID) Invoice already has, just without an
    # equivalent to Invoice's CANCELLED — a medicine bill has no
    # cancellation pipeline, unlike an Invoice's Pending Billing Item
    # review flow.
    amount_paid: Mapped[Decimal] = mapped_column(_MONEY, nullable=False, default=Decimal("0.00"))
    # A fixed-amount discount applied once, at bill-creation time only
    # (2026-08-19 addition) — same shape and rationale as
    # app/modules/billing/models.py's Invoice.discount_amount/
    # discount_reason: `total_amount` above is already post-discount,
    # the pre-discount subtotal is never stored separately (always
    # cheaply recoverable as `total_amount + discount_amount`, see
    # PharmacyService.create_bill's docstring). One deliberate
    # difference from Invoice: `discount_reason` here is always
    # optional, even when `discount_amount > 0` — a product decision
    # for this feature specifically, not a data-integrity requirement
    # the way Invoice's reason-required rule is.
    discount_amount: Mapped[Decimal] = mapped_column(
        _MONEY, nullable=False, default=Decimal("0.00")
    )
    discount_reason: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[MedicineBillStatus] = mapped_column(
        Enum(
            MedicineBillStatus,
            name="medicine_bill_status",
            native_enum=False,
            length=20,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
            create_constraint=True,
        ),
        nullable=False,
        default=MedicineBillStatus.UNPAID,
    )
    paid_at: Mapped[datetime | None] = mapped_column()
    # Same field shapes/lengths as app/modules/patients/models.py's
    # Patient.full_name/age_years/phone_number — this is the identical
    # data, just typed in ad hoc for the slip instead of sourced from a
    # real Patient record. See this class's own docstring for the
    # mutual-exclusivity rule with `visit_id`.
    manual_patient_name: Mapped[str | None] = mapped_column(String(150))
    manual_patient_age: Mapped[int | None] = mapped_column(Integer)
    manual_patient_phone: Mapped[str | None] = mapped_column(String(20))


class MedicineBillItem(BaseEntity):
    __tablename__ = "medicine_bill_item"
    __table_args__ = (
        Index("ix_medicine_bill_item_medicine_bill_id", "medicine_bill_id"),
        CheckConstraint("quantity > 0", name="ck_medicine_bill_item_quantity_positive"),
        CheckConstraint("line_total >= 0", name="ck_medicine_bill_item_line_total_non_negative"),
    )

    medicine_bill_id: Mapped[UUID] = mapped_column(ForeignKey("medicine_bill.id"), nullable=False)
    medicine_id: Mapped[UUID] = mapped_column(ForeignKey("medicine.id"), nullable=False)
    medicine_name_snapshot: Mapped[str] = mapped_column(String(150), nullable=False)
    # Snapshotted alongside name/price for the identical reason (see this
    # module's docstring) — the printed slip's category column must never
    # change retroactively if the medicine's own category is later edited.
    category_snapshot: Mapped[MedicineCategory] = mapped_column(
        Enum(
            MedicineCategory,
            name="medicine_bill_item_category_snapshot",
            native_enum=False,
            length=20,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
            create_constraint=True,
        ),
        nullable=False,
    )
    unit_price_snapshot: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    line_total: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)


class MedicineBillPayment(BaseEntity):
    """One payment against a MedicineBill — the real, timestamped/
    attributed audit trail (inherited `created_at` is when it was paid,
    `created_by` is who recorded it), the exact same shape and rationale
    as app/modules/billing/models.py's `InvoicePayment`: `MedicineBill.
    amount_paid`/`status` stay a maintained running total rather than
    being replaced by a live SUM here, so every existing reader keeps
    working unchanged and this table only adds history nothing else
    needed before."""

    __tablename__ = "medicine_bill_payment"
    __table_args__ = (
        Index("ix_medicine_bill_payment_medicine_bill_id", "medicine_bill_id"),
        CheckConstraint("amount > 0", name="ck_medicine_bill_payment_amount_positive"),
    )

    medicine_bill_id: Mapped[UUID] = mapped_column(ForeignKey("medicine_bill.id"), nullable=False)
    amount: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    # `payment_method` (2026-08-19 addition) — same shape and rationale
    # as app/modules/billing/models.py's identical InvoicePayment.
    # payment_method; see app/shared/payment_method.py's module
    # docstring for the shared vocabulary. Every individual payment
    # carries its own method (never one method per MedicineBill).
    payment_method: Mapped[PaymentMethod] = mapped_column(
        Enum(
            PaymentMethod,
            name="payment_method",
            native_enum=False,
            length=20,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
            create_constraint=True,
        ),
        nullable=False,
    )

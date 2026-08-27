"""SQLAlchemy models for the Laboratory Billing module.

Four entities, deliberately independent from Reception's Visit/
procedure system (confirmed design — see this module's own package
docstring lineage in the design proposal) — mirrors app/modules/
pharmacy/models.py's shape almost exactly, with two deliberate
differences from that direct precedent, called out below.

- `LabTest` — the admin-managed price list. `category` (Pathology/
  Radiology) is a lightweight two-way grouping confirmed against this
  clinic's real, pre-existing lab-like Procedure catalog entries (see
  the one-time seed migration that copies them into this table) —
  unlike `Medicine.category` (a dispensing-form distinction that also
  constrains which units are valid, see app/modules/pharmacy/
  schemas.py), this one is purely a display/organization grouping,
  never cross-validated against any other field.
- `LabBill` — one receptionist-built, multi-test lab bill.
  **Deliberate difference #1**: patient linkage is `patient_id` (a
  direct, nullable FK straight to `Patient`) plus the usual manual_
  patient_name/_age/_phone fallback plus neither (anonymous) — the
  identical three-way shape `InventoryUsageEntry` already established,
  NOT `MedicineBill`'s Patient-via-Visit indirection (search a patient,
  then pick one of their registered Visits). Confirmed design decision:
  a lab-only patient is exactly as likely to have no same-day
  registered Visit at all as Inventory's own ward/emergency population
  already is (see that model's own docstring for the identical
  reasoning). There is deliberately no `visit_id` column on this table
  at all — this module never reads or writes anything Visit-owned.
  `amount_paid`/`status`/`paid_at` mirror `MedicineBill`'s identical
  maintained-running-total shape (never a live `SUM` over
  `LabBillPayment`). `discount_amount`/`discount_reason` and
  `queue_token` (drawn from the exact same unified Postgres sequence
  Visit/MedicineBill both already draw from — see
  app/modules/visits/constants.py's `QUEUE_TOKEN_SEQUENCE_NAME`
  docstring) also mirror `MedicineBill`'s identical mechanism exactly.
- `LabBillItem` — one line on a LabBill. Snapshots the test's name,
  category, and price at billing time, the same "billed record stays
  correct even if the price list changes later" principle
  `MedicineBillItem` already follows. **Deliberate difference #2**: no
  `quantity` column at all (confirmed design) — a lab test is a service
  performed, not a countable dispensed unit the way a medicine's
  tablets/sachets are; ordering the same test twice is two independent
  line rows, never one row with `quantity=2`. Since there is no
  quantity to multiply against, this table also has no separate
  `line_total` column — it would always be identical to
  `unit_price_snapshot`, a pointless duplicate; a bill's subtotal is
  the plain sum of every item's `unit_price_snapshot`.
- `LabBillPayment` — one payment against a LabBill, identical shape and
  rationale to `MedicineBillPayment`.

Money fields use `Numeric`, never `Float` — see app/modules/billing/
models.py's module docstring for why."""

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


class LabTestCategory(PyEnum):
    PATHOLOGY = "pathology"
    RADIOLOGY = "radiology"


class LabBillStatus(PyEnum):
    UNPAID = "unpaid"
    PARTIALLY_PAID = "partially_paid"
    PAID = "paid"


class LabTest(BaseEntity):
    __tablename__ = "lab_test"
    __table_args__ = (
        Index("ix_lab_test_name", "name"),
        Index("ix_lab_test_is_active", "is_active"),
        CheckConstraint("price > 0", name="ck_lab_test_price_positive"),
    )

    name: Mapped[str] = mapped_column(String(150), nullable=False)
    category: Mapped[LabTestCategory] = mapped_column(
        Enum(
            LabTestCategory,
            name="lab_test_category",
            native_enum=False,
            length=20,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
            create_constraint=True,
        ),
        nullable=False,
    )
    price: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    # "No longer offered" — distinct from `deleted_at`, mirrors
    # Medicine.is_active's identical rationale exactly: a deactivated
    # test is excluded from the receptionist-facing search but remains
    # visible/re-activatable on the admin management screen, and every
    # bill that already line-itemed one keeps its snapshot regardless.
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class LabBill(BaseEntity):
    __tablename__ = "lab_bill"
    __table_args__ = (
        Index("ix_lab_bill_patient_id", "patient_id"),
        # Mirrors app/modules/pharmacy/models.py's identical
        # `ix_medicine_bill_queue_token_active` — unique among active
        # rows, but a unique index never rejects multiple NULLs
        # (Postgres treats each NULL as distinct). Structurally, two
        # rows across Visit/MedicineBill/LabBill can never actually
        # collide on a real token value regardless, since all three
        # draw from the same single Postgres sequence.
        Index(
            "ix_lab_bill_queue_token_active",
            "queue_token",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        CheckConstraint("total_amount >= 0", name="ck_lab_bill_total_amount_non_negative"),
        CheckConstraint("amount_paid >= 0", name="ck_lab_bill_amount_paid_non_negative"),
        CheckConstraint(
            "amount_paid <= total_amount", name="ck_lab_bill_amount_paid_not_exceeding_total"
        ),
        CheckConstraint("discount_amount >= 0", name="ck_lab_bill_discount_amount_non_negative"),
        # A linked patient and manual patient details are mutually
        # exclusive — see this module's own docstring. Enforced here,
        # not only in LabService.create_bill, the same "the database is
        # the real backstop" rigor every other cross-field invariant in
        # this codebase already gets.
        CheckConstraint(
            "NOT (patient_id IS NOT NULL AND manual_patient_name IS NOT NULL)",
            name="ck_lab_bill_not_both_patient_and_manual",
        ),
        # The three manual fields are all-or-nothing — a half-filled
        # manual entry would render a broken slip.
        CheckConstraint(
            "(manual_patient_name IS NULL AND manual_patient_age IS NULL "
            "AND manual_patient_phone IS NULL) OR (manual_patient_name IS NOT NULL "
            "AND manual_patient_age IS NOT NULL AND manual_patient_phone IS NOT NULL)",
            name="ck_lab_bill_manual_patient_fields_all_or_none",
        ),
    )

    # Nullable: a lab bill may stand alone as a walk-in sale with no
    # linked Patient at all — see this module's docstring.
    patient_id: Mapped[UUID | None] = mapped_column(ForeignKey("patient.id"))
    # This bill's own identifying number, drawn from the exact same
    # unified Postgres sequence Visit/MedicineBill both use — see
    # MedicineBill.queue_token's own docstring for the full mechanism.
    # Every LabBill gets a real token from creation (unlike
    # MedicineBill, which has pre-2026-08-20 rows with none) — this
    # column is nullable only for schema-shape symmetry/future-proofing,
    # never expected to actually be NULL for any row this module writes.
    queue_token: Mapped[str | None] = mapped_column(String(20))
    total_amount: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    amount_paid: Mapped[Decimal] = mapped_column(_MONEY, nullable=False, default=Decimal("0.00"))
    discount_amount: Mapped[Decimal] = mapped_column(
        _MONEY, nullable=False, default=Decimal("0.00")
    )
    discount_reason: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[LabBillStatus] = mapped_column(
        Enum(
            LabBillStatus,
            name="lab_bill_status",
            native_enum=False,
            length=20,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
            create_constraint=True,
        ),
        nullable=False,
        default=LabBillStatus.UNPAID,
    )
    paid_at: Mapped[datetime | None] = mapped_column()
    # Same field shapes/lengths as app/modules/patients/models.py's
    # Patient.full_name/age_years/phone_number — this is the identical
    # data, just typed in ad hoc for the slip instead of sourced from a
    # real Patient record. See this class's own docstring for the
    # mutual-exclusivity rule with `patient_id`.
    manual_patient_name: Mapped[str | None] = mapped_column(String(150))
    manual_patient_age: Mapped[int | None] = mapped_column(Integer)
    manual_patient_phone: Mapped[str | None] = mapped_column(String(20))


class LabBillItem(BaseEntity):
    __tablename__ = "lab_bill_item"
    __table_args__ = (Index("ix_lab_bill_item_lab_bill_id", "lab_bill_id"),)

    lab_bill_id: Mapped[UUID] = mapped_column(ForeignKey("lab_bill.id"), nullable=False)
    lab_test_id: Mapped[UUID] = mapped_column(ForeignKey("lab_test.id"), nullable=False)
    lab_test_name_snapshot: Mapped[str] = mapped_column(String(150), nullable=False)
    category_snapshot: Mapped[LabTestCategory] = mapped_column(
        Enum(
            LabTestCategory,
            name="lab_bill_item_category_snapshot",
            native_enum=False,
            length=20,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
            create_constraint=True,
        ),
        nullable=False,
    )
    # No `quantity`/`line_total` — see this module's own docstring
    # ("Deliberate difference #2") for why: this *is* the line total,
    # there is nothing to multiply it by.
    unit_price_snapshot: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)


class LabBillPayment(BaseEntity):
    """One payment against a LabBill — the real, timestamped/attributed
    audit trail, the exact same shape and rationale as app/modules/
    pharmacy/models.py's `MedicineBillPayment`."""

    __tablename__ = "lab_bill_payment"
    __table_args__ = (
        Index("ix_lab_bill_payment_lab_bill_id", "lab_bill_id"),
        CheckConstraint("amount > 0", name="ck_lab_bill_payment_amount_positive"),
    )

    lab_bill_id: Mapped[UUID] = mapped_column(ForeignKey("lab_bill.id"), nullable=False)
    amount: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
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

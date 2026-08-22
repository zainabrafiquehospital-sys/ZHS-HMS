"""SQLAlchemy models for the Visit module (Phase 6 architecture §4: "the
aggregate root for one hospital encounter"). Registered once into
app/db/model_registry.py's centralized model registry.

`Visit` is deliberately the only module that owns clinical-stage
progression (`status`, §4.1's formalized state machine) — Reception,
Vitals, Consultation, and Billing all *call into* this module's service
to move a Visit's status forward (one-directional dependency, §12); this
module never reaches back into any of theirs. Queue routing (which role's
worklist a Visit currently sits in) is a deliberately separate, faster-
changing concept the Queue module (not yet built) will own — §4.1 is
explicit that a doctor-initiated vitals detour changes Queue routing
without moving the Visit out of `IN_CONSULTATION`.

Two more entities (2026-08-21 addition — itemized procedures):
- `Procedure` — the admin-managed procedure price list, mirroring
  app/modules/pharmacy/models.py's `Medicine` almost exactly (no
  category — nothing about a procedure needs one). `is_active` is the
  same "no longer offered" soft flag Medicine's own column is; unlike
  Medicine, the admin screen for this catalog also supports a genuine
  soft-delete (see VisitService's procedure-catalog methods) — a
  deliberate, explicitly-confirmed broadening beyond Medicine's own
  create/edit/activate-only shape, since nothing about a historical
  `VisitProcedureItem` depends on its source Procedure row still
  existing (it already snapshots the name at add-time, see below).
- `VisitProcedureItem` — one procedure line on a Visit **registered
  from 2026-08-21 onward only**. `procedure_id` is nullable and is the
  per-item (not per-visit) discriminator between a catalog-linked entry
  (snapshotted `name`/`amount` from the Procedure at add-time, its
  price locked — never client-editable, mirroring
  `MedicineBillItem.unit_price_snapshot`'s identical price-integrity
  rule) and a manual/free-typed entry (`procedure_id IS NULL`, `name`/
  `amount` both freely provided) — the two shapes coexist as separate
  rows on the very same Visit, never mutually exclusive at the parent
  level the way `MedicineBill.manual_patient_*` is.

  Deliberately NOT retrofitted onto any visit registered before this
  feature shipped — an explicit, confirmed decision: every visit
  registered before 2026-08-21 keeps its original single `Visit.
  procedure`/`Visit.amount` fields as its only record of what was
  billed, forever, with zero conversion. This is why `Visit.procedure`
  stays `NOT NULL` unchanged below despite no longer being read for
  display on a Visit that has procedure items — see that column's own
  docstring for the exact reasoning and the placeholder value a
  from-now-on Visit stores there instead. Every caller (print, every
  list/detail view) decides which of the two shapes to render for a
  given Visit purely by checking whether it has any `VisitProcedureItem`
  rows at all — never by a date/version flag on the Visit itself."""

from datetime import datetime
from decimal import Decimal
from enum import Enum as PyEnum
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, Enum, ForeignKey, Index, Numeric, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base_entity import BaseEntity
from app.shared.payment_method import PaymentMethod

_MONEY = Numeric(10, 2)

# Stored in Visit.procedure for every visit registered from 2026-08-21
# onward (see Visit.procedure's own docstring) — the column is NOT NULL
# and stays that way unchanged, so a real, obviously-synthetic value is
# written rather than reusing whatever the receptionist's first
# procedure happened to be named (which would risk some future reader
# mistaking it for a real single-procedure summary again, exactly what
# this feature moved away from). No code should ever display this
# string — every reader checks for VisitProcedureItem rows first.
ITEMIZED_PROCEDURE_PLACEHOLDER = "(itemized — see procedure items)"


class VisitStatus(PyEnum):
    """Phase 6 architecture §4.1's Visit Lifecycle State Machine,
    including the `COMPLETED -> PAYMENT_PENDING` reopening transition
    the architecture's own final self-review (§26) identified as the
    missing link between §4.1 and §7.4 (a new Outstanding Invoice
    created after a Visit already reached `COMPLETED` needs a status to
    move back to) — see VisitService.VALID_TRANSITIONS for the full,
    enforced transition table."""

    REGISTERED = "registered"
    WAITING_VITALS = "waiting_vitals"
    WAITING_DOCTOR = "waiting_doctor"
    IN_CONSULTATION = "in_consultation"
    WAITING_BILLING = "waiting_billing"
    PAYMENT_PENDING = "payment_pending"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class VisitPaymentStatus(PyEnum):
    """The registration-charge payment ledger's own status (2026-08-22
    addition) — same three-state shape as
    `app/modules/pharmacy/models.py`'s `MedicineBillStatus`, deliberately
    a distinct Python class rather than a shared/imported one (this
    codebase's established convention: every billable entity gets its
    own status enum, never a cross-module shared one — see that
    module's docstring). `UNPAID` is defined for shape-parity but is not
    reachable through the normal `VisitService.register_visit` flow,
    which always requires a real payment (full or partial) at
    registration — see `Visit.payment_status`'s own column docstring."""

    UNPAID = "unpaid"
    PARTIALLY_PAID = "partially_paid"
    PAID = "paid"


class Visit(BaseEntity):
    """One hospital encounter. `patient_id`/`doctor_user_id` are plain FK
    columns, never `relationship()` — this module never loads a Patient
    or User object through a Visit; callers that need one already have
    it (Reception creates both in the same request) or fetch it
    separately through its owning module, keeping the one-directional
    dependency graph (§12) intact in both directions.

    `queue_token` is the permanent, human-referenceable identifier for
    this Visit (§18) — distinct from Patient.mr_number (identifies the
    *person* across every visit) and never reused/reassigned. Generated
    the same race-safe way as Patient.mr_number (a real Postgres
    SEQUENCE — see VisitRepository.next_queue_token_value)."""

    __tablename__ = "visit"
    __table_args__ = (
        Index(
            "ix_visit_queue_token_active",
            "queue_token",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_visit_patient_id", "patient_id"),
        Index("ix_visit_doctor_user_id", "doctor_user_id"),
        Index("ix_visit_status", "status"),
        CheckConstraint("amount > 0", name="ck_visit_amount_positive"),
        CheckConstraint("discount_amount >= 0", name="ck_visit_discount_amount_non_negative"),
        # Mirrors app/modules/pharmacy/models.py's identical
        # `ck_medicine_bill_amount_paid_non_negative`/
        # `ck_medicine_bill_amount_paid_not_exceeding_total` (2026-08-22
        # addition) — both are NULL-safe without any extra "OR NULL"
        # clause: a Postgres CHECK constraint only rejects a row when
        # its condition evaluates to FALSE, never TRUE/UNKNOWN, and any
        # comparison against a NULL `amount_paid` (every visit that
        # predates payment tracking) evaluates to UNKNOWN, so those rows
        # always pass untouched.
        CheckConstraint("amount_paid >= 0", name="ck_visit_amount_paid_non_negative"),
        CheckConstraint(
            "amount_paid <= amount", name="ck_visit_amount_paid_not_exceeding_amount"
        ),
    )

    patient_id: Mapped[UUID] = mapped_column(ForeignKey("patient.id"), nullable=False)
    # Nullable: fast registration must never block on doctor availability
    # (see reception/service.py's `find_least_busy_available_doctor` —
    # Reception auto-assigns an online doctor when one exists, and
    # otherwise leaves this NULL). A NULL here means "unclaimed" — any
    # doctor with `consultation:start` may claim it by starting the
    # consultation, which assigns this column at that moment (see
    # consultation/service.py's `start_consultation`).
    doctor_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("user.id"))
    queue_token: Mapped[str] = mapped_column(String(20), nullable=False)
    # For a visit registered before 2026-08-21: the real, single
    # procedure name, exactly as it always has been — still the only
    # record of what this visit was for, never touched by the itemized-
    # procedures feature. For a visit registered from 2026-08-21 onward
    # (which always has one or more `VisitProcedureItem` rows instead):
    # `ITEMIZED_PROCEDURE_PLACEHOLDER`, a fixed value nothing ever
    # displays — deliberately kept `NOT NULL` unchanged (not relaxed to
    # nullable) rather than dropped or widened, since this feature was
    # explicitly confirmed to leave every existing column's definition
    # untouched. Every reader — print, every list/detail view, the
    # admin edit dialog — decides which of the two to use purely by
    # checking whether the Visit has any procedure items at all.
    procedure: Mapped[str] = mapped_column(String(200), nullable=False)
    # The visit's total charge. For a pre-2026-08-21 visit: entered once
    # by Reception at registration, exactly as it always has been —
    # Billing reads this value as the invoice's starting line item
    # rather than asking Reception to type the same amount a second time
    # (see billing's GenerateInvoiceRequest usage in the frontend).
    # Already post-discount (2026-08-19 addition, see discount_amount's
    # own docstring below) — every existing reader of this column
    # (Billing's prefill, every revenue aggregate) already treats it as
    # "the real amount". For a visit registered from 2026-08-21 onward:
    # the same post-discount meaning, computed instead from the sum of
    # its `VisitProcedureItem` rows minus `discount_amount` — see
    # VisitService.register_visit's docstring. Either way this column
    # keeps being the one true "how much was this visit billed for"
    # figure every revenue aggregate and Billing's prefill can keep
    # reading directly, with zero changes to either of those call sites.
    amount: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    # A fixed-amount discount applied once, at registration time only
    # (2026-08-19 addition) — same shape and rationale as
    # app/modules/pharmacy/models.py's MedicineBill.discount_amount/
    # discount_reason (itself mirroring Invoice's original convention):
    # `amount` above is already post-discount, the pre-discount original
    # is never stored separately (always cheaply recoverable as `amount
    # + discount_amount`). `discount_reason` is always optional, even
    # when `discount_amount > 0` — same product decision as the
    # medicine-bill discount, not Invoice's own required-reason rule.
    # Independent of, and stacks with, Billing's own separate Invoice-
    # level discount applied later at Generate Invoice time — see
    # VisitService.register_visit's docstring for the full mechanism.
    discount_amount: Mapped[Decimal] = mapped_column(
        _MONEY, nullable=False, default=Decimal("0.00")
    )
    discount_reason: Mapped[str | None] = mapped_column(String(200))
    vitals_required: Mapped[bool] = mapped_column(Boolean, nullable=False)
    status: Mapped[VisitStatus] = mapped_column(
        Enum(
            VisitStatus,
            name="visit_status",
            native_enum=False,
            length=20,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
            create_constraint=True,
        ),
        nullable=False,
        default=VisitStatus.REGISTERED,
    )
    # Registration-time payment tracking (2026-08-22 addition) — a
    # ledger independent of, and parallel to, Billing's own separate
    # Invoice/InvoicePayment (which tracks *additional*, post-
    # consultation charges, not this registration charge). Mirrors
    # `MedicineBill.amount_paid`/`status`/`paid_at` exactly: a
    # maintained running total/derived status, never computed live from
    # `VisitPayment`, updated in the same transaction as each new
    # `VisitPayment` row so it can never drift from `SUM(amount)` there.
    #
    # All three are nullable and, unlike `amount_paid` becoming NOT NULL
    # when the `payment_method` column was retrofitted onto
    # `invoice_payment`/`medicine_bill_payment` (see
    # app/shared/payment_method.py's module docstring), deliberately
    # NEVER backfilled onto any visit that predates this feature — a
    # confirmed, explicit decision, mirroring `VisitProcedureItem`'s own
    # "never retrofitted onto an older Visit" precedent instead of the
    # payment_method precedent: backfilling every existing row to `paid`
    # would make a genuinely legacy visit indistinguishable from a new,
    # fully-paid one, which matters because `VisitHasSettledPaymentError`
    # (see exceptions.py) blocks admin correction once a *new-style*
    # visit is paid/partially paid — a real backfill would silently
    # freeze every old visit's admin tooling too. `payment_status IS
    # NULL` is therefore the permanent, structural signal "this visit
    # predates payment tracking" — every reader (print, the admin
    # edit/delete guard, the Pending Revenue aggregate) branches on it,
    # the same nullable-discriminator idiom `VisitProcedureItem.
    # procedure_id` already established for this feature area. A visit
    # registered from now on always has these three populated —
    # `register_visit` requires a real payment (full or partial, never
    # zero) at registration time, so `UNPAID` is defined for shape-
    # parity with `MedicineBillStatus` but is not reachable through the
    # normal registration flow.
    amount_paid: Mapped[Decimal | None] = mapped_column(_MONEY)
    payment_status: Mapped[VisitPaymentStatus | None] = mapped_column(
        Enum(
            VisitPaymentStatus,
            name="visit_payment_status",
            native_enum=False,
            length=20,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
            create_constraint=True,
        ),
    )
    paid_at: Mapped[datetime | None] = mapped_column()


class Procedure(BaseEntity):
    """The admin-managed procedure price list (2026-08-21 addition) —
    see this module's own docstring for the full rationale. Mirrors
    `app/modules/pharmacy/models.py`'s `Medicine` almost exactly."""

    __tablename__ = "procedure"
    __table_args__ = (
        Index("ix_procedure_name", "name"),
        Index("ix_procedure_is_active", "is_active"),
        CheckConstraint("price > 0", name="ck_procedure_price_positive"),
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    price: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    # "No longer offered" — distinct from `deleted_at`, mirrors
    # Medicine.is_active's identical rationale exactly: deactivated
    # procedures are excluded from Reception's registration-time search
    # but remain visible/re-activatable on the admin management screen.
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class VisitProcedureItem(BaseEntity):
    """One procedure line on a Visit registered from 2026-08-21 onward
    — see this module's own docstring for the full rationale, including
    why this is never retrofitted onto any older Visit."""

    __tablename__ = "visit_procedure_item"
    __table_args__ = (
        Index("ix_visit_procedure_item_visit_id", "visit_id"),
        CheckConstraint("amount > 0", name="ck_visit_procedure_item_amount_positive"),
    )

    visit_id: Mapped[UUID] = mapped_column(ForeignKey("visit.id"), nullable=False)
    # None for a manual/free-typed entry — the per-item (not per-visit)
    # discriminator between the two coexisting shapes this table holds;
    # see this module's own docstring for the full rationale.
    procedure_id: Mapped[UUID | None] = mapped_column(ForeignKey("procedure.id"))
    # Snapshotted from the catalog Procedure's own name at add-time when
    # `procedure_id` is set (so a later rename/deactivation of the
    # catalog entry never rewrites a historical slip — the exact same
    # "billed record is immutable, even if its source changes later"
    # principle `MedicineBillItem.medicine_name_snapshot` already
    # follows), or the receptionist's own free-typed value when
    # `procedure_id` is None.
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # Locked to the catalog Procedure's own price at add-time when
    # `procedure_id` is set — never client-editable in that case,
    # mirroring `MedicineBillItem.unit_price_snapshot`'s identical
    # price-integrity rule exactly (confirmed design decision: unlike
    # `Visit.amount`'s own historically-freely-typed single value, a
    # catalog-selected procedure's price is fixed, same as a medicine's
    # unit price). Freely provided by the receptionist when
    # `procedure_id` is None — a manual entry has no catalog price to
    # lock to at all.
    amount: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)


class VisitPayment(BaseEntity):
    """One payment against a Visit's own registration charge (2026-08-22
    addition) — the append-only audit trail behind `Visit.amount_paid`'s
    maintained running total, the exact same role `MedicineBillPayment`/
    `InvoicePayment` play for their own parent rows (see those models'
    docstrings for the full rationale). Deliberately independent of, and
    never referenced by, Billing's own `Invoice`/`InvoicePayment` — this
    tracks the registration charge collected at (or after) Register
    Visit, a different financial event from Billing's later, separate
    Invoice for additional post-consultation charges; a Visit may have
    both, tracked on entirely separate ledgers, the same way it may
    independently have a `MedicineBill` too.

    Only ever inserted for a visit registered from 2026-08-22 onward
    (one whose `Visit.payment_status` is not `NULL`) — see that column's
    own docstring for why an older visit never gains one of these rows
    retroactively."""

    __tablename__ = "visit_payment"
    __table_args__ = (
        Index("ix_visit_payment_visit_id", "visit_id"),
        CheckConstraint("amount > 0", name="ck_visit_payment_amount_positive"),
    )

    visit_id: Mapped[UUID] = mapped_column(ForeignKey("visit.id"), nullable=False)
    amount: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    # Every individual payment carries its own method (never one method
    # per Visit) — a partial cash payment at registration and a bank
    # transfer top-up weeks later are two separate rows, each correctly
    # attributed. See app/shared/payment_method.py's module docstring.
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

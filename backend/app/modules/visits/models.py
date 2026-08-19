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
without moving the Visit out of `IN_CONSULTATION`."""

from decimal import Decimal
from enum import Enum as PyEnum
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, Enum, ForeignKey, Index, Numeric, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base_entity import BaseEntity

_MONEY = Numeric(10, 2)


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
    procedure: Mapped[str] = mapped_column(String(200), nullable=False)
    # The procedure's price, entered once by Reception at registration —
    # Billing later reads this value as the invoice's starting line item
    # rather than asking Reception to type the same amount a second time
    # (see billing's GenerateInvoiceRequest usage in the frontend).
    # Already post-discount (2026-08-19 addition, see discount_amount's
    # own docstring below) — every existing reader of this column
    # (Billing's prefill, every revenue aggregate) already treats it as
    # "the real amount", so keeping that meaning here is what makes a
    # registration-time discount actually flow through everywhere else
    # in the system for free, rather than needing every such call site
    # updated to separately subtract a discount.
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

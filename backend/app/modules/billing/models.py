"""SQLAlchemy models for the Billing module (Phase 6 architecture §7:
"Reception as Sole Financial Authority"). Registered once into
app/db/model_registry.py's centralized model registry.

Three entities:
- `PendingBillingItem` — a doctor-submitted additional charge request
  (§7.1), never itself a financial transaction until Reception approves
  it and it is folded into an Invoice.
- `Invoice` — the authoritative financial record for a Visit (§7.4).
  Money fields use `Numeric`, never `Float` — `Float` is IEEE-754
  binary floating point, which cannot represent most decimal currency
  values exactly (e.g. 0.1 + 0.2 != 0.3) and is unsuitable for anything
  a hospital bills a patient.
- `InvoiceLineItem` — one charge line on an Invoice, optionally traced
  back to the `PendingBillingItem` it came from.

`Refunded` (§7.4) is deliberately not modeled — explicitly out of scope
for this build; adding it later is an additive enum value, not a
redesign, per the architecture's own "future-ready, reserved" framing."""

from datetime import datetime
from decimal import Decimal
from enum import Enum as PyEnum
from uuid import UUID

from sqlalchemy import CheckConstraint, Enum, ForeignKey, Index, Numeric, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base_entity import BaseEntity

_MONEY = Numeric(10, 2)


class PendingBillingItemStatus(PyEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    BILLED = "billed"


class InvoiceStatus(PyEnum):
    PENDING_PAYMENT = "pending_payment"
    PARTIALLY_PAID = "partially_paid"
    PAID = "paid"
    CANCELLED = "cancelled"


class PendingBillingItem(BaseEntity):
    """`created_by` (from BaseEntity) is the requesting doctor — no
    separate column needed. `BILLED` is a fourth, terminal status beyond
    Phase 6 §7.1's PENDING/APPROVED/REJECTED trio: it marks an APPROVED
    item as already folded into a specific Invoice's line items, so it
    can never be billed a second time if a Visit later gets a second
    Invoice (§7.4's "new Outstanding Invoice" case)."""

    __tablename__ = "pending_billing_item"
    __table_args__ = (
        Index("ix_pending_billing_item_visit_id_status", "visit_id", "status"),
        CheckConstraint("amount > 0", name="ck_pending_billing_item_amount_positive"),
    )

    visit_id: Mapped[UUID] = mapped_column(ForeignKey("visit.id"), nullable=False)
    description: Mapped[str] = mapped_column(String(200), nullable=False)
    amount: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    status: Mapped[PendingBillingItemStatus] = mapped_column(
        Enum(
            PendingBillingItemStatus,
            name="pending_billing_item_status",
            native_enum=False,
            length=20,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
            create_constraint=True,
        ),
        nullable=False,
        default=PendingBillingItemStatus.PENDING,
    )


class Invoice(BaseEntity):
    __tablename__ = "invoice"
    __table_args__ = (
        Index("ix_invoice_visit_id_status", "visit_id", "status"),
        # At most one *open* (unpaid) Invoice per Visit at any time — a
        # real database constraint, not just BillingService.
        # generate_invoice's own "check, then insert" guard, which two
        # concurrent generate calls could otherwise both pass before
        # either commits. Mirrors app/modules/queue/models.py's and
        # app/modules/consultation/models.py's identical single-active-
        # row pattern.
        Index(
            "ix_invoice_visit_id_open_active",
            "visit_id",
            unique=True,
            postgresql_where=text(
                "deleted_at IS NULL AND status IN ('pending_payment', 'partially_paid')"
            ),
        ),
        CheckConstraint("total_amount >= 0", name="ck_invoice_total_amount_non_negative"),
        CheckConstraint("amount_paid >= 0", name="ck_invoice_amount_paid_non_negative"),
        CheckConstraint(
            "amount_paid <= total_amount", name="ck_invoice_amount_paid_not_exceeding_total"
        ),
    )

    visit_id: Mapped[UUID] = mapped_column(ForeignKey("visit.id"), nullable=False)
    status: Mapped[InvoiceStatus] = mapped_column(
        Enum(
            InvoiceStatus,
            name="invoice_status",
            native_enum=False,
            length=20,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
            create_constraint=True,
        ),
        nullable=False,
        default=InvoiceStatus.PENDING_PAYMENT,
    )
    total_amount: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    amount_paid: Mapped[Decimal] = mapped_column(_MONEY, nullable=False, default=Decimal("0.00"))
    paid_at: Mapped[datetime | None] = mapped_column()


class InvoiceLineItem(BaseEntity):
    __tablename__ = "invoice_line_item"
    __table_args__ = (
        Index("ix_invoice_line_item_invoice_id", "invoice_id"),
        CheckConstraint("amount > 0", name="ck_invoice_line_item_amount_positive"),
    )

    invoice_id: Mapped[UUID] = mapped_column(ForeignKey("invoice.id"), nullable=False)
    pending_billing_item_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("pending_billing_item.id")
    )
    description: Mapped[str] = mapped_column(String(200), nullable=False)
    amount: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)

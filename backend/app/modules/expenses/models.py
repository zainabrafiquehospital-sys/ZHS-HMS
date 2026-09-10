"""SQLAlchemy models for the Expense Tracking module.

A standalone module, deliberately not folded into Reception: Reception
owns no table of its own (see app/modules/reception/service.py's
docstring — it is pure cross-module orchestration), so an `Expense`
table cannot live there. Its only inbound coupling is that
ReceptionService reads `ExpenseRepository` (read-only) to subtract a
receptionist's own expense total from her "My Revenue" figure — the
same "compose the already-existing repository" pattern Reception
already uses for Invoice / MedicineBill / LabBill.

`expense_date` is the Asia/Karachi (`settings.display_timezone`)
calendar day the expense was logged, computed server-side at creation
from `datetime.now(ZoneInfo(display_timezone)).date()` — never a
client-supplied value, and never derived by treating a local day key as
a UTC midnight (the day-boundary bug present in several other repos
that do `datetime(d.year, d.month, d.day, tzinfo=UTC)` — not
reproduced here). It is a real `Date` column, distinct from the
inherited UTC `created_at`, so date-wise aggregation is a plain
equality/range on `expense_date` with no timezone maths at read time.
"""

from datetime import date as date_type
from decimal import Decimal
from uuid import UUID

from sqlalchemy import CheckConstraint, Date, ForeignKey, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base_entity import BaseEntity

_MONEY = Numeric(10, 2)


class Expense(BaseEntity):
    """One cash expense a receptionist logs against a given day —
    amount, why, and who was paid. `receptionist_id` is an explicit,
    non-null FK to the owning user (also mirrored onto `BaseEntity.
    created_by` at creation); every edit/delete re-checks
    `receptionist_id == actor.id` in the service. Soft-deleted via
    `deleted_at` like every other `BaseEntity` row — a deleted expense
    is excluded from all sums and from Admin's per-receptionist
    breakdown, but the row is kept."""

    __tablename__ = "expense"
    __table_args__ = (
        # Fast "this receptionist's expenses for this day" — the
        # receptionist's own list and the Net Revenue deduction path.
        Index("ix_expense_receptionist_id_expense_date", "receptionist_id", "expense_date"),
        # Fast "everyone's expenses for this day" — Admin's cross-
        # receptionist list and breakdown.
        Index("ix_expense_expense_date", "expense_date"),
        CheckConstraint("amount > 0", name="ck_expense_amount_positive"),
    )

    # No `ondelete` (default NO ACTION / restrict): unlike
    # `BaseEntity.created_by` (nullable, SET NULL), the owning
    # receptionist is a required attribution fact — and users are
    # soft-deleted in this system, never hard-deleted, so this never
    # actually blocks anything.
    receptionist_id: Mapped[UUID] = mapped_column(ForeignKey("user.id"), nullable=False)
    amount: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    reason: Mapped[str] = mapped_column(String(200), nullable=False)
    recipient_name: Mapped[str] = mapped_column(String(150), nullable=False)
    expense_date: Mapped[date_type] = mapped_column(Date, nullable=False)

"""Pydantic request/response schemas for the Expense module — mirrors
app/modules/lab/schemas.py's conventions (LaxDecimal/LaxUUID under a
strict request model, `from_attributes` + a `from_x` classmethod for
responses)."""

from datetime import date as date_type
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.expenses.models import Expense
from app.shared.schema_types import LaxDecimal

# ---------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------


class CreateExpenseRequest(BaseModel):
    """`expense_date` is NOT a field — it is set server-side to the
    current Asia/Karachi calendar day (same-day-only, no backdating).
    `reason` and `recipient_name` are both required and non-empty."""

    model_config = ConfigDict(strict=True)

    amount: LaxDecimal = Field(gt=0)
    reason: str = Field(min_length=1, max_length=200)
    recipient_name: str = Field(min_length=1, max_length=150)


class UpdateExpenseRequest(BaseModel):
    """Partial update — only `amount`/`reason`/`recipient_name` are ever
    writable (never `expense_date`, `receptionist_id`, or any audit
    column). Same `exclude_unset` PATCH semantics every other update
    endpoint in this codebase uses; the service applies the same
    ownership + same-day-window checks as delete."""

    model_config = ConfigDict(strict=True)

    amount: LaxDecimal | None = Field(default=None, gt=0)
    reason: str | None = Field(default=None, min_length=1, max_length=200)
    recipient_name: str | None = Field(default=None, min_length=1, max_length=150)


# ---------------------------------------------------------------------
# Responses
# ---------------------------------------------------------------------


class ExpenseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    receptionist_id: UUID
    amount: Decimal
    reason: str
    recipient_name: str
    expense_date: date_type
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_expense(cls, expense: Expense) -> "ExpenseOut":
        return cls(
            id=expense.id,
            receptionist_id=expense.receptionist_id,
            amount=expense.amount,
            reason=expense.reason,
            recipient_name=expense.recipient_name,
            expense_date=expense.expense_date,
            created_at=expense.created_at,
            updated_at=expense.updated_at,
        )


class ExpenseBreakdownRowOut(BaseModel):
    """One receptionist's expense rollup for a day — `receptionist_name`
    is resolved server-side (router's `UserService.list_by_ids` batch
    join), `None` when the user can't be resolved, the same convention
    `InventoryUsageEntryOut.created_by_display_name` already uses."""

    model_config = ConfigDict(strict=True)

    receptionist_id: UUID
    receptionist_name: str | None
    expense_count: int
    total_amount: Decimal


class ExpenseBreakdownOut(BaseModel):
    model_config = ConfigDict(strict=True)

    date: date_type
    rows: list[ExpenseBreakdownRowOut]
    total_count: int
    grand_total: Decimal

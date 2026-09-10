"""HTTP endpoints for the Expense Tracking module.

`expenses:log` (Receptionist + admin) covers a receptionist's own
petty-cash lifecycle; `expenses:read_all` (admin only) covers the
cross-receptionist list and per-receptionist breakdown. Every
own-scoped route resolves the target from `actor.id`, never a
request-suppliable id — a receptionist can neither read nor mutate
another receptionist's expense by guessing an id (the id path only
exists on PATCH/DELETE, where `ExpenseService` re-checks ownership and
raises 403). `date` defaults to the current Asia/Karachi day
everywhere it is accepted.
"""

from datetime import date as date_type
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.modules.auth.dependencies import get_user_service, require_permission
from app.modules.auth.models import User
from app.modules.auth.user_service import UserService
from app.modules.expenses.constants import (
    PERMISSION_EXPENSES_LOG,
    PERMISSION_EXPENSES_READ_ALL,
)
from app.modules.expenses.dependencies import get_expense_service
from app.modules.expenses.schemas import (
    CreateExpenseRequest,
    ExpenseBreakdownOut,
    ExpenseBreakdownRowOut,
    ExpenseOut,
    UpdateExpenseRequest,
)
from app.modules.expenses.service import ExpenseService
from app.shared.envelope import success_envelope

router = APIRouter(prefix="/expenses", tags=["expenses"])


@router.post("", status_code=201)
async def create_expense(
    payload: CreateExpenseRequest,
    expense_service: ExpenseService = Depends(get_expense_service),
    actor: User = Depends(require_permission(PERMISSION_EXPENSES_LOG)),
) -> dict:
    """Logs one cash expense against the current Asia/Karachi day. The
    date is server-set (same-day-only, no backdating); the caller is
    recorded as the owning receptionist."""
    expense = await expense_service.create(
        actor=actor,
        amount=payload.amount,
        reason=payload.reason,
        recipient_name=payload.recipient_name,
    )
    return success_envelope(ExpenseOut.from_expense(expense).model_dump(mode="json"))


@router.get("/mine")
async def list_my_expenses(
    date: date_type | None = Query(default=None),
    expense_service: ExpenseService = Depends(get_expense_service),
    actor: User = Depends(require_permission(PERMISSION_EXPENSES_LOG)),
) -> dict:
    """The calling receptionist's own expenses for one day (default:
    today, Asia/Karachi) — newest first. Always `actor.id`; no path or
    query parameter can widen this to anyone else."""
    day = date or expense_service.today_local()
    expenses = await expense_service.list_own_for_day(actor=actor, day=day)
    body = [ExpenseOut.from_expense(expense).model_dump(mode="json") for expense in expenses]
    return success_envelope(body)


@router.get("/stats")
async def get_expense_breakdown(
    date: date_type | None = Query(default=None),
    expense_service: ExpenseService = Depends(get_expense_service),
    user_service: UserService = Depends(get_user_service),
    _actor: User = Depends(require_permission(PERMISSION_EXPENSES_READ_ALL)),
) -> dict:
    """Per-receptionist expense rollup for one day (admin only) —
    `(receptionist, count, total)` rows plus a grand total. Names are
    resolved server-side via the same `UserService.list_by_ids` batch
    join `list_usage_entries` uses."""
    day = date or expense_service.today_local()
    rows = await expense_service.breakdown_for_day(day=day)
    receptionist_ids = [receptionist_id for receptionist_id, _, _ in rows]
    users_by_id = {user.id: user for user in await user_service.list_by_ids(receptionist_ids)}
    body = ExpenseBreakdownOut(
        date=day,
        rows=[
            ExpenseBreakdownRowOut(
                receptionist_id=receptionist_id,
                receptionist_name=(
                    users_by_id[receptionist_id].full_name
                    if receptionist_id in users_by_id
                    else None
                ),
                expense_count=count,
                total_amount=total,
            )
            for receptionist_id, count, total in rows
        ],
        total_count=sum(count for _, count, _ in rows),
        grand_total=sum((total for _, _, total in rows), start=Decimal("0.00")),
    )
    return success_envelope(body.model_dump(mode="json"))


@router.get("")
async def list_all_expenses(
    date: date_type | None = Query(default=None),
    receptionist_id: UUID | None = Query(default=None),
    expense_service: ExpenseService = Depends(get_expense_service),
    _actor: User = Depends(require_permission(PERMISSION_EXPENSES_READ_ALL)),
) -> dict:
    """Every receptionist's expenses for one day (admin only),
    optionally narrowed to a single receptionist — newest first."""
    day = date or expense_service.today_local()
    expenses = await expense_service.list_all_for_day(day=day, receptionist_id=receptionist_id)
    body = [ExpenseOut.from_expense(expense).model_dump(mode="json") for expense in expenses]
    return success_envelope(body)


@router.patch("/{expense_id}")
async def update_expense(
    expense_id: UUID,
    payload: UpdateExpenseRequest,
    expense_service: ExpenseService = Depends(get_expense_service),
    actor: User = Depends(require_permission(PERMISSION_EXPENSES_LOG)),
) -> dict:
    """Owner-only, same-day-only. `ExpenseService.update` raises 403 if
    `actor` is not the owning receptionist and 409
    (`EXPENSE_EDIT_WINDOW_CLOSED`) if the expense's day has rolled
    over. Only amount/reason/recipient_name are writable."""
    expense = await expense_service.update(
        actor=actor,
        expense_id=expense_id,
        updates=payload.model_dump(exclude_unset=True),
    )
    return success_envelope(ExpenseOut.from_expense(expense).model_dump(mode="json"))


@router.delete("/{expense_id}")
async def delete_expense(
    expense_id: UUID,
    expense_service: ExpenseService = Depends(get_expense_service),
    actor: User = Depends(require_permission(PERMISSION_EXPENSES_LOG)),
) -> dict:
    """Owner-only, same-day-only soft-delete — same 403 / 409 rules as
    PATCH. Returns `{"data": null}`."""
    await expense_service.delete(actor=actor, expense_id=expense_id)
    return success_envelope(None)

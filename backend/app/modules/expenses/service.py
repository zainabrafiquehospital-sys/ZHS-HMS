"""Expense Tracking business logic.

Ownership is enforced here, explicitly, on every edit/delete — a
`expense.receptionist_id != actor.id` check that raises
`PermissionDeniedError` (403), exactly the shape
app/modules/consultation/service.py uses for its own writes. The
router's `require_permission(expenses:log)` gate alone is never treated
as sufficient (the finding the Aug-30 doctor-module audit turned up).

Same-day-only applies to edits and deletes too, not just creation:
once `expense_date` is no longer the current Asia/Karachi calendar day
the record is locked (`ExpenseEditWindowClosedError`, a 409). The local
"today" is `datetime.now(ZoneInfo(display_timezone)).date()` — computed
from a real timezone conversion, never by treating a local day key as a
UTC midnight (the day-boundary bug some other repos carry).
"""

from datetime import UTC, datetime
from datetime import date as date_type
from decimal import Decimal
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import PermissionDeniedError, ValidationError
from app.modules.auth.models import User
from app.modules.expenses.exceptions import (
    ExpenseEditWindowClosedError,
    ExpenseNotFoundError,
)
from app.modules.expenses.models import Expense
from app.modules.expenses.repository import ExpenseRepository
from app.shared.audit.repository import AuditLogRepository
from app.shared.money import quantize_money

_WRITABLE_FIELDS = ("amount", "reason", "recipient_name")


class ExpenseService:
    def __init__(
        self,
        *,
        session: AsyncSession,
        expense_repository: ExpenseRepository,
        audit_repository: AuditLogRepository,
        display_timezone: str,
    ) -> None:
        self._session = session
        self._expense_repo = expense_repository
        self._audit_repo = audit_repository
        self._display_timezone = display_timezone

    # -- helpers -------------------------------------------------------

    def today_local(self) -> date_type:
        """Current Asia/Karachi (`settings.display_timezone`) calendar
        day — the one authority on 'today' for same-day-only rules."""
        return datetime.now(ZoneInfo(self._display_timezone)).date()

    @staticmethod
    def _nonblank(value: str, field_label: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValidationError(f"{field_label} cannot be blank.")
        return stripped

    async def _get_owned(self, *, expense_id: UUID, actor: User) -> Expense:
        expense = await self._expense_repo.get_by_id(expense_id)
        if expense is None:
            raise ExpenseNotFoundError
        if expense.receptionist_id != actor.id:
            raise PermissionDeniedError("This expense was not logged by you.")
        return expense

    # -- commands ----------------------------------------------------

    async def create(
        self, *, actor: User, amount: Decimal, reason: str, recipient_name: str
    ) -> Expense:
        expense = Expense(
            receptionist_id=actor.id,
            amount=quantize_money(amount),
            reason=self._nonblank(reason, "Reason"),
            recipient_name=self._nonblank(recipient_name, "Recipient name"),
            expense_date=self.today_local(),
            created_by=actor.id,
            updated_by=actor.id,
        )
        await self._expense_repo.add(expense)
        await self._audit_repo.record(
            module="expenses",
            action="expenses.created",
            entity_type="expense",
            entity_id=expense.id,
            actor_user_id=actor.id,
            metadata={
                "amount": str(expense.amount),
                "recipient_name": expense.recipient_name,
                "expense_date": expense.expense_date.isoformat(),
            },
        )
        await self._session.commit()
        return await self._expense_repo.get_by_id(expense.id, include_deleted=True)

    async def update(self, *, actor: User, expense_id: UUID, updates: dict[str, Any]) -> Expense:
        expense = await self._get_owned(expense_id=expense_id, actor=actor)
        if expense.expense_date != self.today_local():
            raise ExpenseEditWindowClosedError(expense.expense_date.isoformat())

        changed: list[str] = []
        for field in _WRITABLE_FIELDS:
            if field not in updates or updates[field] is None:
                continue
            if field == "amount":
                value = quantize_money(updates["amount"])
            elif field == "reason":
                value = self._nonblank(updates["reason"], "Reason")
            else:
                value = self._nonblank(updates["recipient_name"], "Recipient name")
            if getattr(expense, field) != value:
                setattr(expense, field, value)
                changed.append(field)

        if not changed:
            return expense

        expense.updated_by = actor.id
        await self._expense_repo.add(expense)
        await self._audit_repo.record(
            module="expenses",
            action="expenses.updated",
            entity_type="expense",
            entity_id=expense.id,
            actor_user_id=actor.id,
            metadata={"fields": sorted(changed)},
        )
        await self._session.commit()
        return await self._expense_repo.get_by_id(expense.id, include_deleted=True)

    async def delete(self, *, actor: User, expense_id: UUID) -> None:
        expense = await self._get_owned(expense_id=expense_id, actor=actor)
        if expense.expense_date != self.today_local():
            raise ExpenseEditWindowClosedError(expense.expense_date.isoformat())

        now = datetime.now(UTC)
        await self._audit_repo.record(
            module="expenses",
            action="expenses.deleted",
            entity_type="expense",
            entity_id=expense.id,
            actor_user_id=actor.id,
            metadata={
                "amount": str(expense.amount),
                "recipient_name": expense.recipient_name,
                "expense_date": expense.expense_date.isoformat(),
            },
        )
        await self._expense_repo.soft_delete(expense, deleted_at=now, deleted_by=actor.id)
        await self._session.commit()

    # -- queries ---------------------------------------------------

    async def list_own_for_day(self, *, actor: User, day: date_type) -> list[Expense]:
        return await self._expense_repo.list_for_owner_and_day(receptionist_id=actor.id, day=day)

    async def list_all_for_day(
        self, *, day: date_type, receptionist_id: UUID | None = None
    ) -> list[Expense]:
        return await self._expense_repo.list_for_day(day=day, receptionist_id=receptionist_id)

    async def breakdown_for_day(self, *, day: date_type) -> list[tuple[UUID, int, Decimal]]:
        return await self._expense_repo.breakdown_for_day(day=day)

"""Persistence-only repository for the Expense module — see
app/modules/patients/repository.py's identical "persistence only, no
policy" rationale. Every query here excludes soft-deleted rows
(`deleted_at IS NULL`); ownership and same-day rules live in the
service, never here."""

from datetime import date as date_type
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select

from app.modules.expenses.models import Expense
from app.shared.repository.base_repository import BaseRepository


class ExpenseRepository(BaseRepository[Expense]):
    model = Expense

    async def list_for_owner_and_day(
        self, *, receptionist_id: UUID, day: date_type
    ) -> list[Expense]:
        """One receptionist's own expenses for a single Asia/Karachi
        calendar day, newest first — backs `GET /expenses/mine?date=`."""
        stmt = self._exclude_soft_deleted(
            select(Expense).where(
                Expense.receptionist_id == receptionist_id,
                Expense.expense_date == day,
            ),
            include_deleted=False,
        ).order_by(Expense.created_at.desc(), Expense.id.desc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def sum_for_owner_since(
        self, *, receptionist_id: UUID, since: datetime
    ) -> tuple[int, Decimal]:
        """`(count, total)` of one receptionist's own expenses with
        `created_at > since` — mirrors `VisitRepository.
        count_and_revenue_for_creator`'s exact shape. `since` is the
        rolling `max(last "Clear Revenue", now - 24h)` cutoff
        ReceptionService.get_own_revenue already computes for the
        revenue half; this keeps the expense deduction on the identical
        window so `net_revenue = total_revenue - total_expenses` is
        arithmetically consistent. Returns `Decimal("0.00")`, never
        `None`, for "no matching expenses"."""
        stmt = self._exclude_soft_deleted(
            select(func.count(), func.sum(Expense.amount)).where(
                Expense.receptionist_id == receptionist_id,
                Expense.created_at > since,
            ),
            include_deleted=False,
        )
        count, total = (await self.session.execute(stmt)).one()
        return count, (total if total is not None else Decimal("0.00"))

    async def list_for_day(
        self, *, day: date_type, receptionist_id: UUID | None = None
    ) -> list[Expense]:
        """Every receptionist's expenses for a day (optionally narrowed
        to one), newest first — backs Admin's cross-receptionist
        `GET /expenses?date=&receptionist_id=`."""
        conditions = [Expense.expense_date == day]
        if receptionist_id is not None:
            conditions.append(Expense.receptionist_id == receptionist_id)
        stmt = self._exclude_soft_deleted(
            select(Expense).where(*conditions), include_deleted=False
        ).order_by(Expense.created_at.desc(), Expense.id.desc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def breakdown_for_day(self, *, day: date_type) -> list[tuple[UUID, int, Decimal]]:
        """`(receptionist_id, count, total)` per receptionist for a
        single day — backs Admin's `GET /expenses/stats?date=`
        per-receptionist rollup. Ordered by total desc so the biggest
        spenders surface first."""
        total_col = func.sum(Expense.amount)
        stmt = (
            self._exclude_soft_deleted(
                select(Expense.receptionist_id, func.count(), total_col).where(
                    Expense.expense_date == day
                ),
                include_deleted=False,
            )
            .group_by(Expense.receptionist_id)
            .order_by(total_col.desc())
        )
        result = await self.session.execute(stmt)
        return [(row[0], row[1], row[2]) for row in result.all()]

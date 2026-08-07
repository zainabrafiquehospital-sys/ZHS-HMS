"""Persistence-only repository for the Queue module — see
app/modules/patients/repository.py's identical module docstring for the
"persistence only, no policy" rationale."""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import InstrumentedAttribute

from app.modules.queue.models import QueueDestination, QueueEntry, QueueEntryStatus
from app.shared.repository.base_repository import BaseRepository

QUEUE_ENTRY_SORTABLE_COLUMNS: dict[str, InstrumentedAttribute] = {
    "created_at": QueueEntry.created_at,
}


class QueueEntryRepository(BaseRepository[QueueEntry]):
    model = QueueEntry

    async def get_active_for_visit(self, visit_id: UUID) -> QueueEntry | None:
        """The one currently-open leg for `visit_id` (`left_at IS NULL`)
        — at most one can ever exist, enforced by the partial unique
        index on `(visit_id) WHERE left_at IS NULL` (see models.py)."""
        stmt = self._exclude_soft_deleted(
            select(QueueEntry).where(QueueEntry.visit_id == visit_id, QueueEntry.left_at.is_(None)),
            include_deleted=False,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_history_for_visit(self, visit_id: UUID) -> list[QueueEntry]:
        stmt = self._exclude_soft_deleted(
            select(QueueEntry)
            .where(QueueEntry.visit_id == visit_id)
            .order_by(QueueEntry.created_at.asc()),
            include_deleted=False,
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def worklist(
        self,
        *,
        destination: QueueDestination,
        status: QueueEntryStatus | None,
        sort_column: InstrumentedAttribute,
        limit: int,
        offset: int,
    ) -> tuple[list[QueueEntry], int]:
        """Backs the Doctor Queue / Vitals worklist screens — always
        FIFO (oldest `created_at` first) since Emergency priority
        routing (§24) is explicitly out of scope for this build."""
        conditions = [QueueEntry.deleted_at.is_(None), QueueEntry.destination == destination]
        if status is not None:
            conditions.append(QueueEntry.status == status)

        stmt = select(QueueEntry).where(*conditions)
        total = (
            await self.session.execute(select(func.count()).select_from(stmt.subquery()))
        ).scalar_one()

        stmt = stmt.order_by(sort_column.asc(), QueueEntry.id).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total

    async def count_waiting_by_destination(self) -> dict[QueueDestination, int]:
        """Backs the Reception/Doctor/Vitals Dashboards (§22) — a single
        `GROUP BY` query, not one per destination (no N+1)."""
        stmt = (
            select(QueueEntry.destination, func.count())
            .where(QueueEntry.deleted_at.is_(None), QueueEntry.status == QueueEntryStatus.WAITING)
            .group_by(QueueEntry.destination)
        )
        result = await self.session.execute(stmt)
        return dict(result.all())

"""Queue Management business logic — see app/modules/patients/service.py's
identical module docstring for why this doesn't subclass the shared
`BaseService`.

`route_to` is the one operation every other module (Reception, Vitals,
Consultation) calls to move a Visit between destinations — it always
closes whatever leg is currently open (if any) before opening the new
one, inside a single transaction, so a Visit can never end up with two
simultaneously-active queue entries (also enforced at the database level
— see models.py's partial unique index)."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import User
from app.modules.queue.exceptions import NoActiveQueueEntryError, QueueEntryNotFoundError
from app.modules.queue.models import QueueDestination, QueueEntry, QueueEntryStatus
from app.modules.queue.repository import QUEUE_ENTRY_SORTABLE_COLUMNS, QueueEntryRepository
from app.shared.audit.repository import AuditLogRepository


class QueueService:
    def __init__(
        self,
        session: AsyncSession,
        queue_entry_repository: QueueEntryRepository,
        audit_repository: AuditLogRepository,
    ) -> None:
        self._session = session
        self._queue_repo = queue_entry_repository
        self._audit_repo = audit_repository

    async def _close_active_entry(
        self, *, actor: User, visit_id: UUID, status: QueueEntryStatus, now: datetime
    ) -> QueueEntry | None:
        """Closes the currently-open leg for `visit_id`, if any — returns
        `None` (rather than raising) when there is none, since callers
        like `route_to` legitimately call this for a Visit's very first
        leg, where "no active entry yet" is expected, not an error."""
        active = await self._queue_repo.get_active_for_visit(visit_id)
        if active is None:
            return None
        active.status = status
        active.left_at = now
        active.updated_by = actor.id
        await self._queue_repo.add(active)
        await self._audit_repo.record(
            module="queue",
            action="queue.entry_closed",
            entity_type="queue_entry",
            entity_id=active.id,
            actor_user_id=actor.id,
            metadata={
                "visit_id": str(visit_id),
                "destination": active.destination.value,
                "status": status.value,
            },
        )
        return active

    async def route_to(
        self,
        *,
        actor: User,
        visit_id: UUID,
        destination: QueueDestination,
        reason: str | None = None,
    ) -> QueueEntry:
        """Closes the Visit's current leg (if any) as `COMPLETED` and
        opens a new `WAITING` leg at `destination` — the single choke
        point for every routing change in the system (§5.1, §5.2, §5.3)."""
        now = datetime.now(UTC)
        await self._close_active_entry(
            actor=actor, visit_id=visit_id, status=QueueEntryStatus.COMPLETED, now=now
        )
        entry = QueueEntry(
            visit_id=visit_id,
            destination=destination,
            status=QueueEntryStatus.WAITING,
            reason=reason,
            created_by=actor.id,
            updated_by=actor.id,
        )
        await self._queue_repo.add(entry)
        await self._audit_repo.record(
            module="queue",
            action="queue.routed",
            entity_type="queue_entry",
            entity_id=entry.id,
            actor_user_id=actor.id,
            metadata={
                "visit_id": str(visit_id),
                "destination": destination.value,
                "reason": reason,
            },
        )
        await self._session.commit()
        return await self._queue_repo.get_by_id(entry.id)

    async def start_serving(self, *, actor: User, entry_id: UUID) -> QueueEntry:
        """`WAITING -> IN_PROGRESS` — staff (Reception/Vitals/Doctor)
        begins actively serving this Visit."""
        entry = await self._queue_repo.get_by_id(entry_id)
        if entry is None:
            raise QueueEntryNotFoundError
        entry.status = QueueEntryStatus.IN_PROGRESS
        entry.updated_by = actor.id
        await self._queue_repo.add(entry)
        await self._audit_repo.record(
            module="queue",
            action="queue.entry_started",
            entity_type="queue_entry",
            entity_id=entry.id,
            actor_user_id=actor.id,
            metadata={"visit_id": str(entry.visit_id)},
        )
        await self._session.commit()
        return await self._queue_repo.get_by_id(entry.id)

    async def complete_current(self, *, actor: User, visit_id: UUID) -> QueueEntry:
        """Closes the Visit's current leg with no successor — used when
        the Visit leaves the queue system entirely (e.g. moves to
        Billing, which has no queue destination of its own)."""
        now = datetime.now(UTC)
        closed = await self._close_active_entry(
            actor=actor, visit_id=visit_id, status=QueueEntryStatus.COMPLETED, now=now
        )
        if closed is None:
            raise NoActiveQueueEntryError
        await self._session.commit()
        return closed

    async def cancel_current(self, *, actor: User, visit_id: UUID) -> QueueEntry:
        now = datetime.now(UTC)
        closed = await self._close_active_entry(
            actor=actor, visit_id=visit_id, status=QueueEntryStatus.CANCELLED, now=now
        )
        if closed is None:
            raise NoActiveQueueEntryError
        await self._session.commit()
        return closed

    async def get_active_for_visit(self, visit_id: UUID) -> QueueEntry | None:
        return await self._queue_repo.get_active_for_visit(visit_id)

    async def get_history_for_visit(self, visit_id: UUID) -> list[QueueEntry]:
        return await self._queue_repo.list_history_for_visit(visit_id)

    async def worklist(
        self,
        *,
        destination: QueueDestination,
        status: QueueEntryStatus | None,
        page: int,
        page_size: int,
    ) -> tuple[list[QueueEntry], int]:
        return await self._queue_repo.worklist(
            destination=destination,
            status=status,
            sort_column=QUEUE_ENTRY_SORTABLE_COLUMNS["created_at"],
            limit=page_size,
            offset=(page - 1) * page_size,
        )

    async def count_waiting_by_destination(self) -> dict[QueueDestination, int]:
        """Read-only aggregate added for the Dashboard module (§22)."""
        return await self._queue_repo.count_waiting_by_destination()

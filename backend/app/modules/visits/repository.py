"""Persistence-only repository for the Visit module — see
app/modules/patients/repository.py's identical module docstring for the
"persistence only, no policy" rationale."""

from uuid import UUID

from sqlalchemy import Sequence, func, select, update
from sqlalchemy.orm import InstrumentedAttribute

from app.modules.visits.constants import QUEUE_TOKEN_SEQUENCE_NAME
from app.modules.visits.models import Visit, VisitStatus
from app.shared.repository.base_repository import BaseRepository

VISIT_SORTABLE_COLUMNS: dict[str, InstrumentedAttribute] = {
    "created_at": Visit.created_at,
    "status": Visit.status,
}

# See app/modules/patients/repository.py's `_mr_number_sequence` for the
# identical race-safety rationale, applied here to Queue Token generation.
_queue_token_sequence = Sequence(QUEUE_TOKEN_SEQUENCE_NAME)


class VisitRepository(BaseRepository[Visit]):
    model = Visit

    async def next_queue_token_value(self) -> int:
        result = await self.session.execute(_queue_token_sequence.next_value().select())
        return result.scalar_one()

    async def get_by_queue_token(self, queue_token: str) -> Visit | None:
        stmt = self._exclude_soft_deleted(
            select(Visit).where(Visit.queue_token == queue_token), include_deleted=False
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def search(
        self,
        *,
        patient_id: UUID | None,
        doctor_user_id: UUID | None,
        unassigned_only: bool = False,
        status: VisitStatus | None,
        sort_column: InstrumentedAttribute,
        sort_desc: bool,
        limit: int,
        offset: int,
    ) -> tuple[list[Visit], int]:
        """Backs `GET /visits`. Every filter is optional and additive —
        the Doctor Queue / Vitals worklist screens (built on top of the
        not-yet-built Queue module) will layer their own routing filter
        on top of this; this method only ever filters by Visit's own
        columns.

        `unassigned_only` backs the Doctor Queue's "unclaimed pool" view
        (fast-registration visits Reception couldn't auto-assign — see
        models.py's `doctor_user_id` docstring) — mutually exclusive
        with `doctor_user_id` in practice, but not enforced here; the
        caller (VisitService) owns that policy."""
        conditions = [Visit.deleted_at.is_(None)]
        if patient_id is not None:
            conditions.append(Visit.patient_id == patient_id)
        if unassigned_only:
            conditions.append(Visit.doctor_user_id.is_(None))
        elif doctor_user_id is not None:
            conditions.append(Visit.doctor_user_id == doctor_user_id)
        if status is not None:
            conditions.append(Visit.status == status)

        stmt = select(Visit).where(*conditions)
        total = (
            await self.session.execute(select(func.count()).select_from(stmt.subquery()))
        ).scalar_one()

        order_column = sort_column.desc() if sort_desc else sort_column.asc()
        stmt = stmt.order_by(order_column, Visit.id).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total

    async def assign_doctor_if_unassigned(self, *, visit_id: UUID, doctor_user_id: UUID) -> bool:
        """Conditional claim for an unassigned Visit (`doctor_user_id IS
        NULL`) — a plain `UPDATE ... WHERE doctor_user_id IS NULL`
        rather than a read-then-write, so two doctors racing to claim
        the same unclaimed Visit can never both "win" this column (the
        loser's UPDATE simply matches zero rows). The actual
        authoritative arbiter of who gets to treat the patient is still
        Consultation's own single-active-per-visit unique index (see
        consultation/service.py's `start_consultation`) — this only
        protects the informational `doctor_user_id` column on Visit
        itself from being silently overwritten by a second claim.
        Returns whether a row was actually updated."""
        stmt = (
            update(Visit)
            .where(Visit.id == visit_id, Visit.doctor_user_id.is_(None))
            .values(doctor_user_id=doctor_user_id)
        )
        result = await self.session.execute(stmt)
        return result.rowcount > 0

    async def count_by_status(self) -> dict[VisitStatus, int]:
        """Backs the Reception Dashboard (Phase 6 §22) — a single
        `GROUP BY` query for every status's count, not one query per
        status (which would be exactly the N+1 pattern this project's
        quality bar forbids)."""
        stmt = (
            select(Visit.status, func.count())
            .where(Visit.deleted_at.is_(None))
            .group_by(Visit.status)
        )
        result = await self.session.execute(stmt)
        return dict(result.all())

    async def count_by_creator(self) -> dict[UUID, int]:
        """Backs the Admin "Employee Accounts & Stats" page's per-
        receptionist "visits registered" figure — one `GROUP BY` query
        for every creator's count across all Visits, the same N+1-
        avoidance shape as `count_by_status` above. Visits with a NULL
        `created_by` (none in practice — VisitService.register_visit
        always stamps it — but never assumed) are excluded by the
        `is_not(None)` filter rather than surfacing as a spurious
        `{None: n}` entry the caller would have to special-case."""
        stmt = (
            select(Visit.created_by, func.count())
            .where(Visit.deleted_at.is_(None), Visit.created_by.is_not(None))
            .group_by(Visit.created_by)
        )
        result = await self.session.execute(stmt)
        return dict(result.all())

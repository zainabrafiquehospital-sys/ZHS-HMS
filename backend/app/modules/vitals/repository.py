"""Persistence-only repository for the Vitals module — see
app/modules/patients/repository.py's identical module docstring."""

from uuid import UUID

from sqlalchemy import func, select

from app.modules.vitals.models import VitalsRecord
from app.shared.repository.base_repository import BaseRepository


class VitalsRecordRepository(BaseRepository[VitalsRecord]):
    model = VitalsRecord

    async def list_for_visit(self, visit_id: UUID) -> list[VitalsRecord]:
        stmt = self._exclude_soft_deleted(
            select(VitalsRecord)
            .where(VitalsRecord.visit_id == visit_id)
            .order_by(VitalsRecord.created_at.asc()),
            include_deleted=False,
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_latest_for_visit_ids(self, visit_ids: list[UUID]) -> VitalsRecord | None:
        """Used by VitalsService.get_latest_for_patient to find a
        patient's most recent prior vitals record, given the patient's
        other visit IDs (resolved via VisitService, not looked up here —
        see this module's models.py docstring: Visit is a plain FK
        column, never a `relationship()`, and this repository only ever
        queries its own table, keeping the one-directional module
        dependency graph (§12) intact). Filters purely by
        `visit_id IN (...)`, no cross-table join."""
        if not visit_ids:
            return None
        stmt = self._exclude_soft_deleted(
            select(VitalsRecord)
            .where(VitalsRecord.visit_id.in_(visit_ids))
            .order_by(VitalsRecord.created_at.desc())
            .limit(1),
            include_deleted=False,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_for_visit_ids(self, visit_ids: list[UUID]) -> list[VitalsRecord]:
        """Used by VitalsService.list_for_patient to back the "Show
        Details" cross-visit vitals history view — every vitals record
        recorded across every one of a patient's visits, not just the
        latest (see get_latest_for_visit_ids' identical docstring on why
        this stays a plain `visit_id IN (...)` filter rather than a
        cross-table join). Newest first, matching the history view's own
        "chronological, newest-first" requirement — callers never need
        to re-sort."""
        if not visit_ids:
            return []
        stmt = self._exclude_soft_deleted(
            select(VitalsRecord)
            .where(VitalsRecord.visit_id.in_(visit_ids))
            .order_by(VitalsRecord.created_at.desc()),
            include_deleted=False,
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count_by_creator(self) -> dict[UUID, int]:
        """Backs the Admin "Employee Accounts & Stats" page's per-
        vitals-staff "vitals recorded" figure — one `GROUP BY` query for
        every creator's count, the same N+1-avoidance shape as
        app/modules/visits/repository.py's `count_by_creator`. Records
        with a NULL `created_by` (none in practice — VitalsService.
        record_vitals always stamps it — but never assumed) are
        excluded rather than surfacing as a spurious `{None: n}` entry."""
        stmt = (
            select(VitalsRecord.created_by, func.count())
            .where(VitalsRecord.deleted_at.is_(None), VitalsRecord.created_by.is_not(None))
            .group_by(VitalsRecord.created_by)
        )
        result = await self.session.execute(stmt)
        return dict(result.all())

"""Persistence-only repository for the Vitals module — see
app/modules/patients/repository.py's identical module docstring."""

from uuid import UUID

from sqlalchemy import select

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

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

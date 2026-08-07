"""Persistence-only repository for the Consultation module — see
app/modules/patients/repository.py's identical module docstring."""

from uuid import UUID

from sqlalchemy import select

from app.modules.consultation.models import Consultation, ConsultationStatus
from app.shared.repository.base_repository import BaseRepository

_ACTIVE_STATUSES = (ConsultationStatus.IN_PROGRESS, ConsultationStatus.AWAITING_VITALS)


class ConsultationRepository(BaseRepository[Consultation]):
    model = Consultation

    async def get_active_for_visit(self, visit_id: UUID) -> Consultation | None:
        stmt = self._exclude_soft_deleted(
            select(Consultation).where(
                Consultation.visit_id == visit_id, Consultation.status.in_(_ACTIVE_STATUSES)
            ),
            include_deleted=False,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

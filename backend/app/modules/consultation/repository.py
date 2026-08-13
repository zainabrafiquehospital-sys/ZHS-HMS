"""Persistence-only repository for the Consultation module — see
app/modules/patients/repository.py's identical module docstring."""

from uuid import UUID

from sqlalchemy import func, select

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

    async def count_completed_by_doctor(self) -> dict[UUID, int]:
        """Backs the Admin "Employee Accounts & Stats" page's per-doctor
        "consultations completed" figure — one `GROUP BY` query for
        every doctor's completed count, the same N+1-avoidance shape as
        app/modules/visits/repository.py's `count_by_creator`. Grouped
        by `doctor_user_id` (the doctor who actually ran the
        consultation), not `created_by` (BaseEntity's generic audit
        column) — for a Consultation those are always the same actor in
        practice (only the assigned doctor may start one — see
        `ConsultationService.start_consultation`), but `doctor_user_id`
        is the semantically correct column to group by regardless."""
        stmt = (
            select(Consultation.doctor_user_id, func.count())
            .where(
                Consultation.deleted_at.is_(None),
                Consultation.status == ConsultationStatus.COMPLETED,
            )
            .group_by(Consultation.doctor_user_id)
        )
        result = await self.session.execute(stmt)
        return dict(result.all())

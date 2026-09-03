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

    async def list_for_visit_ids(self, visit_ids: list[UUID]) -> list[Consultation]:
        """Batched sibling of `get_active_for_visit` — every Consultation
        (any status, not only the active one) across the given visits,
        oldest first. Used by the Patient History aggregation module
        (app/modules/patient_history/service.py) to show a patient's
        full consultation history, not just whichever one is currently
        in progress. Mirrors app/modules/vitals/repository.py's
        `list_for_visit_ids` exactly — same N+1-avoidance shape."""
        if not visit_ids:
            return []
        stmt = self._exclude_soft_deleted(
            select(Consultation)
            .where(Consultation.visit_id.in_(visit_ids))
            .order_by(Consultation.created_at.asc()),
            include_deleted=False,
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_completed_for_doctor(
        self, doctor_user_id: UUID, *, page: int, page_size: int
    ) -> tuple[list[Consultation], int]:
        """Real, paginated server-side "every consultation this doctor
        has personally completed" (2026-09-03 addition) — the Doctor
        sibling of `VitalsRecordRepository.list_for_creator` /
        `MedicineBillRepository.list_for_creator`, backing the Doctor
        dashboard's "My Consultations" screen the same way those back
        Vitals' and Pharmacy's own "my records" lists. Newest first by
        `completed_at`, no date restriction — a real server-side filter,
        never a client-side "fetch N most recent" approximation.

        Scoped by `doctor_user_id` (the doctor who ran the consultation),
        not `created_by` — for a Consultation those are always the same
        actor in practice (only the assigned doctor may start one), but
        `doctor_user_id` is the semantically correct column, matching
        `count_completed_by_doctor` below. `status == COMPLETED` only:
        an in-progress / awaiting-vitals / cancelled consultation is not
        a browsable record."""
        stmt = self._exclude_soft_deleted(
            select(Consultation).where(
                Consultation.doctor_user_id == doctor_user_id,
                Consultation.status == ConsultationStatus.COMPLETED,
            ),
            include_deleted=False,
        )
        total = (
            await self.session.execute(select(func.count()).select_from(stmt.subquery()))
        ).scalar_one()

        stmt = (
            stmt.order_by(Consultation.completed_at.desc())
            .limit(page_size)
            .offset((page - 1) * page_size)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total

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

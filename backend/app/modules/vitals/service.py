"""Vitals business logic. Orchestrates VisitService, QueueService, and
ConsultationService the same way app/modules/reception/service.py does
— see that module's docstring for the identical "sequential
orchestration across independently-committing services" rationale.

`record_vitals` is where Phase 6 §5.1/§5.2's two vitals scopes converge
onto one routing decision:
- No active Consultation for the Visit -> this is Workflow A intake
  (Reception routed straight to Vitals before any doctor touch). On
  completion, the Visit itself moves `WAITING_VITALS -> WAITING_DOCTOR`
  (VisitService), and Queue routes to DOCTOR.
- An active (`AWAITING_VITALS`) Consultation exists -> this is a
  doctor-requested detour (§5.2). The Visit stays `IN_CONSULTATION`
  throughout (§4.1) — only the Consultation itself resumes
  (`ConsultationService.resume_from_vitals`) and Queue routes to DOCTOR.
Either way, the same doctor gets the Visit back — enforced upstream by
Visit.doctor_user_id never changing and Consultation's own doctor-
ownership check (see app/modules/consultation/service.py)."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import User
from app.modules.consultation.service import ConsultationService
from app.modules.queue.models import QueueDestination
from app.modules.queue.service import QueueService
from app.modules.visits.service import VisitService
from app.modules.vitals.exceptions import VitalsRecordNotFoundError
from app.modules.vitals.models import VitalsRecord
from app.modules.vitals.repository import VitalsRecordRepository
from app.shared.audit.repository import AuditLogRepository


class VitalsService:
    def __init__(
        self,
        session: AsyncSession,
        vitals_record_repository: VitalsRecordRepository,
        visit_service: VisitService,
        queue_service: QueueService,
        consultation_service: ConsultationService,
        audit_repository: AuditLogRepository,
    ) -> None:
        self._session = session
        self._vitals_repo = vitals_record_repository
        self._visit_service = visit_service
        self._queue_service = queue_service
        self._consultation_service = consultation_service
        self._audit_repo = audit_repository

    async def record_vitals(
        self,
        *,
        actor: User,
        visit_id: UUID,
        systolic_bp: int | None,
        diastolic_bp: int | None,
        pulse_rate: int | None,
        temperature_celsius: float | None,
        weight_kg: float | None,
        height_cm: float | None,
        spo2_percent: int | None,
        notes: str | None,
    ) -> VitalsRecord:
        active_consultation = await self._consultation_service.get_active_for_visit(visit_id)

        record = VitalsRecord(
            visit_id=visit_id,
            consultation_id=active_consultation.id if active_consultation else None,
            systolic_bp=systolic_bp,
            diastolic_bp=diastolic_bp,
            pulse_rate=pulse_rate,
            temperature_celsius=temperature_celsius,
            weight_kg=weight_kg,
            height_cm=height_cm,
            spo2_percent=spo2_percent,
            notes=notes,
            created_by=actor.id,
            updated_by=actor.id,
        )
        await self._vitals_repo.add(record)
        await self._audit_repo.record(
            module="vitals",
            action="vitals.recorded",
            entity_type="vitals_record",
            entity_id=record.id,
            actor_user_id=actor.id,
            metadata={
                "visit_id": str(visit_id),
                "is_doctor_requested_detour": active_consultation is not None,
            },
        )
        await self._session.commit()

        await self._queue_service.route_to(
            actor=actor,
            visit_id=visit_id,
            destination=QueueDestination.DOCTOR,
            reason="vitals_completed",
        )
        if active_consultation is not None:
            await self._consultation_service.resume_from_vitals(actor=actor, visit_id=visit_id)
        else:
            await self._visit_service.mark_waiting_doctor(actor=actor, visit_id=visit_id)

        return await self._vitals_repo.get_by_id(record.id)

    async def get_vitals_record(self, vitals_record_id: UUID) -> VitalsRecord:
        record = await self._vitals_repo.get_by_id(vitals_record_id)
        if record is None:
            raise VitalsRecordNotFoundError
        return record

    async def list_for_visit(self, visit_id: UUID) -> list[VitalsRecord]:
        return await self._vitals_repo.list_for_visit(visit_id)

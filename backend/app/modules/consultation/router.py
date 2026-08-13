"""HTTP endpoints for the Consultation module."""

from uuid import UUID

from fastapi import APIRouter, Depends

from app.modules.auth.dependencies import require_permission
from app.modules.auth.models import User
from app.modules.consultation.constants import (
    PERMISSION_CONSULTATION_MANAGE,
    PERMISSION_CONSULTATION_READ,
    PERMISSION_CONSULTATION_START,
)
from app.modules.consultation.dependencies import get_consultation_service
from app.modules.consultation.schemas import (
    CompleteConsultationRequest,
    ConsultationDoctorStatOut,
    ConsultationOut,
    SendToVitalsRequest,
    StartConsultationRequest,
)
from app.modules.consultation.service import ConsultationService
from app.shared.envelope import success_envelope

router = APIRouter(prefix="/consultations", tags=["consultations"])


@router.post("", status_code=201)
async def start_consultation(
    payload: StartConsultationRequest,
    consultation_service: ConsultationService = Depends(get_consultation_service),
    actor: User = Depends(require_permission(PERMISSION_CONSULTATION_START)),
) -> dict:
    consultation = await consultation_service.start_consultation(
        actor=actor, visit_id=payload.visit_id
    )
    return success_envelope(ConsultationOut.from_consultation(consultation).model_dump(mode="json"))


@router.get("/stats/by-doctor")
async def get_consultation_stats_by_doctor(
    consultation_service: ConsultationService = Depends(get_consultation_service),
    _actor: User = Depends(require_permission(PERMISSION_CONSULTATION_READ)),
) -> dict:
    """Read-only aggregate added for the Admin "Employee Accounts &
    Stats" page — one row per doctor with at least one completed
    consultation, each with their all-time completed count. Not
    paginated: bounded by the number of distinct doctors, not
    consultation volume (see ConsultationRepository.
    count_completed_by_doctor)."""
    counts = await consultation_service.count_completed_by_doctor()
    body = [
        ConsultationDoctorStatOut(user_id=user_id, count=count).model_dump(mode="json")
        for user_id, count in counts.items()
    ]
    return success_envelope(body)


@router.get("/{consultation_id}")
async def get_consultation(
    consultation_id: UUID,
    consultation_service: ConsultationService = Depends(get_consultation_service),
    _actor: User = Depends(require_permission(PERMISSION_CONSULTATION_READ)),
) -> dict:
    consultation = await consultation_service.get_consultation(consultation_id)
    return success_envelope(ConsultationOut.from_consultation(consultation).model_dump(mode="json"))


@router.get("/visits/{visit_id}/active")
async def get_active_for_visit(
    visit_id: UUID,
    consultation_service: ConsultationService = Depends(get_consultation_service),
    _actor: User = Depends(require_permission(PERMISSION_CONSULTATION_READ)),
) -> dict:
    consultation = await consultation_service.get_active_for_visit(visit_id)
    body = (
        ConsultationOut.from_consultation(consultation).model_dump(mode="json")
        if consultation
        else None
    )
    return success_envelope(body)


@router.post("/{consultation_id}/send-to-vitals")
async def send_to_vitals(
    consultation_id: UUID,
    payload: SendToVitalsRequest,
    consultation_service: ConsultationService = Depends(get_consultation_service),
    actor: User = Depends(require_permission(PERMISSION_CONSULTATION_MANAGE)),
) -> dict:
    consultation = await consultation_service.send_to_vitals(
        actor=actor, consultation_id=consultation_id, reason=payload.reason
    )
    return success_envelope(ConsultationOut.from_consultation(consultation).model_dump(mode="json"))


@router.post("/{consultation_id}/complete")
async def complete_consultation(
    consultation_id: UUID,
    payload: CompleteConsultationRequest,
    consultation_service: ConsultationService = Depends(get_consultation_service),
    actor: User = Depends(require_permission(PERMISSION_CONSULTATION_MANAGE)),
) -> dict:
    consultation = await consultation_service.complete_consultation(
        actor=actor,
        consultation_id=consultation_id,
        updates=payload.model_dump(exclude_unset=True),
    )
    return success_envelope(ConsultationOut.from_consultation(consultation).model_dump(mode="json"))

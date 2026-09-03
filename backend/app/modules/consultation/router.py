"""HTTP endpoints for the Consultation module."""

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse

from app.core.config import Settings, get_settings
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
from app.modules.patients.dependencies import get_patient_service
from app.modules.patients.service import PatientService
from app.modules.visits.dependencies import get_visit_service
from app.modules.visits.service import VisitService
from app.shared.envelope import success_envelope
from app.shared.pagination import PaginationMeta
from app.shared.printing.service import render_prescription_slip

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


@router.get("/mine")
async def list_my_consultations(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    consultation_service: ConsultationService = Depends(get_consultation_service),
    actor: User = Depends(require_permission(PERMISSION_CONSULTATION_READ)),
) -> dict:
    """The calling doctor's own "My Consultations" — every consultation
    they have personally completed, newest first, real server-side
    pagination, no date restriction (2026-09-03 addition — the Doctor
    sibling of `GET /vitals/records/mine` and Reception's "My
    Registrations"). Declared before `GET /{consultation_id}` so the
    literal `mine` segment is never captured as a UUID path param, the
    same ordering `GET /stats/by-doctor` above already relies on.

    Always `actor.id`, never a request-suppliable user id — the same
    hard server-side "your own work only" scoping every other `mine`
    endpoint in this app establishes; there is structurally no way to
    ask for a colleague's consultations through this endpoint. Rows are
    the plain `ConsultationOut` (which already carries `visit_id` and
    every clinical field); the caller joins visit -> patient itself, the
    same client-side join `MyVitalsRecords.jsx` already does."""
    consultations, total = await consultation_service.list_completed_for_doctor(
        actor.id, page=page, page_size=page_size
    )
    body = [
        ConsultationOut.from_consultation(consultation).model_dump(mode="json")
        for consultation in consultations
    ]
    meta = PaginationMeta(page=page, page_size=page_size, total=total).model_dump(mode="json")
    return success_envelope(body, meta)


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


@router.get("/{consultation_id}/slip/print", response_class=HTMLResponse)
async def print_prescription_slip(
    consultation_id: UUID,
    consultation_service: ConsultationService = Depends(get_consultation_service),
    visit_service: VisitService = Depends(get_visit_service),
    patient_service: PatientService = Depends(get_patient_service),
    settings: Settings = Depends(get_settings),
    _actor: User = Depends(require_permission(PERMISSION_CONSULTATION_READ)),
) -> HTMLResponse:
    """The doctor's prescription slip — same Central Print Service
    pattern as Billing's invoice print and Reception's registration
    slip (this module decides *whether* it may be printed, via the same
    `consultation:read` gate as viewing it, and supplies the data; the
    shared printing service only renders it — Phase 6 §14). Unlike those
    two this is a full-page layout meant to overprint paper already
    bearing the hospital's own letterhead, so `render_prescription_slip`
    draws no hospital identity itself — see its docstring."""
    consultation = await consultation_service.get_consultation(consultation_id)
    visit = await visit_service.get_visit(consultation.visit_id)
    patient = await patient_service.get_patient(visit.patient_id)

    html_document = render_prescription_slip(
        hospital_name=settings.app_name,
        visit_queue_token=visit.queue_token,
        patient_full_name=patient.full_name,
        patient_age_years=patient.age_years,
        history_of=consultation.history_of,
        complaint_of=consultation.complaint_of,
        advised=consultation.advised,
        diagnosis=consultation.diagnosis,
        prescription=consultation.prescription,
    )
    return HTMLResponse(content=html_document)

"""HTTP endpoints for the Reception module — the composite "register a
visit" and "cancel a visit" actions (Phase 6 architecture §6), plus the
fast-registration slip print endpoint (§6/§7)."""

from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse

from app.core.config import Settings, get_settings
from app.modules.auth.dependencies import get_user_service, require_permission
from app.modules.auth.models import User
from app.modules.auth.user_service import UserService
from app.modules.patients.dependencies import get_patient_service
from app.modules.patients.schemas import PatientOut
from app.modules.patients.service import PatientService
from app.modules.queue.schemas import QueueEntryOut
from app.modules.reception.constants import (
    PERMISSION_RECEPTION_CANCEL_VISIT,
    PERMISSION_RECEPTION_REGISTER_VISIT,
)
from app.modules.reception.dependencies import get_reception_service
from app.modules.reception.schemas import (
    CancelVisitRequest,
    RegisterVisitRequest,
    RegisterVisitResponse,
)
from app.modules.reception.service import ReceptionService
from app.modules.visits.dependencies import get_visit_service
from app.modules.visits.schemas import VisitOut
from app.modules.visits.service import VisitService
from app.shared.envelope import success_envelope
from app.shared.printing.service import render_registration_slip

router = APIRouter(prefix="/reception", tags=["reception"])


@router.post("/visits", status_code=201)
async def register_visit(
    payload: RegisterVisitRequest,
    reception_service: ReceptionService = Depends(get_reception_service),
    actor: User = Depends(require_permission(PERMISSION_RECEPTION_REGISTER_VISIT)),
) -> dict:
    patient, visit, queue_entry = await reception_service.register_visit(
        actor=actor,
        patient_id=payload.patient_id,
        new_patient=payload.new_patient.model_dump() if payload.new_patient else None,
        doctor_user_id=None,
        procedure=payload.procedure,
        amount=payload.amount,
        vitals_required=payload.vitals_required,
    )
    response = RegisterVisitResponse(
        patient=PatientOut.from_patient(patient),
        visit=VisitOut.from_visit(visit),
        queue_entry=QueueEntryOut.from_entry(queue_entry),
    )
    return success_envelope(response.model_dump(mode="json"))


@router.get("/visits/{visit_id}/slip/print", response_class=HTMLResponse)
async def print_registration_slip(
    visit_id: UUID,
    patient_service: PatientService = Depends(get_patient_service),
    visit_service: VisitService = Depends(get_visit_service),
    user_service: UserService = Depends(get_user_service),
    settings: Settings = Depends(get_settings),
    _actor: User = Depends(require_permission(PERMISSION_RECEPTION_REGISTER_VISIT)),
) -> HTMLResponse:
    """Same Central Print Service pattern as Billing's invoice print
    endpoint (app/modules/billing/router.py) — Reception decides
    *whether* this may be printed (the same `reception:register_visit`
    gate as registering it) and supplies the data; the shared printing
    service only renders it (Phase 6 §14)."""
    visit = await visit_service.get_visit(visit_id)
    patient = await patient_service.get_patient(visit.patient_id)
    doctor_full_name = None
    if visit.doctor_user_id is not None:
        doctor = await user_service.get_user(visit.doctor_user_id)
        doctor_full_name = doctor.full_name

    html_document = render_registration_slip(
        hospital_name=settings.app_name,
        display_timezone=settings.display_timezone,
        patient_full_name=patient.full_name,
        patient_mr_number=patient.mr_number,
        patient_age_years=patient.age_years,
        patient_phone_number=patient.phone_number,
        visit_queue_token=visit.queue_token,
        visit_procedure=visit.procedure,
        visit_amount=visit.amount,
        visit_created_at=visit.created_at,
        assigned_doctor_full_name=doctor_full_name,
    )
    return HTMLResponse(content=html_document)


@router.post("/visits/{visit_id}/cancel")
async def cancel_visit(
    visit_id: UUID,
    payload: CancelVisitRequest,
    reception_service: ReceptionService = Depends(get_reception_service),
    actor: User = Depends(require_permission(PERMISSION_RECEPTION_CANCEL_VISIT)),
) -> dict:
    visit = await reception_service.cancel_visit(
        actor=actor, visit_id=visit_id, reason=payload.reason
    )
    return success_envelope(VisitOut.from_visit(visit).model_dump(mode="json"))

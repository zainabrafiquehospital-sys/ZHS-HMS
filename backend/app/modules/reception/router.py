"""HTTP endpoints for the Reception module — the composite "register a
visit" and "cancel a visit" actions (Phase 6 architecture §6), the
fast-registration slip print endpoint (§6/§7), admin-only "update"/
"delete" data-correction actions for a mistakenly-entered visit (see
AdminUpdateVisitRequest's and ReceptionService.admin_delete_visit's own
docstrings), and (2026-08-19 addition) a receptionist's own "My Revenue"
read/clear actions — see ReceptionRevenueOut's and ReceptionService.
get_own_revenue's own docstrings."""

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
    PERMISSION_RECEPTION_CLEAR_OWN_REVENUE,
    PERMISSION_RECEPTION_DELETE_VISIT,
    PERMISSION_RECEPTION_REGISTER_VISIT,
    PERMISSION_RECEPTION_UPDATE_VISIT,
)
from app.modules.reception.dependencies import get_reception_service
from app.modules.reception.schemas import (
    AdminUpdateVisitRequest,
    AdminUpdateVisitResponse,
    CancelVisitRequest,
    ClearRevenueResponse,
    ReceptionRevenueOut,
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
        discount_amount=payload.discount_amount,
        discount_reason=payload.discount_reason,
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
        visit_discount_amount=visit.discount_amount,
        visit_discount_reason=visit.discount_reason,
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


# ------------------------------------------------------------------
# Admin data correction (2026-08-19 addition) — gated on
# reception:update_visit / reception:delete_visit, never on
# register_visit/cancel_visit, and never granted to Receptionist (see
# constants.py). Ownership never matters here: an admin may act on any
# receptionist's slip, not only their own — the permission check alone
# is what authorizes that, exactly like every other RBAC-gated action
# in this codebase.
# ------------------------------------------------------------------


@router.patch("/visits/{visit_id}")
async def update_visit(
    visit_id: UUID,
    payload: AdminUpdateVisitRequest,
    reception_service: ReceptionService = Depends(get_reception_service),
    actor: User = Depends(require_permission(PERMISSION_RECEPTION_UPDATE_VISIT)),
) -> dict:
    """Corrects a wrongly-entered slip — patient identity fields and/or
    the visit's own procedure/amount, in one call (see
    AdminUpdateVisitRequest's own docstring for why this is a single
    flat form rather than two separate requests)."""
    patient, visit = await reception_service.admin_update_visit(
        actor=actor, visit_id=visit_id, updates=payload.model_dump(exclude_unset=True)
    )
    response = AdminUpdateVisitResponse(
        patient=PatientOut.from_patient(patient), visit=VisitOut.from_visit(visit)
    )
    return success_envelope(response.model_dump(mode="json"))


@router.delete("/visits/{visit_id}")
async def delete_visit(
    visit_id: UUID,
    reception_service: ReceptionService = Depends(get_reception_service),
    actor: User = Depends(require_permission(PERMISSION_RECEPTION_DELETE_VISIT)),
) -> dict:
    """Soft-deletes a visit registered by mistake (see ReceptionService.
    admin_delete_visit's own docstring for the full safety story,
    including the paid-invoice block). The Visit's own `patient` row is
    never touched or deleted — only the Visit itself, which is what
    makes this safe to call even against a Patient with other, real
    visits on file."""
    await reception_service.admin_delete_visit(actor=actor, visit_id=visit_id)
    return success_envelope(None)


# ------------------------------------------------------------------
# "My Revenue" (2026-08-19 addition) — always the calling receptionist's
# own figures, structurally: neither endpoint below accepts a target
# user id at all, matching how GET /dashboard/doctor is hard-scoped to
# `actor.id` and never a request parameter. Reading is gated on
# reception:register_visit (every receptionist already holds it — the
# same base permission "My Revenue"/"My Slips" implicitly relied on via
# visits:read before this endpoint existed); clearing gets its own
# atomic permission, matching this module's register/cancel/update/
# delete convention.
# ------------------------------------------------------------------


@router.get("/revenue")
async def get_own_revenue(
    reception_service: ReceptionService = Depends(get_reception_service),
    actor: User = Depends(require_permission(PERMISSION_RECEPTION_REGISTER_VISIT)),
) -> dict:
    visits_count, visits_revenue, medicine_count, medicine_revenue, cleared_at = (
        await reception_service.get_own_revenue(actor=actor)
    )
    body = ReceptionRevenueOut(
        visits_count=visits_count,
        visits_revenue=visits_revenue,
        medicine_bill_count=medicine_count,
        medicine_revenue=medicine_revenue,
        total_revenue=visits_revenue + medicine_revenue,
        cleared_at=cleared_at,
    )
    return success_envelope(body.model_dump(mode="json"))


@router.post("/revenue/clear")
async def clear_own_revenue(
    reception_service: ReceptionService = Depends(get_reception_service),
    actor: User = Depends(require_permission(PERMISSION_RECEPTION_CLEAR_OWN_REVENUE)),
) -> dict:
    """Resets the calling receptionist's own "My Revenue" display to
    zero going forward — see ReceptionService.clear_own_revenue's own
    docstring: no visit, invoice, payment, or medicine bill is ever
    touched, only a new audit_log row recording that this happened."""
    cleared_at = await reception_service.clear_own_revenue(actor=actor)
    body = ClearRevenueResponse(cleared_at=cleared_at)
    return success_envelope(body.model_dump(mode="json"))

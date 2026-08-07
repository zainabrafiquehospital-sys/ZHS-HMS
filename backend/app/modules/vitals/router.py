"""HTTP endpoints for the Vitals module."""

from uuid import UUID

from fastapi import APIRouter, Depends

from app.modules.auth.dependencies import require_permission
from app.modules.auth.models import User
from app.modules.vitals.constants import PERMISSION_VITALS_READ, PERMISSION_VITALS_RECORD
from app.modules.vitals.dependencies import get_vitals_service
from app.modules.vitals.schemas import RecordVitalsRequest, VitalsRecordOut
from app.modules.vitals.service import VitalsService
from app.shared.envelope import success_envelope

router = APIRouter(prefix="/vitals", tags=["vitals"])


@router.post("", status_code=201)
async def record_vitals(
    payload: RecordVitalsRequest,
    vitals_service: VitalsService = Depends(get_vitals_service),
    actor: User = Depends(require_permission(PERMISSION_VITALS_RECORD)),
) -> dict:
    record = await vitals_service.record_vitals(
        actor=actor,
        visit_id=payload.visit_id,
        systolic_bp=payload.systolic_bp,
        diastolic_bp=payload.diastolic_bp,
        pulse_rate=payload.pulse_rate,
        temperature_celsius=payload.temperature_celsius,
        weight_kg=payload.weight_kg,
        height_cm=payload.height_cm,
        spo2_percent=payload.spo2_percent,
        notes=payload.notes,
    )
    return success_envelope(VitalsRecordOut.from_record(record).model_dump(mode="json"))


@router.get("/visits/{visit_id}")
async def list_for_visit(
    visit_id: UUID,
    vitals_service: VitalsService = Depends(get_vitals_service),
    _actor: User = Depends(require_permission(PERMISSION_VITALS_READ)),
) -> dict:
    records = await vitals_service.list_for_visit(visit_id)
    body = [VitalsRecordOut.from_record(record).model_dump(mode="json") for record in records]
    return success_envelope(body)

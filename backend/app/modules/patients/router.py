"""HTTP endpoints for the Patient module. Every endpoint requires the
matching `patients:*` permission via the existing `require_permission()`
dependency factory (Phase 5), mirroring app/modules/auth/role_router.py's
convention exactly. `GET /patients` doubles as the Patient Search MVP
module's endpoint — `search` matches name, MR number, phone number, or
CNIC (see repository.py's `search` docstring)."""

from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.modules.auth.dependencies import require_permission
from app.modules.auth.models import User
from app.modules.patients.constants import (
    PERMISSION_PATIENTS_CREATE,
    PERMISSION_PATIENTS_READ,
    PERMISSION_PATIENTS_UPDATE,
)
from app.modules.patients.dependencies import get_patient_service
from app.modules.patients.schemas import (
    CreatePatientRequest,
    PatientOut,
    PatientSortField,
    UpdatePatientRequest,
)
from app.modules.patients.service import PatientService
from app.shared.envelope import success_envelope
from app.shared.pagination import PaginationMeta, SortOrder

router = APIRouter(prefix="/patients", tags=["patients"])


@router.post("", status_code=201)
async def register_patient(
    payload: CreatePatientRequest,
    patient_service: PatientService = Depends(get_patient_service),
    actor: User = Depends(require_permission(PERMISSION_PATIENTS_CREATE)),
) -> dict:
    patient = await patient_service.register_patient(
        actor=actor,
        full_name=payload.full_name,
        guardian_name=payload.guardian_name,
        gender=payload.gender,
        age_years=payload.age_years,
        phone_number=payload.phone_number,
        cnic=payload.cnic,
        address=payload.address,
    )
    return success_envelope(PatientOut.from_patient(patient).model_dump(mode="json"))


@router.get("")
async def list_patients(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    search: str | None = Query(default=None, max_length=150),
    sort_by: PatientSortField = Query(default=PatientSortField.CREATED_AT),
    sort_order: SortOrder = Query(default=SortOrder.DESC),
    patient_service: PatientService = Depends(get_patient_service),
    _actor: User = Depends(require_permission(PERMISSION_PATIENTS_READ)),
) -> dict:
    patients, total = await patient_service.list_patients(
        search=search,
        sort_by=sort_by.value,
        sort_desc=sort_order == SortOrder.DESC,
        page=page,
        page_size=page_size,
    )
    body = [PatientOut.from_patient(patient).model_dump(mode="json") for patient in patients]
    meta = PaginationMeta(page=page, page_size=page_size, total=total).model_dump(mode="json")
    return success_envelope(body, meta)


@router.get("/{patient_id}")
async def get_patient(
    patient_id: UUID,
    patient_service: PatientService = Depends(get_patient_service),
    _actor: User = Depends(require_permission(PERMISSION_PATIENTS_READ)),
) -> dict:
    patient = await patient_service.get_patient(patient_id)
    return success_envelope(PatientOut.from_patient(patient).model_dump(mode="json"))


@router.patch("/{patient_id}")
async def update_patient(
    patient_id: UUID,
    payload: UpdatePatientRequest,
    patient_service: PatientService = Depends(get_patient_service),
    actor: User = Depends(require_permission(PERMISSION_PATIENTS_UPDATE)),
) -> dict:
    updated = await patient_service.update_patient(
        actor=actor, patient_id=patient_id, updates=payload.model_dump(exclude_unset=True)
    )
    return success_envelope(PatientOut.from_patient(updated).model_dump(mode="json"))

"""HTTP endpoints for the Pharmacy / Medicine Billing module. Medicine
price-list management requires `pharmacy:manage` (Admin-only); searching
the price list and viewing/printing bills requires `pharmacy:read`;
creating a bill requires `pharmacy:bill` — see constants.py's module
docstring for the segregation-of-duties rationale, matching Billing's
identical permission split."""

from datetime import date as date_type
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse

from app.core.config import Settings, get_settings
from app.modules.auth.dependencies import require_permission
from app.modules.auth.models import User
from app.modules.patients.dependencies import get_patient_service
from app.modules.patients.service import PatientService
from app.modules.pharmacy.constants import (
    PERMISSION_PHARMACY_BILL,
    PERMISSION_PHARMACY_MANAGE,
    PERMISSION_PHARMACY_READ,
)
from app.modules.pharmacy.dependencies import get_pharmacy_service
from app.modules.pharmacy.schemas import (
    CreateMedicineBillRequest,
    CreateMedicineRequest,
    MedicineBillOut,
    MedicineBillSummaryOut,
    MedicineOut,
    MedicineSortField,
    UpdateMedicineRequest,
)
from app.modules.pharmacy.service import PharmacyService
from app.modules.visits.dependencies import get_visit_service
from app.modules.visits.service import VisitService
from app.shared.envelope import success_envelope
from app.shared.pagination import PaginationMeta, SortOrder
from app.shared.printing.service import render_medicine_bill_receipt

router = APIRouter(prefix="/pharmacy", tags=["pharmacy"])


# ----------------------------------------------------------------------
# Medicine price list — Admin-only management
# ----------------------------------------------------------------------


@router.post("/medicines", status_code=201)
async def create_medicine(
    payload: CreateMedicineRequest,
    pharmacy_service: PharmacyService = Depends(get_pharmacy_service),
    actor: User = Depends(require_permission(PERMISSION_PHARMACY_MANAGE)),
) -> dict:
    medicine = await pharmacy_service.create_medicine(
        actor=actor,
        name=payload.name,
        category=payload.category,
        unit_price=payload.unit_price,
    )
    return success_envelope(MedicineOut.from_medicine(medicine).model_dump(mode="json"))


@router.get("/medicines")
async def list_medicines(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    search: str | None = Query(default=None, max_length=150),
    sort_by: MedicineSortField = Query(default=MedicineSortField.NAME),
    sort_order: SortOrder = Query(default=SortOrder.ASC),
    pharmacy_service: PharmacyService = Depends(get_pharmacy_service),
    _actor: User = Depends(require_permission(PERMISSION_PHARMACY_MANAGE)),
) -> dict:
    """Admin management listing — every medicine, active and inactive
    alike (see repository.py's `list_all` docstring)."""
    medicines, total = await pharmacy_service.list_medicines(
        search=search,
        sort_by=sort_by.value,
        sort_desc=sort_order == SortOrder.DESC,
        page=page,
        page_size=page_size,
    )
    body = [MedicineOut.from_medicine(medicine).model_dump(mode="json") for medicine in medicines]
    meta = PaginationMeta(page=page, page_size=page_size, total=total).model_dump(mode="json")
    return success_envelope(body, meta)


@router.get("/medicines/search")
async def search_medicines(
    search: str = Query(min_length=1, max_length=150),
    pharmacy_service: PharmacyService = Depends(get_pharmacy_service),
    _actor: User = Depends(require_permission(PERMISSION_PHARMACY_READ)),
) -> dict:
    """Active-only, case-insensitive partial name match — backs the
    receptionist's medicine autocomplete. Unpaginated by design, same
    rationale as app/modules/auth/permission_router.py's
    `get_roles_for_permission`: a utility lookup endpoint, not a primary
    listing."""
    medicines = await pharmacy_service.search_medicines(search=search)
    body = [MedicineOut.from_medicine(medicine).model_dump(mode="json") for medicine in medicines]
    return success_envelope(body)


@router.patch("/medicines/{medicine_id}")
async def update_medicine(
    medicine_id: UUID,
    payload: UpdateMedicineRequest,
    pharmacy_service: PharmacyService = Depends(get_pharmacy_service),
    actor: User = Depends(require_permission(PERMISSION_PHARMACY_MANAGE)),
) -> dict:
    medicine = await pharmacy_service.update_medicine(
        actor=actor,
        medicine_id=medicine_id,
        updates=payload.model_dump(exclude_unset=True),
    )
    return success_envelope(MedicineOut.from_medicine(medicine).model_dump(mode="json"))


# ----------------------------------------------------------------------
# Medicine bills — Receptionist + Admin
# ----------------------------------------------------------------------


@router.post("/bills", status_code=201)
async def create_bill(
    payload: CreateMedicineBillRequest,
    pharmacy_service: PharmacyService = Depends(get_pharmacy_service),
    actor: User = Depends(require_permission(PERMISSION_PHARMACY_BILL)),
) -> dict:
    bill = await pharmacy_service.create_bill(
        actor=actor,
        visit_id=payload.visit_id,
        items=[(item.medicine_id, item.quantity) for item in payload.items],
    )
    items = await pharmacy_service.get_bill_items(bill.id)
    return success_envelope(MedicineBillOut.from_bill(bill, items).model_dump(mode="json"))


@router.get("/bills")
async def list_bills_for_day(
    date: date_type = Query(description="Calendar day (UTC) to list medicine bills for."),
    pharmacy_service: PharmacyService = Depends(get_pharmacy_service),
    _actor: User = Depends(require_permission(PERMISSION_PHARMACY_READ)),
) -> dict:
    summaries = await pharmacy_service.list_bill_summaries_for_day(date)
    body = [
        MedicineBillSummaryOut.from_bill(bill, item_count).model_dump(mode="json")
        for bill, item_count in summaries
    ]
    return success_envelope(body)


@router.get("/bills/{bill_id}")
async def get_bill(
    bill_id: UUID,
    pharmacy_service: PharmacyService = Depends(get_pharmacy_service),
    _actor: User = Depends(require_permission(PERMISSION_PHARMACY_READ)),
) -> dict:
    bill = await pharmacy_service.get_bill(bill_id)
    items = await pharmacy_service.get_bill_items(bill.id)
    return success_envelope(MedicineBillOut.from_bill(bill, items).model_dump(mode="json"))


@router.get("/bills/{bill_id}/print", response_class=HTMLResponse)
async def print_bill(
    bill_id: UUID,
    pharmacy_service: PharmacyService = Depends(get_pharmacy_service),
    patient_service: PatientService = Depends(get_patient_service),
    visit_service: VisitService = Depends(get_visit_service),
    settings: Settings = Depends(get_settings),
    _actor: User = Depends(require_permission(PERMISSION_PHARMACY_READ)),
) -> HTMLResponse:
    """Same Central Print Service pattern as Billing's invoice print
    endpoint and Reception's registration-slip print endpoint — Pharmacy
    decides *whether* this bill may be printed (the same `pharmacy:read`
    gate as viewing it) and supplies the data; the shared printing
    service only ever renders it (Phase 6 §14)."""
    bill = await pharmacy_service.get_bill(bill_id)
    items = await pharmacy_service.get_bill_items(bill.id)

    visit = None
    patient = None
    if bill.visit_id is not None:
        visit = await visit_service.get_visit(bill.visit_id)
        patient = await patient_service.get_patient(visit.patient_id)

    html_document = render_medicine_bill_receipt(
        hospital_name=settings.app_name,
        display_timezone=settings.display_timezone,
        bill_id=str(bill.id),
        bill_created_at=bill.created_at,
        visit_queue_token=visit.queue_token if visit else None,
        patient_full_name=patient.full_name if patient else None,
        patient_mr_number=patient.mr_number if patient else None,
        line_items=[
            (
                item.medicine_name_snapshot,
                item.category_snapshot.value,
                item.quantity,
                item.unit_price_snapshot,
                item.line_total,
            )
            for item in items
        ],
        total_amount=bill.total_amount,
    )
    return HTMLResponse(content=html_document)

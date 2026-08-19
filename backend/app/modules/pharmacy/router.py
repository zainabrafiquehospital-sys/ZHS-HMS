"""HTTP endpoints for the Pharmacy / Medicine Billing module. Medicine
price-list management requires `pharmacy:manage` (Admin-only); searching
the price list and viewing/printing bills requires `pharmacy:read`;
creating a bill requires `pharmacy:bill` — see constants.py's module
docstring for the segregation-of-duties rationale, matching Billing's
identical permission split. `GET /bills/mine` (2026-08-19 addition) is
a receptionist's own itemized medicine-bill record — see
list_my_bills's own docstring."""

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
    MedicineBillCreatorStatOut,
    MedicineBillOut,
    MedicineBillSummaryOut,
    MedicineOut,
    MedicineSortField,
    RecordMedicineBillPaymentRequest,
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
        initial_payment_amount=payload.initial_payment_amount,
        initial_payment_method=payload.initial_payment_method,
        manual_patient_name=payload.manual_patient_name,
        manual_patient_age=payload.manual_patient_age,
        manual_patient_phone=payload.manual_patient_phone,
        discount_amount=payload.discount_amount,
        discount_reason=payload.discount_reason,
    )
    items = await pharmacy_service.get_bill_items(bill.id)
    payments = await pharmacy_service.get_bill_payments(bill.id)
    return success_envelope(
        MedicineBillOut.from_bill(bill, items, payments).model_dump(mode="json")
    )


@router.post("/bills/{bill_id}/pay")
async def record_payment(
    bill_id: UUID,
    payload: RecordMedicineBillPaymentRequest,
    pharmacy_service: PharmacyService = Depends(get_pharmacy_service),
    actor: User = Depends(require_permission(PERMISSION_PHARMACY_BILL)),
) -> dict:
    """Gated on `pharmacy:bill`, the same permission that creates a bill
    — unlike Billing's `submit_charge`/`manage` split (a real segregation
    of duties between a doctor requesting a charge and Reception
    approving/collecting it), Pharmacy has no equivalent second actor:
    the same receptionist who builds and finalizes a medicine bill is
    always the one collecting payment for it at the same counter, so a
    separate "manage" gate here would be a distinction without a
    difference."""
    bill = await pharmacy_service.record_payment(
        actor=actor, bill_id=bill_id, amount=payload.amount, payment_method=payload.payment_method
    )
    items = await pharmacy_service.get_bill_items(bill.id)
    payments = await pharmacy_service.get_bill_payments(bill.id)
    return success_envelope(
        MedicineBillOut.from_bill(bill, items, payments).model_dump(mode="json")
    )


@router.get("/bills")
async def list_bills_for_day(
    date: date_type = Query(description="Calendar day (UTC) to list medicine bills for."),
    pharmacy_service: PharmacyService = Depends(get_pharmacy_service),
    _actor: User = Depends(require_permission(PERMISSION_PHARMACY_READ)),
) -> dict:
    summaries = await pharmacy_service.list_bill_summaries_for_day(date)
    body = [
        MedicineBillSummaryOut.from_bill(bill, item_count, payment_methods).model_dump(mode="json")
        for bill, item_count, payment_methods in summaries
    ]
    return success_envelope(body)


@router.get("/bills/stats/by-creator")
async def get_bill_stats_by_creator(
    pharmacy_service: PharmacyService = Depends(get_pharmacy_service),
    _actor: User = Depends(require_permission(PERMISSION_PHARMACY_READ)),
) -> dict:
    """Read-only aggregate added for the Admin "Employee Accounts &
    Stats" page — one row per user who has created at least one
    medicine bill, each with their all-time bill count and total
    revenue billed. Not paginated: bounded by the number of distinct
    users who have ever created a bill (see MedicineBillRepository.
    count_and_revenue_by_creator)."""
    stats = await pharmacy_service.count_and_revenue_by_creator()
    body = [
        MedicineBillCreatorStatOut(user_id=user_id, count=count, revenue=revenue).model_dump(
            mode="json"
        )
        for user_id, (count, revenue) in stats.items()
    ]
    return success_envelope(body)


@router.get("/bills/mine")
async def list_my_bills(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    pharmacy_service: PharmacyService = Depends(get_pharmacy_service),
    actor: User = Depends(require_permission(PERMISSION_PHARMACY_READ)),
) -> dict:
    """The calling receptionist's own "My Medicine Bills" record —
    every medicine bill she has personally created, newest first, real
    server-side pagination, no date restriction (2026-08-19 addition,
    the medicine-bill sibling of `GET /visits?created_by=`'s "My
    Registrations"). Declared before `GET /bills/{bill_id}` below —
    same routing-order precaution `GET /bills/stats/by-creator` above
    already needs, otherwise FastAPI would try to parse the literal
    path segment `mine` as a `bill_id` UUID and 422.

    Always `actor.id`, never a request-suppliable user id — the same
    hard server-side scoping `GET /reception/revenue` already
    established for "My Revenue" (see PharmacyService.
    list_bills_for_creator's own docstring); there is structurally no
    way to ask for someone else's bills through this endpoint."""
    summaries, total = await pharmacy_service.list_bills_for_creator(
        actor.id, page=page, page_size=page_size
    )
    body = [
        MedicineBillSummaryOut.from_bill(bill, item_count, payment_methods).model_dump(mode="json")
        for bill, item_count, payment_methods in summaries
    ]
    meta = PaginationMeta(page=page, page_size=page_size, total=total).model_dump(mode="json")
    return success_envelope(body, meta)


@router.get("/bills/{bill_id}")
async def get_bill(
    bill_id: UUID,
    pharmacy_service: PharmacyService = Depends(get_pharmacy_service),
    _actor: User = Depends(require_permission(PERMISSION_PHARMACY_READ)),
) -> dict:
    bill = await pharmacy_service.get_bill(bill_id)
    items = await pharmacy_service.get_bill_items(bill.id)
    payments = await pharmacy_service.get_bill_payments(bill.id)
    return success_envelope(
        MedicineBillOut.from_bill(bill, items, payments).model_dump(mode="json")
    )


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
    service only ever renders it (Phase 6 §14).

    Sources the slip's patient/visit reference block from whichever of
    the three mutually-exclusive states this bill is in (see models.py's
    `MedicineBill` docstring): a linked Visit's real Patient record, the
    manually-typed name/age/contact, or neither (an anonymous walk-in,
    the pre-existing behavior, unchanged). `render_medicine_bill_receipt`
    itself needs no changes for this — it already renders the reference
    section whenever `patient_full_name` is not `None`, regardless of
    which of these three sources supplied it."""
    bill = await pharmacy_service.get_bill(bill_id)
    items = await pharmacy_service.get_bill_items(bill.id)
    payments = await pharmacy_service.get_bill_payments(bill.id)

    visit = None
    patient = None
    if bill.visit_id is not None:
        visit = await visit_service.get_visit(bill.visit_id)
        patient = await patient_service.get_patient(visit.patient_id)

    if patient is not None:
        patient_full_name = patient.full_name
        patient_mr_number = patient.mr_number
        patient_age_years = patient.age_years
        patient_phone_number = patient.phone_number
    elif bill.manual_patient_name is not None:
        patient_full_name = bill.manual_patient_name
        patient_mr_number = None
        patient_age_years = bill.manual_patient_age
        patient_phone_number = bill.manual_patient_phone
    else:
        patient_full_name = None
        patient_mr_number = None
        patient_age_years = None
        patient_phone_number = None

    html_document = render_medicine_bill_receipt(
        hospital_name=settings.app_name,
        display_timezone=settings.display_timezone,
        bill_id=str(bill.id),
        bill_created_at=bill.created_at,
        visit_queue_token=visit.queue_token if visit else None,
        patient_full_name=patient_full_name,
        patient_mr_number=patient_mr_number,
        patient_age_years=patient_age_years,
        patient_phone_number=patient_phone_number,
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
        amount_paid=bill.amount_paid,
        discount_amount=bill.discount_amount,
        discount_reason=bill.discount_reason,
        payment_methods=list(dict.fromkeys(payment.payment_method.value for payment in payments)),
    )
    return HTMLResponse(content=html_document)

"""HTTP endpoints for the Laboratory Billing module. Lab test price-list
management requires `lab:manage` (Admin-only); searching the price list
and viewing bills requires `lab:read`; creating a bill requires
`lab:bill` — see constants.py's module docstring for the segregation-
of-duties rationale, matching Pharmacy's identical permission split.
`GET /bills/mine` is a receptionist's own itemized lab-bill record —
see list_my_bills's own docstring. `PATCH`/`DELETE /bills/{bill_id}`
are admin-only data-correction actions — `lab:update_bill`/
`lab:delete_bill`, never `lab:bill` — mirroring app/modules/pharmacy/
router.py's identical update_bill/delete_bill pair.

`GET /bills/{bill_id}/print` (pulled forward into the same build step
as the Receptionist frontend, since Finalize & Print is one combined
action there) is the Central Print Service integration — same pattern
as Pharmacy's own `print_bill`: this router decides *whether* a bill
may be printed (the same `lab:read` gate as viewing it) and supplies
the data; the shared printing service only ever renders it. Sources
the slip's patient reference block directly from `LabBill.patient_id`
(never a Visit — confirmed design) via `PatientService.get_patient`."""

from datetime import date as date_type
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse

from app.core.config import Settings, get_settings
from app.modules.auth.dependencies import require_permission
from app.modules.auth.models import User
from app.modules.lab.constants import (
    PERMISSION_LAB_BILL,
    PERMISSION_LAB_DELETE_BILL,
    PERMISSION_LAB_MANAGE,
    PERMISSION_LAB_READ,
    PERMISSION_LAB_UPDATE_BILL,
)
from app.modules.lab.dependencies import get_lab_service
from app.modules.lab.schemas import (
    AdminUpdateLabBillRequest,
    CreateLabBillRequest,
    CreateLabTestRequest,
    LabBillCreatorStatOut,
    LabBillOut,
    LabBillSummaryOut,
    LabTestOut,
    LabTestSortField,
    RecordLabBillPaymentRequest,
    UpdateLabTestRequest,
)
from app.modules.lab.service import LabService
from app.modules.patients.dependencies import get_patient_service
from app.modules.patients.service import PatientService
from app.shared.envelope import success_envelope
from app.shared.pagination import PaginationMeta, SortOrder
from app.shared.printing.service import render_lab_bill_receipt

router = APIRouter(prefix="/lab", tags=["lab"])


# ----------------------------------------------------------------------
# Lab test price list — Admin-only management
# ----------------------------------------------------------------------


@router.post("/tests", status_code=201)
async def create_test(
    payload: CreateLabTestRequest,
    lab_service: LabService = Depends(get_lab_service),
    actor: User = Depends(require_permission(PERMISSION_LAB_MANAGE)),
) -> dict:
    test = await lab_service.create_test(
        actor=actor, name=payload.name, category=payload.category, price=payload.price
    )
    return success_envelope(LabTestOut.from_test(test).model_dump(mode="json"))


@router.get("/tests")
async def list_tests(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    search: str | None = Query(default=None, max_length=150),
    sort_by: LabTestSortField = Query(default=LabTestSortField.NAME),
    sort_order: SortOrder = Query(default=SortOrder.ASC),
    lab_service: LabService = Depends(get_lab_service),
    _actor: User = Depends(require_permission(PERMISSION_LAB_MANAGE)),
) -> dict:
    """Admin management listing — every test, active and inactive
    alike (see repository.py's `list_all` docstring)."""
    tests, total = await lab_service.list_tests(
        search=search,
        sort_by=sort_by.value,
        sort_desc=sort_order == SortOrder.DESC,
        page=page,
        page_size=page_size,
    )
    body = [LabTestOut.from_test(test).model_dump(mode="json") for test in tests]
    meta = PaginationMeta(page=page, page_size=page_size, total=total).model_dump(mode="json")
    return success_envelope(body, meta)


@router.get("/tests/search")
async def search_tests(
    search: str = Query(min_length=1, max_length=150),
    lab_service: LabService = Depends(get_lab_service),
    _actor: User = Depends(require_permission(PERMISSION_LAB_READ)),
) -> dict:
    """Active-only, case-insensitive partial name match — backs the
    receptionist's lab test autocomplete. Unpaginated by design, same
    rationale as app/modules/pharmacy/router.py's `search_medicines`."""
    tests = await lab_service.search_tests(search=search)
    body = [LabTestOut.from_test(test).model_dump(mode="json") for test in tests]
    return success_envelope(body)


@router.patch("/tests/{lab_test_id}")
async def update_test(
    lab_test_id: UUID,
    payload: UpdateLabTestRequest,
    lab_service: LabService = Depends(get_lab_service),
    actor: User = Depends(require_permission(PERMISSION_LAB_MANAGE)),
) -> dict:
    test = await lab_service.update_test(
        actor=actor, lab_test_id=lab_test_id, updates=payload.model_dump(exclude_unset=True)
    )
    return success_envelope(LabTestOut.from_test(test).model_dump(mode="json"))


# ----------------------------------------------------------------------
# Lab bills — Receptionist + Admin
# ----------------------------------------------------------------------


@router.post("/bills", status_code=201)
async def create_bill(
    payload: CreateLabBillRequest,
    lab_service: LabService = Depends(get_lab_service),
    actor: User = Depends(require_permission(PERMISSION_LAB_BILL)),
) -> dict:
    bill = await lab_service.create_bill(
        actor=actor,
        patient_id=payload.patient_id,
        items=[(item.lab_test_id, item.name, item.price) for item in payload.items],
        initial_payment_amount=payload.initial_payment_amount,
        initial_payment_method=payload.initial_payment_method,
        manual_patient_name=payload.manual_patient_name,
        manual_patient_age=payload.manual_patient_age,
        manual_patient_phone=payload.manual_patient_phone,
        discount_amount=payload.discount_amount,
        discount_reason=payload.discount_reason,
    )
    items = await lab_service.get_bill_items(bill.id)
    payments = await lab_service.get_bill_payments(bill.id)
    return success_envelope(LabBillOut.from_bill(bill, items, payments).model_dump(mode="json"))


@router.post("/bills/{bill_id}/pay")
async def record_payment(
    bill_id: UUID,
    payload: RecordLabBillPaymentRequest,
    lab_service: LabService = Depends(get_lab_service),
    actor: User = Depends(require_permission(PERMISSION_LAB_BILL)),
) -> dict:
    """Gated on `lab:bill`, the same permission that creates a bill —
    mirrors app/modules/pharmacy/router.py's identical `record_payment`
    docstring: the same receptionist who builds and finalizes a lab
    bill is always the one collecting payment for it at the same
    counter."""
    bill = await lab_service.record_payment(
        actor=actor, bill_id=bill_id, amount=payload.amount, payment_method=payload.payment_method
    )
    items = await lab_service.get_bill_items(bill.id)
    payments = await lab_service.get_bill_payments(bill.id)
    return success_envelope(LabBillOut.from_bill(bill, items, payments).model_dump(mode="json"))


@router.get("/bills")
async def list_bills_for_day(
    date: date_type = Query(description="Calendar day (UTC) to list lab bills for."),
    lab_service: LabService = Depends(get_lab_service),
    _actor: User = Depends(require_permission(PERMISSION_LAB_READ)),
) -> dict:
    summaries = await lab_service.list_bill_summaries_for_day(date)
    body = [
        LabBillSummaryOut.from_bill(bill, item_count, payment_methods).model_dump(mode="json")
        for bill, item_count, payment_methods in summaries
    ]
    return success_envelope(body)


@router.get("/bills/stats/by-creator")
async def get_bill_stats_by_creator(
    lab_service: LabService = Depends(get_lab_service),
    _actor: User = Depends(require_permission(PERMISSION_LAB_READ)),
) -> dict:
    """Read-only aggregate for the Admin "Employee Accounts & Stats"
    page — one row per user who has created at least one lab bill, each
    with their all-time bill count and total revenue billed. Not
    paginated, same rationale as app/modules/pharmacy/router.py's
    identical `get_bill_stats_by_creator`."""
    stats = await lab_service.count_and_revenue_by_creator()
    body = [
        LabBillCreatorStatOut(user_id=user_id, count=count, revenue=revenue).model_dump(mode="json")
        for user_id, (count, revenue) in stats.items()
    ]
    return success_envelope(body)


@router.get("/bills/mine")
async def list_my_bills(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    lab_service: LabService = Depends(get_lab_service),
    actor: User = Depends(require_permission(PERMISSION_LAB_READ)),
) -> dict:
    """The calling receptionist's own "My Lab Bills" record — every lab
    bill she has personally created, newest first, real server-side
    pagination, no date restriction. Declared before `GET /bills/
    {bill_id}` below — same routing-order precaution `GET /bills/
    stats/by-creator` above already needs, otherwise FastAPI would try
    to parse the literal path segment `mine` as a `bill_id` UUID and
    422.

    Always `actor.id`, never a request-suppliable user id — the same
    hard server-side scoping app/modules/pharmacy/router.py's identical
    `list_my_bills` already established."""
    summaries, total = await lab_service.list_bills_for_creator(
        actor.id, page=page, page_size=page_size
    )
    body = [
        LabBillSummaryOut.from_bill(bill, item_count, payment_methods).model_dump(mode="json")
        for bill, item_count, payment_methods in summaries
    ]
    meta = PaginationMeta(page=page, page_size=page_size, total=total).model_dump(mode="json")
    return success_envelope(body, meta)


@router.get("/bills/{bill_id}")
async def get_bill(
    bill_id: UUID,
    lab_service: LabService = Depends(get_lab_service),
    _actor: User = Depends(require_permission(PERMISSION_LAB_READ)),
) -> dict:
    bill = await lab_service.get_bill(bill_id)
    items = await lab_service.get_bill_items(bill.id)
    payments = await lab_service.get_bill_payments(bill.id)
    return success_envelope(LabBillOut.from_bill(bill, items, payments).model_dump(mode="json"))


@router.get("/bills/{bill_id}/print", response_class=HTMLResponse)
async def print_bill(
    bill_id: UUID,
    lab_service: LabService = Depends(get_lab_service),
    patient_service: PatientService = Depends(get_patient_service),
    settings: Settings = Depends(get_settings),
    _actor: User = Depends(require_permission(PERMISSION_LAB_READ)),
) -> HTMLResponse:
    """Same Central Print Service pattern as Pharmacy's own `print_bill`
    — see this router's own module docstring. Sources the slip's
    reference block from whichever of the three mutually-exclusive
    states this bill is in (see models.py's `LabBill` docstring): a
    directly-linked Patient record, the manually-typed name/age/
    contact, or neither (an anonymous walk-in)."""
    bill = await lab_service.get_bill(bill_id)
    items = await lab_service.get_bill_items(bill.id)
    payments = await lab_service.get_bill_payments(bill.id)

    patient = None
    if bill.patient_id is not None:
        patient = await patient_service.get_patient(bill.patient_id)

    if patient is not None:
        patient_full_name = patient.full_name
        patient_age_years = patient.age_years
        patient_phone_number = patient.phone_number
    elif bill.manual_patient_name is not None:
        patient_full_name = bill.manual_patient_name
        patient_age_years = bill.manual_patient_age
        patient_phone_number = bill.manual_patient_phone
    else:
        patient_full_name = None
        patient_age_years = None
        patient_phone_number = None

    html_document = render_lab_bill_receipt(
        hospital_name=settings.app_name,
        display_timezone=settings.display_timezone,
        bill_id=str(bill.id),
        bill_created_at=bill.created_at,
        bill_queue_token=bill.queue_token,
        patient_full_name=patient_full_name,
        patient_age_years=patient_age_years,
        patient_phone_number=patient_phone_number,
        line_items=[
            (
                item.lab_test_name_snapshot,
                item.category_snapshot.value if item.category_snapshot else None,
                item.unit_price_snapshot,
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


# ------------------------------------------------------------------
# Admin data correction — gated on lab:update_bill / lab:delete_bill,
# never on lab:bill, and never granted to Receptionist — the lab-bill
# sibling of app/modules/pharmacy/router.py's identical update_bill/
# delete_bill pair. Ownership never matters here: an admin may act on
# any receptionist's bill, not only their own.
# ------------------------------------------------------------------


@router.patch("/bills/{bill_id}")
async def update_bill(
    bill_id: UUID,
    payload: AdminUpdateLabBillRequest,
    lab_service: LabService = Depends(get_lab_service),
    actor: User = Depends(require_permission(PERMISSION_LAB_UPDATE_BILL)),
) -> dict:
    """Corrects a mistakenly-entered bill's manual patient details
    and/or discount (see LabService.admin_update_bill's own docstring
    for the full safety story)."""
    bill = await lab_service.admin_update_bill(
        actor=actor, bill_id=bill_id, updates=payload.model_dump(exclude_unset=True)
    )
    items = await lab_service.get_bill_items(bill.id)
    payments = await lab_service.get_bill_payments(bill.id)
    return success_envelope(LabBillOut.from_bill(bill, items, payments).model_dump(mode="json"))


@router.delete("/bills/{bill_id}")
async def delete_bill(
    bill_id: UUID,
    lab_service: LabService = Depends(get_lab_service),
    actor: User = Depends(require_permission(PERMISSION_LAB_DELETE_BILL)),
) -> dict:
    """Soft-deletes a lab bill created by mistake (see LabService.
    admin_delete_bill's own docstring for the full safety story,
    including the paid/partially-paid block)."""
    await lab_service.admin_delete_bill(actor=actor, bill_id=bill_id)
    return success_envelope(None)

"""HTTP endpoints for the Ward/Emergency Inventory Management module.
Catalog management, Main Stock receipts, transfers to Emergency Stock,
and restock-request fulfillment/rejection all require `inventory:manage`
(Inventory Manager-only); recording a usage entry requires
`inventory:record_usage` and raising a restock request requires
`inventory:request_restock` (both Vitals-only); every read endpoint
requires only `inventory:read` (Inventory Manager, Vitals, and Admin —
see constants.py's module docstring). Doctor holds none of these and
reaches nothing here.

Print endpoints (2026-08-26 addition) — `print_history_log`/
`print_my_daily_usage_slip` below — are report-style A4 documents via
the Central Print Service's newer `render_inventory_history_log`/
`render_inventory_daily_usage_slip` (see app/shared/printing/service.py's
own module-level docstring for the full "browser handles both Print and
Save-as-PDF, no server-side PDF library" rationale), never the narrow
42mm thermal-receipt layout every other print in this app uses — those
three documents are genuinely single transactions; these two are
multi-row reports. This router is where the id-to-display-string
resolution happens (item names, patient names, "Recorded By" user
names) — the render functions themselves only ever lay out already-
resolved strings, matching this module's own "owning module decides
what to render" boundary."""

from datetime import UTC, datetime
from datetime import date as date_type
from decimal import Decimal
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse

from app.core.config import Settings, get_settings
from app.modules.auth.dependencies import get_user_service, require_permission
from app.modules.auth.models import User
from app.modules.auth.user_service import UserService
from app.modules.inventory.constants import (
    PERMISSION_INVENTORY_MANAGE,
    PERMISSION_INVENTORY_READ,
    PERMISSION_INVENTORY_RECORD_USAGE,
    PERMISSION_INVENTORY_REQUEST_RESTOCK,
)
from app.modules.inventory.dependencies import get_inventory_service
from app.modules.inventory.models import InventoryRestockRequestStatus
from app.modules.inventory.schemas import (
    CreateInventoryItemRequest,
    FulfillRestockRequestRequest,
    InventoryItemOut,
    InventoryItemSortField,
    InventoryMainStockReceiptOut,
    InventoryPatientContextOut,
    InventoryRestockRequestOut,
    InventoryTransferOut,
    InventoryUsageEntryOut,
    RaiseRestockRequestRequest,
    ReceiveStockRequest,
    RecordUsageRequest,
    RejectRestockRequestRequest,
    TransferStockRequest,
    UpdateInventoryItemRequest,
)
from app.modules.inventory.service import InventoryService
from app.modules.patients.dependencies import get_patient_service
from app.modules.patients.service import PatientService
from app.shared.envelope import success_envelope
from app.shared.pagination import PaginationMeta, SortOrder
from app.shared.printing.service import (
    format_local_timestamp,
    render_inventory_daily_usage_slip,
    render_inventory_history_log,
)

router = APIRouter(prefix="/inventory", tags=["inventory"])

_ALL_ITEMS_PAGE_SIZE = 1000
_ALL_ROWS_PAGE_SIZE = 1000


async def _load_items_by_id(inventory_service: InventoryService) -> dict[UUID, InventoryItemOut]:
    """Every item, keyed by id — used by both print endpoints below to
    resolve an item name per row without a per-row lookup. `_ALL_ITEMS_
    PAGE_SIZE` is a generous bound consistent with `listItems`'s own
    frontend page size (a real hospital's catalog is at most a few
    hundred rows); this is a print action, not a hot path."""
    items, _total = await inventory_service.list_items(
        search=None,
        category=None,
        low_stock_only=False,
        sort_by="name",
        sort_desc=False,
        page=1,
        page_size=_ALL_ITEMS_PAGE_SIZE,
    )
    return {item.id: item for item in items}


# ----------------------------------------------------------------------
# Catalog — Inventory Manager-only management, shared read
# ----------------------------------------------------------------------


@router.post("/items", status_code=201)
async def create_item(
    payload: CreateInventoryItemRequest,
    inventory_service: InventoryService = Depends(get_inventory_service),
    actor: User = Depends(require_permission(PERMISSION_INVENTORY_MANAGE)),
) -> dict:
    item = await inventory_service.create_item(
        actor=actor,
        name=payload.name,
        category=payload.category,
        unit=payload.unit,
        low_stock_threshold=payload.low_stock_threshold,
    )
    return success_envelope(InventoryItemOut.from_item(item).model_dump(mode="json"))


@router.get("/items")
async def list_items(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    search: str | None = Query(default=None, max_length=150),
    category: str | None = Query(default=None),
    low_stock_only: bool = Query(default=False),
    sort_by: InventoryItemSortField = Query(default=InventoryItemSortField.NAME),
    sort_order: SortOrder = Query(default=SortOrder.ASC),
    inventory_service: InventoryService = Depends(get_inventory_service),
    _actor: User = Depends(require_permission(PERMISSION_INVENTORY_READ)),
) -> dict:
    items, total = await inventory_service.list_items(
        search=search,
        category=category,
        low_stock_only=low_stock_only,
        sort_by=sort_by.value,
        sort_desc=sort_order == SortOrder.DESC,
        page=page,
        page_size=page_size,
    )
    body = [InventoryItemOut.from_item(item).model_dump(mode="json") for item in items]
    meta = PaginationMeta(page=page, page_size=page_size, total=total).model_dump(mode="json")
    return success_envelope(body, meta)


@router.get("/items/search")
async def search_items(
    search: str = Query(min_length=1, max_length=150),
    inventory_service: InventoryService = Depends(get_inventory_service),
    _actor: User = Depends(require_permission(PERMISSION_INVENTORY_READ)),
) -> dict:
    """Active-only autocomplete backing the Vitals usage-entry item
    picker — declared before `GET /items/{item_id}` below, the same
    routing-order precaution `GET /pharmacy/medicines/search` already
    needs relative to `GET /pharmacy/medicines/{medicine_id}`."""
    items = await inventory_service.search_items(search=search)
    body = [InventoryItemOut.from_item(item).model_dump(mode="json") for item in items]
    return success_envelope(body)


@router.get("/items/{item_id}")
async def get_item(
    item_id: UUID,
    inventory_service: InventoryService = Depends(get_inventory_service),
    _actor: User = Depends(require_permission(PERMISSION_INVENTORY_READ)),
) -> dict:
    item = await inventory_service.get_item(item_id)
    return success_envelope(InventoryItemOut.from_item(item).model_dump(mode="json"))


@router.patch("/items/{item_id}")
async def update_item(
    item_id: UUID,
    payload: UpdateInventoryItemRequest,
    inventory_service: InventoryService = Depends(get_inventory_service),
    actor: User = Depends(require_permission(PERMISSION_INVENTORY_MANAGE)),
) -> dict:
    item = await inventory_service.update_item(
        actor=actor, item_id=item_id, updates=payload.model_dump(exclude_unset=True)
    )
    return success_envelope(InventoryItemOut.from_item(item).model_dump(mode="json"))


# ----------------------------------------------------------------------
# Main Stock receipts — Inventory Manager-only
# ----------------------------------------------------------------------


@router.post("/items/{item_id}/receive")
async def receive_stock(
    item_id: UUID,
    payload: ReceiveStockRequest,
    inventory_service: InventoryService = Depends(get_inventory_service),
    actor: User = Depends(require_permission(PERMISSION_INVENTORY_MANAGE)),
) -> dict:
    item = await inventory_service.receive_stock(
        actor=actor,
        item_id=item_id,
        quantity=payload.quantity,
        received_on=payload.received_on,
    )
    return success_envelope(InventoryItemOut.from_item(item).model_dump(mode="json"))


@router.get("/receipts")
async def list_receipts(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    item_id: UUID | None = Query(default=None),
    start_date: date_type | None = Query(default=None),
    end_date: date_type | None = Query(default=None),
    inventory_service: InventoryService = Depends(get_inventory_service),
    _actor: User = Depends(require_permission(PERMISSION_INVENTORY_READ)),
) -> dict:
    receipts, total = await inventory_service.list_receipts(
        item_id=item_id, start_date=start_date, end_date=end_date, page=page, page_size=page_size
    )
    body = [
        InventoryMainStockReceiptOut.from_receipt(receipt).model_dump(mode="json")
        for receipt in receipts
    ]
    meta = PaginationMeta(page=page, page_size=page_size, total=total).model_dump(mode="json")
    return success_envelope(body, meta)


# ----------------------------------------------------------------------
# Transfers — Inventory Manager-only
# ----------------------------------------------------------------------


@router.post("/items/{item_id}/transfer")
async def transfer_stock(
    item_id: UUID,
    payload: TransferStockRequest,
    inventory_service: InventoryService = Depends(get_inventory_service),
    actor: User = Depends(require_permission(PERMISSION_INVENTORY_MANAGE)),
) -> dict:
    item = await inventory_service.transfer_to_emergency(
        actor=actor,
        item_id=item_id,
        quantity=payload.quantity,
        transferred_on=payload.transferred_on,
    )
    return success_envelope(InventoryItemOut.from_item(item).model_dump(mode="json"))


@router.get("/transfers")
async def list_transfers(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    item_id: UUID | None = Query(default=None),
    start_date: date_type | None = Query(default=None),
    end_date: date_type | None = Query(default=None),
    inventory_service: InventoryService = Depends(get_inventory_service),
    _actor: User = Depends(require_permission(PERMISSION_INVENTORY_READ)),
) -> dict:
    transfers, total = await inventory_service.list_transfers(
        item_id=item_id, start_date=start_date, end_date=end_date, page=page, page_size=page_size
    )
    body = [
        InventoryTransferOut.from_transfer(transfer).model_dump(mode="json")
        for transfer in transfers
    ]
    meta = PaginationMeta(page=page, page_size=page_size, total=total).model_dump(mode="json")
    return success_envelope(body, meta)


# ----------------------------------------------------------------------
# Usage entries — Vitals records, everyone with inventory:read views
# ----------------------------------------------------------------------


@router.post("/usage", status_code=201)
async def record_usage(
    payload: RecordUsageRequest,
    inventory_service: InventoryService = Depends(get_inventory_service),
    actor: User = Depends(require_permission(PERMISSION_INVENTORY_RECORD_USAGE)),
) -> dict:
    entry = await inventory_service.record_usage(
        actor=actor,
        item_id=payload.item_id,
        quantity=payload.quantity,
        used_on=payload.used_on,
        patient_id=payload.patient_id,
        manual_patient_name=payload.manual_patient_name,
        manual_patient_age=payload.manual_patient_age,
        manual_patient_phone=payload.manual_patient_phone,
        reason_note=payload.reason_note,
    )
    return success_envelope(InventoryUsageEntryOut.from_entry(entry).model_dump(mode="json"))


@router.get("/usage")
async def list_usage_entries(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    item_id: UUID | None = Query(default=None),
    created_by: UUID | None = Query(default=None),
    start_date: date_type | None = Query(default=None),
    end_date: date_type | None = Query(default=None),
    inventory_service: InventoryService = Depends(get_inventory_service),
    _actor: User = Depends(require_permission(PERMISSION_INVENTORY_READ)),
) -> dict:
    entries, total = await inventory_service.list_usage_entries(
        item_id=item_id,
        created_by=created_by,
        start_date=start_date,
        end_date=end_date,
        page=page,
        page_size=page_size,
    )
    body = [InventoryUsageEntryOut.from_entry(entry).model_dump(mode="json") for entry in entries]
    meta = PaginationMeta(page=page, page_size=page_size, total=total).model_dump(mode="json")
    return success_envelope(body, meta)


@router.get("/usage/mine")
async def list_my_usage_for_day(
    date: date_type = Query(
        description="Calendar day (UTC) to list this user's own usage entries for."
    ),
    inventory_service: InventoryService = Depends(get_inventory_service),
    actor: User = Depends(require_permission(PERMISSION_INVENTORY_RECORD_USAGE)),
) -> dict:
    """A Vitals staff member's own usage entries for one day — the
    source for their printed daily usage slip (a future build step).
    Declared before nothing conflicting (no `/usage/{id}` path exists in
    this module), but named the same "mine" convention `GET
    /pharmacy/bills/mine` established, and — like that endpoint — always
    scoped to `actor.id`, never a request-suppliable user id."""
    entries = await inventory_service.list_usage_for_creator_and_day(
        created_by=actor.id, day=datetime(date.year, date.month, date.day)
    )
    body = [InventoryUsageEntryOut.from_entry(entry).model_dump(mode="json") for entry in entries]
    return success_envelope(body)


@router.get("/patients/{patient_id}/context")
async def get_patient_context(
    patient_id: UUID,
    inventory_service: InventoryService = Depends(get_inventory_service),
    _actor: User = Depends(require_permission(PERMISSION_INVENTORY_READ)),
) -> dict:
    """Backs the usage-entry screen's read-only "MR number + most recent
    registered procedure" preview once a patient is picked — see
    InventoryService.get_patient_context's own docstring."""
    patient, latest_visit = await inventory_service.get_patient_context(patient_id)
    return success_envelope(
        InventoryPatientContextOut.from_context(patient, latest_visit).model_dump(mode="json")
    )


# ----------------------------------------------------------------------
# Restock requests
# ----------------------------------------------------------------------


@router.post("/requests", status_code=201)
async def raise_restock_request(
    payload: RaiseRestockRequestRequest,
    inventory_service: InventoryService = Depends(get_inventory_service),
    actor: User = Depends(require_permission(PERMISSION_INVENTORY_REQUEST_RESTOCK)),
) -> dict:
    request = await inventory_service.raise_restock_request(
        actor=actor,
        item_id=payload.item_id,
        requested_quantity=payload.requested_quantity,
        note=payload.note,
    )
    return success_envelope(
        InventoryRestockRequestOut.from_request(request).model_dump(mode="json")
    )


@router.get("/requests")
async def list_requests(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status: InventoryRestockRequestStatus | None = Query(default=None),
    inventory_service: InventoryService = Depends(get_inventory_service),
    _actor: User = Depends(require_permission(PERMISSION_INVENTORY_READ)),
) -> dict:
    requests, total = await inventory_service.list_requests(
        status=status, page=page, page_size=page_size
    )
    body = [
        InventoryRestockRequestOut.from_request(request).model_dump(mode="json")
        for request in requests
    ]
    meta = PaginationMeta(page=page, page_size=page_size, total=total).model_dump(mode="json")
    return success_envelope(body, meta)


@router.post("/requests/{request_id}/fulfill")
async def fulfill_request(
    request_id: UUID,
    payload: FulfillRestockRequestRequest,
    inventory_service: InventoryService = Depends(get_inventory_service),
    actor: User = Depends(require_permission(PERMISSION_INVENTORY_MANAGE)),
) -> dict:
    request = await inventory_service.fulfill_request(
        actor=actor,
        request_id=request_id,
        transfer_quantity=payload.transfer_quantity,
        transferred_on=payload.transferred_on,
    )
    return success_envelope(
        InventoryRestockRequestOut.from_request(request).model_dump(mode="json")
    )


@router.post("/requests/{request_id}/reject")
async def reject_request(
    request_id: UUID,
    payload: RejectRestockRequestRequest,
    inventory_service: InventoryService = Depends(get_inventory_service),
    actor: User = Depends(require_permission(PERMISSION_INVENTORY_MANAGE)),
) -> dict:
    request = await inventory_service.reject_request(
        actor=actor, request_id=request_id, rejection_reason=payload.rejection_reason
    )
    return success_envelope(
        InventoryRestockRequestOut.from_request(request).model_dump(mode="json")
    )


# ----------------------------------------------------------------------
# Dashboard stats — Admin Overview's "Pending Requests" indicator and
# both dashboards' low-stock badge, in one call.
# ----------------------------------------------------------------------


@router.get("/stats")
async def get_stats(
    inventory_service: InventoryService = Depends(get_inventory_service),
    _actor: User = Depends(require_permission(PERMISSION_INVENTORY_READ)),
) -> dict:
    pending_requests = await inventory_service.count_pending_requests()
    low_stock_items = await inventory_service.count_low_stock()
    return success_envelope(
        {"pending_requests": pending_requests, "low_stock_items": low_stock_items}
    )


# ----------------------------------------------------------------------
# Print — report-style A4 documents (2026-08-26 addition), Inventory
# Manager-only for the filterable log (inventory:manage — this is a
# management-oversight document, the same gate every write action on
# this module already uses), actor-scoped for the Vitals daily slip
# (inventory:record_usage, mirroring GET /usage/mine's own scoping).
# ----------------------------------------------------------------------


@router.get("/history/print", response_class=HTMLResponse)
async def print_history_log(
    log_type: Literal["receipt", "transfer", "usage"] = Query(
        description="Which of the History panel's three sub-tabs to print — "
        "prints whichever one the Inventory Manager currently has open, with "
        "whatever item/date-range filter is currently applied."
    ),
    item_id: UUID | None = Query(default=None),
    start_date: date_type | None = Query(default=None),
    end_date: date_type | None = Query(default=None),
    inventory_service: InventoryService = Depends(get_inventory_service),
    patient_service: PatientService = Depends(get_patient_service),
    user_service: UserService = Depends(get_user_service),
    settings: Settings = Depends(get_settings),
    _actor: User = Depends(require_permission(PERMISSION_INVENTORY_MANAGE)),
) -> HTMLResponse:
    """One function serves all three sub-tabs — see app/shared/printing/
    service.py's own top-level docstring on `render_inventory_history_log`
    for why. This endpoint's own job is entirely id-to-display-string
    resolution: item names (`_load_items_by_id`), "Recorded By" names
    (`UserService.list_by_ids`, 2026-08-26 addition), and — for the usage
    case only — patient names (`PatientService.list_by_ids`, same
    addition). `_ALL_ROWS_PAGE_SIZE` is a generous bound on how many rows
    a single report may print — the Inventory Manager narrows via
    `item_id`/`start_date`/`end_date` before printing, the same way any
    other filtered report would be scoped down first."""
    items_by_id = await _load_items_by_id(inventory_service)
    item_name_filter = items_by_id[item_id].name if item_id in items_by_id else None

    if log_type == "receipt":
        rows_data, _total = await inventory_service.list_receipts(
            item_id=item_id,
            start_date=start_date,
            end_date=end_date,
            page=1,
            page_size=_ALL_ROWS_PAGE_SIZE,
        )
    elif log_type == "transfer":
        rows_data, _total = await inventory_service.list_transfers(
            item_id=item_id,
            start_date=start_date,
            end_date=end_date,
            page=1,
            page_size=_ALL_ROWS_PAGE_SIZE,
        )
    else:
        rows_data, _total = await inventory_service.list_usage_entries(
            item_id=item_id,
            created_by=None,
            start_date=start_date,
            end_date=end_date,
            page=1,
            page_size=_ALL_ROWS_PAGE_SIZE,
        )

    creator_ids = list({row.created_by for row in rows_data if row.created_by is not None})
    users_by_id = {user.id: user for user in await user_service.list_by_ids(creator_ids)}

    def item_name(row_item_id: UUID) -> str:
        item = items_by_id.get(row_item_id)
        return item.name if item else "Unknown item"

    def recorded_by(created_by: UUID | None) -> str:
        user = users_by_id.get(created_by) if created_by else None
        return user.full_name if user else "—"

    total_quantity = sum((row.quantity for row in rows_data), Decimal("0")) if rows_data else None

    if log_type in ("receipt", "transfer"):
        date_attr = "received_on" if log_type == "receipt" else "transferred_on"
        column_headers = [
            "Item",
            "Quantity",
            "Received On" if log_type == "receipt" else "Transferred On",
            "Recorded By",
            "Entered",
        ]
        numeric_columns = {1}
        rows = [
            [
                item_name(row.item_id),
                str(row.quantity),
                getattr(row, date_attr).isoformat(),
                recorded_by(row.created_by),
                format_local_timestamp(row.created_at, settings.display_timezone),
            ]
            for row in rows_data
        ]
    else:
        patient_ids = list({row.patient_id for row in rows_data if row.patient_id is not None})
        patients_by_id = {
            patient.id: patient for patient in await patient_service.list_by_ids(patient_ids)
        }

        def patient_display(row) -> str:
            if row.manual_patient_name:
                return row.manual_patient_name
            patient = patients_by_id.get(row.patient_id) if row.patient_id else None
            return f"{patient.full_name} (MR: {patient.mr_number})" if patient else "—"

        column_headers = [
            "Item",
            "Quantity",
            "Patient",
            "Reason",
            "Used On",
            "Recorded By",
            "Entered",
        ]
        numeric_columns = {1}
        rows = [
            [
                item_name(row.item_id),
                str(row.quantity),
                patient_display(row),
                row.reason_note or "—",
                row.used_on.isoformat(),
                recorded_by(row.created_by),
                format_local_timestamp(row.created_at, settings.display_timezone),
            ]
            for row in rows_data
        ]

    html_document = render_inventory_history_log(
        hospital_name=settings.app_name,
        display_timezone=settings.display_timezone,
        log_type=log_type,
        generated_at=datetime.now(UTC),
        item_name_filter=item_name_filter,
        start_date=start_date,
        end_date=end_date,
        column_headers=column_headers,
        numeric_columns=numeric_columns,
        rows=rows,
        total_quantity=total_quantity,
    )
    return HTMLResponse(content=html_document)


@router.get("/usage/mine/print", response_class=HTMLResponse)
async def print_my_daily_usage_slip(
    date: date_type = Query(
        description="Calendar day (UTC) to print this user's own usage slip for."
    ),
    inventory_service: InventoryService = Depends(get_inventory_service),
    patient_service: PatientService = Depends(get_patient_service),
    settings: Settings = Depends(get_settings),
    actor: User = Depends(require_permission(PERMISSION_INVENTORY_RECORD_USAGE)),
) -> HTMLResponse:
    """Vitals' own end-of-day usage summary — always `actor.id`, never a
    request-suppliable user id, the identical hard server-side scoping
    `GET /inventory/usage/mine` already established (see that endpoint's
    own docstring); a Vitals staff member can only ever print their own
    day's entries through this, never a colleague's."""
    entries = await inventory_service.list_usage_for_creator_and_day(
        created_by=actor.id, day=datetime(date.year, date.month, date.day)
    )

    items_by_id = await _load_items_by_id(inventory_service)
    patient_ids = list({entry.patient_id for entry in entries if entry.patient_id is not None})
    patients_by_id = {
        patient.id: patient for patient in await patient_service.list_by_ids(patient_ids)
    }

    def patient_display(entry) -> str:
        if entry.manual_patient_name:
            return entry.manual_patient_name
        patient = patients_by_id.get(entry.patient_id) if entry.patient_id else None
        return f"{patient.full_name} (MR: {patient.mr_number})" if patient else "—"

    column_headers = ["Item", "Quantity", "Patient", "Reason", "Time"]
    numeric_columns = {1}
    rows = [
        [
            items_by_id[entry.item_id].name if entry.item_id in items_by_id else "Unknown item",
            str(entry.quantity),
            patient_display(entry),
            entry.reason_note or "—",
            format_local_timestamp(entry.created_at, settings.display_timezone),
        ]
        for entry in entries
    ]
    total_quantity = sum((entry.quantity for entry in entries), Decimal("0")) if entries else None

    html_document = render_inventory_daily_usage_slip(
        hospital_name=settings.app_name,
        display_timezone=settings.display_timezone,
        vitals_staff_name=actor.full_name,
        day=date,
        generated_at=datetime.now(UTC),
        column_headers=column_headers,
        numeric_columns=numeric_columns,
        rows=rows,
        total_quantity=total_quantity,
    )
    return HTMLResponse(content=html_document)

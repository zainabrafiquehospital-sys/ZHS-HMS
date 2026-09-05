"""HTTP endpoints for the Ward/Emergency Inventory Management module.
Catalog management, Main Stock receipts, direct-to-Emergency receipts
(2026-09 addition — see `InventoryEmergencyDirectReceipt`'s own
docstring for why this exists alongside Main Stock receiving, not
instead of it), transfers to Emergency Stock, and restock-request
fulfillment/rejection all require `inventory:manage` (Inventory
Manager-only); recording a usage entry requires
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
    InventoryEmergencyDirectReceiptOut,
    InventoryItemOut,
    InventoryItemSortField,
    InventoryMainStockReceiptOut,
    InventoryPatientContextOut,
    InventoryRestockRequestOut,
    InventoryTransferOut,
    InventoryUsageEntryOut,
    RaiseRestockRequestRequest,
    ReceiveDirectToEmergencyRequest,
    ReceiveStockBatchRequest,
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


@router.post("/receipts", status_code=201)
async def receive_stock_batch(
    payload: ReceiveStockBatchRequest,
    inventory_service: InventoryService = Depends(get_inventory_service),
    actor: User = Depends(require_permission(PERMISSION_INVENTORY_MANAGE)),
) -> dict:
    """Top-level batch route (2026-09 addition, the checklist-entry
    redesign) — same "returns every item touched, final post-receipt
    state" shape `POST /transfers` already established, for the
    identical reason (a batch's items can span more than one item id).
    The original single-item `POST /items/{item_id}/receive` above is
    untouched — see `InventoryService.receive_stock_batch`'s own
    docstring for why this is additive, not a replacement."""
    items = await inventory_service.receive_stock_batch(
        actor=actor,
        items=[(line.item_id, line.quantity) for line in payload.items],
        received_on=payload.received_on,
    )
    body = [InventoryItemOut.from_item(item).model_dump(mode="json") for item in items]
    return success_envelope(body)


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
# Direct-to-Emergency receipts — Inventory Manager-only (2026-09
# addition; see InventoryEmergencyDirectReceipt's own docstring)
# ----------------------------------------------------------------------


@router.post("/emergency-receipts", status_code=201)
async def receive_directly_to_emergency(
    payload: ReceiveDirectToEmergencyRequest,
    inventory_service: InventoryService = Depends(get_inventory_service),
    actor: User = Depends(require_permission(PERMISSION_INVENTORY_MANAGE)),
) -> dict:
    """The real-world-shaped receiving path — see this module's own
    top-level docstring and `InventoryService.
    receive_directly_to_emergency`'s own docstring. Same batch shape and
    "returns every item touched" response as `POST /receipts`/
    `POST /transfers`; also auto-resolves any pending restock request
    for each item received (see `InventoryRestockRequest.
    fulfilled_by_direct_receipt_id`'s docstring) — nothing about *that*
    needs to appear in this request body, it happens as a side effect
    the response's `is_low_stock`/stock levels already reflect."""
    items = await inventory_service.receive_directly_to_emergency(
        actor=actor,
        items=[(line.item_id, line.quantity) for line in payload.items],
        received_on=payload.received_on,
    )
    body = [InventoryItemOut.from_item(item).model_dump(mode="json") for item in items]
    return success_envelope(body)


@router.get("/emergency-receipts")
async def list_emergency_direct_receipts(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    item_id: UUID | None = Query(default=None),
    start_date: date_type | None = Query(default=None),
    end_date: date_type | None = Query(default=None),
    inventory_service: InventoryService = Depends(get_inventory_service),
    _actor: User = Depends(require_permission(PERMISSION_INVENTORY_READ)),
) -> dict:
    receipts, total = await inventory_service.list_emergency_direct_receipts(
        item_id=item_id, start_date=start_date, end_date=end_date, page=page, page_size=page_size
    )
    body = [
        InventoryEmergencyDirectReceiptOut.from_receipt(receipt).model_dump(mode="json")
        for receipt in receipts
    ]
    meta = PaginationMeta(page=page, page_size=page_size, total=total).model_dump(mode="json")
    return success_envelope(body, meta)


# ----------------------------------------------------------------------
# Transfers — Inventory Manager-only
# ----------------------------------------------------------------------


@router.post("/transfers")
async def transfer_stock(
    payload: TransferStockRequest,
    inventory_service: InventoryService = Depends(get_inventory_service),
    actor: User = Depends(require_permission(PERMISSION_INVENTORY_MANAGE)),
) -> dict:
    """Top-level route (2026-08-28 batch addition; replaces the old
    single-item `POST /items/{item_id}/transfer`, since a batch's items
    can span more than one item id, the same reason `POST /usage` was
    already top-level rather than nested under one item). Returns every
    item touched by the batch, final post-transfer state — the
    frontend's cache-patch target, same shape `record_usage` could have
    used had usage entries carried item-level state to hand back."""
    items = await inventory_service.transfer_to_emergency(
        actor=actor,
        items=[(line.item_id, line.quantity) for line in payload.items],
        transferred_on=payload.transferred_on,
        carried_by_name=payload.carried_by_name,
    )
    body = [InventoryItemOut.from_item(item).model_dump(mode="json") for item in items]
    return success_envelope(body)


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
    entries = await inventory_service.record_usage(
        actor=actor,
        items=[(line.item_id, line.quantity, line.reason_note) for line in payload.items],
        used_on=payload.used_on,
        patient_id=payload.patient_id,
        manual_patient_name=payload.manual_patient_name,
        manual_patient_age=payload.manual_patient_age,
        manual_patient_phone=payload.manual_patient_phone,
    )
    body = [InventoryUsageEntryOut.from_entry(entry).model_dump(mode="json") for entry in entries]
    return success_envelope(body)


@router.get("/usage")
async def list_usage_entries(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    item_id: UUID | None = Query(default=None),
    created_by: UUID | None = Query(default=None),
    start_date: date_type | None = Query(default=None),
    end_date: date_type | None = Query(default=None),
    inventory_service: InventoryService = Depends(get_inventory_service),
    patient_service: PatientService = Depends(get_patient_service),
    user_service: UserService = Depends(get_user_service),
    _actor: User = Depends(require_permission(PERMISSION_INVENTORY_READ)),
) -> dict:
    """Backs the on-screen History panel's Usage tab (shared wholesale by
    both the Inventory Manager's own History tab and Admin's Inventory
    History tab, see `InventoryHistoryPanel.jsx`), Vitals' own "My
    Inventory Usage" (`created_by` scoped to the caller), and the
    cross-role Daily Usage view (2026-09-04 addition, date-range scoped,
    no `created_by`). Resolves `patient_id` to a real display name here
    (2026-08-28 fix) and `created_by` to the recording staff member's own
    display name (2026-09-04 addition) — the identical
    `PatientService.list_by_ids`/`UserService.list_by_ids` batch joins
    `print_history_log` below has always used for its own printed
    version of this same log. The creator join in particular matters
    here specifically because this endpoint is held by all three
    `inventory:read` roles, and only Admin also holds `users:read` to
    resolve a colleague's name itself — resolving it server-side once,
    regardless of the caller's own permissions, is what lets Vitals and
    the Inventory Manager see "who recorded this" without a new grant."""
    entries, total = await inventory_service.list_usage_entries(
        item_id=item_id,
        created_by=created_by,
        start_date=start_date,
        end_date=end_date,
        page=page,
        page_size=page_size,
    )
    patient_ids = list({entry.patient_id for entry in entries if entry.patient_id is not None})
    patients_by_id = {
        patient.id: patient for patient in await patient_service.list_by_ids(patient_ids)
    }
    creator_ids = list({entry.created_by for entry in entries if entry.created_by is not None})
    creators_by_id = {user.id: user for user in await user_service.list_by_ids(creator_ids)}
    body = [
        InventoryUsageEntryOut.from_entry(
            entry,
            patients_by_id.get(entry.patient_id) if entry.patient_id else None,
            creators_by_id.get(entry.created_by) if entry.created_by else None,
        ).model_dump(mode="json")
        for entry in entries
    ]
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
        carried_by_name=payload.carried_by_name,
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

    if log_type == "receipt":
        column_headers = ["Item", "Quantity", "Received On", "Recorded By", "Entered"]
        numeric_columns = {1}
        rows = [
            [
                item_name(row.item_id),
                str(row.quantity),
                row.received_on.isoformat(),
                recorded_by(row.created_by),
                format_local_timestamp(row.created_at, settings.display_timezone),
            ]
            for row in rows_data
        ]
    elif log_type == "transfer":
        # "Carried By" (2026-08-28 addition) — the person who physically
        # carried the stock, `None` for every transfer recorded before
        # this field existed (see InventoryTransfer.carried_by_name's own
        # docstring); shown as "—" the same as any other unresolved cell
        # in this report.
        column_headers = [
            "Item",
            "Quantity",
            "Transferred On",
            "Carried By",
            "Recorded By",
            "Entered",
        ]
        numeric_columns = {1}
        rows = [
            [
                item_name(row.item_id),
                str(row.quantity),
                row.transferred_on.isoformat(),
                row.carried_by_name or "—",
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


@router.get("/usage/daily/print", response_class=HTMLResponse)
async def print_daily_usage(
    date: date_type = Query(description="Calendar day (UTC) to print the Daily Usage view for."),
    inventory_service: InventoryService = Depends(get_inventory_service),
    patient_service: PatientService = Depends(get_patient_service),
    user_service: UserService = Depends(get_user_service),
    settings: Settings = Depends(get_settings),
    _actor: User = Depends(require_permission(PERMISSION_INVENTORY_READ)),
) -> HTMLResponse:
    """The Daily Usage view's own day-wise export (2026-09-04 addition)
    — a thin, `inventory:read`-gated wrapper around the exact same
    `render_inventory_history_log` report `print_history_log` above
    already uses for its own (Inventory-Manager-only) Usage sub-tab, not
    a new print template. Two differences from that endpoint, both
    deliberate:

    - Gated on `inventory:read`, not `inventory:manage` — this view is
      shared by Inventory Manager, Admin, *and* Vitals (see this
      module's own top-level docstring), and Vitals never holds
      `inventory:manage`. `print_history_log` stays `inventory:manage`-
      gated unchanged; it also legitimately covers receipts/transfers,
      which must stay Inventory-Manager-only data.
    - Hospital-wide and single-day only (`created_by=None`, `start_date
      == end_date == date`), never scoped to `item_id` or to the
      on-screen text search the Daily Usage view's own patient/item
      search box applies — this exports "every item used, on which
      patient, at what time, that day" exactly as specified, independent
      of whatever the viewer currently has filtered on screen.

    Deliberately does NOT reuse either of the two now-orphaned per-actor
    print endpoints below (`GET /inventory/usage/mine/print`, `GET
    /vitals/daily-summary/print`) — both are hard-scoped to the calling
    actor's own day, the opposite of "everyone's usage, hospital-wide,
    for a given day" this view needs, and their frontend entry points
    were removed as broken with no recorded root cause (see this
    endpoint's own commit message); this reuses the render pipeline that
    is verifiably still working today (`print_history_log`'s own tests,
    and its live "Print" button on the Inventory History panel) rather
    than resurrecting either of those two.

    Two sections in one document (2026-09-05 addition): a "Total Usage
    Summary" — one line per distinct item, quantity summed across every
    patient/submission that day — ahead of the detail table, via
    `render_inventory_history_log`'s optional `summary_rows` (see that
    function's own docstring). Aggregated here from the same `entries`
    list the detail table already uses — no second query.

    The detail table itself is grouped one row per "Record Usage"
    submission (2026-09 addition), not one row per item — matching the
    on-screen Daily Usage table's own grouping exactly (identical
    `created_at` + resolved-patient-display-name key as frontend/src/
    features/inventory/utils/groupUsageEntries.js; see this function's
    own `patient_display_key`/grouping code for the full rationale), so
    a patient who received several items in one sitting prints as one
    row instead of that many near-duplicate lines."""
    entries, _total = await inventory_service.list_usage_entries(
        item_id=None,
        created_by=None,
        start_date=date,
        end_date=date,
        page=1,
        page_size=_ALL_ROWS_PAGE_SIZE,
    )

    items_by_id = await _load_items_by_id(inventory_service)
    patient_ids = list({entry.patient_id for entry in entries if entry.patient_id is not None})
    patients_by_id = {
        patient.id: patient for patient in await patient_service.list_by_ids(patient_ids)
    }
    creator_ids = list({entry.created_by for entry in entries if entry.created_by is not None})
    users_by_id = {user.id: user for user in await user_service.list_by_ids(creator_ids)}

    def item_name(item_id: UUID) -> str:
        item = items_by_id.get(item_id)
        return item.name if item else "Unknown item"

    def recorded_by(created_by: UUID | None) -> str:
        user = users_by_id.get(created_by) if created_by else None
        return user.full_name if user else "—"

    def patient_display_key(entry) -> str | None:
        """The same display string `InventoryUsageEntryOut.from_entry`
        resolves as `patient_display_name` — and therefore the exact
        value frontend/src/features/inventory/utils/groupUsageEntries.js
        groups by. `None` only for the fully-anonymous case (no linked
        patient, no manual name), mirroring that field's own `None`
        convention rather than substituting a display fallback here —
        grouping needs the real value; the "—"/"(Walk-in)" display
        fallbacks are applied separately, right where a group's own
        Patient cell is built below."""
        if entry.manual_patient_name:
            return entry.manual_patient_name
        patient = patients_by_id.get(entry.patient_id) if entry.patient_id else None
        return f"{patient.full_name} (MR: {patient.mr_number})" if patient else None

    # Group entries into one row per "Record Usage" submission — the
    # identical grouping key frontend/src/features/inventory/utils/
    # groupUsageEntries.js already established (created_at + resolved
    # patient display name, `''` standing in for the anonymous `None`
    # case on both sides), so this printed grouping can never disagree
    # with what the on-screen Daily Usage table already groups into one
    # row. There is no batch/session parent entity by design (see
    # InventoryUsageEntry's own docstring) — `created_at` is reliable
    # here because `record_usage` writes a whole submission's lines,
    # then commits, in exactly one transaction, so every line shares the
    # exact same timestamp down to the microsecond. `entries` already
    # arrives newest-first (`list_for_range`'s own `created_at.desc()`
    # ordering), and a plain dict preserves insertion order, so no
    # separate sort is needed to keep groups newest-submission-first.
    groups: dict[tuple[datetime, str], list] = {}
    for entry in entries:
        key = (entry.created_at, patient_display_key(entry) or "")
        groups.setdefault(key, []).append(entry)

    # One row per submission, not per item — the whole point of this
    # grouping (2026-09 addition): a patient who received several items
    # in one sitting used to print as that many separate, mostly-
    # identical lines. "Item"/"Quantity"/"Reason" fold into one "Items
    # Used" cell (each line rendered as "Name ×Qty (reason)", joined by
    # "; ") rather than three separately-joined parallel columns, which
    # would risk a reader misaligning which reason belongs to which item
    # when only some lines carry one. A printed report has no "Show
    # Details" drill-down the on-screen view can fall back on, so every
    # line item is spelled out in full here — never truncated to a
    # "+N more" teaser the way the on-screen summary cell is.
    column_headers = ["Patient", "Items Used", "Time", "Recorded By"]
    numeric_columns: set[int] = set()
    rows = []
    for (created_at, _patient_key), group_entries in groups.items():
        first = group_entries[0]
        if first.patient_id:
            patient_cell = patient_display_key(first) or "—"
        else:
            # No linked patient — manual walk-in name, or genuinely
            # anonymous — same "Walk-in" distinction PatientHistorySearch.
            # jsx's own PatientCells and the on-screen Daily Usage table's
            # PatientCell already apply, now applied here too.
            patient_cell = f"{first.manual_patient_name or 'Anonymous'} (Walk-in)"
        items_used_cell = "; ".join(
            f"{item_name(line.item_id)} ×{line.quantity}"
            + (f" ({line.reason_note})" if line.reason_note else "")
            for line in group_entries
        )
        rows.append(
            [
                patient_cell,
                items_used_cell,
                format_local_timestamp(created_at, settings.display_timezone),
                recorded_by(first.created_by),
            ]
        )
    # Independent of how rows are grouped for display — still the exact
    # Decimal-precise sum of every individual entry that day.
    total_quantity = sum((entry.quantity for entry in entries), Decimal("0")) if entries else None

    # Total Usage Summary (2026-09-05 addition) — one line per distinct
    # item, the Decimal-exact sum of every entry against it that day
    # across every patient/submission (Decimal + Decimal stays exact,
    # e.g. 0.5 + 0.5 == 1.0 — never routed through float). Aggregated
    # over this same already-fetched `entries` list, no second query.
    # Sorted by total quantity descending (ties broken by name) rather
    # than alphabetically — a reconciliation reader wants "what got used
    # the most today" surfaced first, not buried in an alphabetical scan.
    quantity_by_item: dict[UUID, Decimal] = {}
    for entry in entries:
        quantity_by_item[entry.item_id] = (
            quantity_by_item.get(entry.item_id, Decimal("0")) + entry.quantity
        )
    summary_rows_data = sorted(
        quantity_by_item.items(), key=lambda pair: (-pair[1], item_name(pair[0]))
    )

    def item_unit(item_id: UUID) -> str:
        item = items_by_id.get(item_id)
        return item.unit.value if item else "—"

    html_document = render_inventory_history_log(
        hospital_name=settings.app_name,
        display_timezone=settings.display_timezone,
        log_type="usage",
        generated_at=datetime.now(UTC),
        item_name_filter=None,
        start_date=date,
        end_date=date,
        column_headers=column_headers,
        numeric_columns=numeric_columns,
        rows=rows,
        total_quantity=total_quantity,
        summary_title="Total Usage Summary",
        summary_column_headers=["Item", "Unit", "Total Quantity"],
        summary_numeric_columns={2},
        summary_rows=[
            [item_name(item_id), item_unit(item_id), str(total)]
            for item_id, total in summary_rows_data
        ],
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

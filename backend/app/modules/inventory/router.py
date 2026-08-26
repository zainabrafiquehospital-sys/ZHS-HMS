"""HTTP endpoints for the Ward/Emergency Inventory Management module.
Catalog management, Main Stock receipts, transfers to Emergency Stock,
and restock-request fulfillment/rejection all require `inventory:manage`
(Inventory Manager-only); recording a usage entry requires
`inventory:record_usage` and raising a restock request requires
`inventory:request_restock` (both Vitals-only); every read endpoint
requires only `inventory:read` (Inventory Manager, Vitals, and Admin —
see constants.py's module docstring). Doctor holds none of these and
reaches nothing here.

Print endpoints (the transfer log and the Vitals daily usage slip) are
deliberately not part of this file yet — per the confirmed design, those
are report-style, PDF-first documents needing a different mechanism than
the Central Print Service's existing thermal-receipt renderers, and are
being investigated/confirmed as their own build step before
implementation, not assumed here."""

from datetime import date as date_type
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.modules.auth.dependencies import require_permission
from app.modules.auth.models import User
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
from app.shared.envelope import success_envelope
from app.shared.pagination import PaginationMeta, SortOrder

router = APIRouter(prefix="/inventory", tags=["inventory"])


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

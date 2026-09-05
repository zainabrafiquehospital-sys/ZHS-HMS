"""Pydantic request/response schemas for the Inventory module — mirrors
app/modules/pharmacy/schemas.py's shape and conventions exactly
(LaxUUID/LaxDecimal for strict-mode request bodies, `from_attributes` +
a `from_x` classmethod for responses)."""

from datetime import date as date_type
from datetime import datetime
from decimal import Decimal
from enum import Enum as PyEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.auth.models import User
from app.modules.inventory.models import (
    InventoryCategory,
    InventoryEmergencyDirectReceipt,
    InventoryItem,
    InventoryMainStockReceipt,
    InventoryRestockRequest,
    InventoryRestockRequestStatus,
    InventoryTransfer,
    InventoryUnit,
    InventoryUsageEntry,
)
from app.modules.patients.models import Patient
from app.modules.visits.models import Visit
from app.shared.schema_types import LaxDecimal, LaxUUID


class InventoryItemSortField(str, PyEnum):
    CREATED_AT = "created_at"
    NAME = "name"


# ---------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------


class CreateInventoryItemRequest(BaseModel):
    model_config = ConfigDict(strict=True)

    name: str = Field(min_length=1, max_length=150)
    category: InventoryCategory = Field(strict=False)
    unit: InventoryUnit = Field(strict=False)
    low_stock_threshold: LaxDecimal | None = Field(default=None, gt=0)


class UpdateInventoryItemRequest(BaseModel):
    """All fields optional for PATCH-style partial update — cross-field
    category/unit compatibility is validated in
    `InventoryService.update_item`, not here (see that method's own
    docstring for why a per-request validator can't correctly check the
    *resulting* combination)."""

    model_config = ConfigDict(strict=True)

    name: str | None = Field(default=None, min_length=1, max_length=150)
    category: InventoryCategory | None = Field(default=None, strict=False)
    unit: InventoryUnit | None = Field(default=None, strict=False)
    low_stock_threshold: LaxDecimal | None = Field(default=None, gt=0)
    is_active: bool | None = None


class ReceiveStockRequest(BaseModel):
    model_config = ConfigDict(strict=True)

    quantity: LaxDecimal = Field(gt=0)
    # strict=False: a plain (non-container) field, so — like the enum
    # fields elsewhere in this file — a local override is sufficient on
    # its own (see app/shared/schema_types.py's LaxUUID docstring for
    # why that stops being true only for a parametrized generic). JSON
    # has no native date representation; a real client always sends an
    # ISO string (e.g. "2026-08-26"), which `ConfigDict(strict=True)`
    # rejects outright for a plain `date` field without this.
    received_on: date_type = Field(strict=False)


class ReceiveLineItemRequest(BaseModel):
    """One line of a batch receiving request's `items` list — same
    `item_id`/`quantity` per-line shape as `TransferLineItemRequest`/
    `UsageLineItemRequest` (nothing about "how much of this item
    arrived" varies beyond the quantity itself), shared by both
    `ReceiveStockBatchRequest` (Main Stock) and
    `ReceiveDirectToEmergencyRequest` (Emergency Stock, 2026-09
    addition) — receiving is the same shape regardless of which tier
    it lands in."""

    model_config = ConfigDict(strict=True)

    item_id: LaxUUID
    quantity: LaxDecimal = Field(gt=0)


class ReceiveStockBatchRequest(BaseModel):
    """Batch Main Stock receiving (2026-09 addition, the checklist-entry
    redesign) — one `received_on` shared across one-or-more items,
    submitted together the same shape `TransferStockRequest`/
    `RecordUsageRequest` already established for their own `items`
    batches. Backs the new `POST /inventory/receipts`; the original
    single-item `POST /items/{item_id}/receive` (`ReceiveStockRequest`
    above) is untouched and still works unchanged — see
    `InventoryService.receive_stock_batch`'s own docstring for why both
    exist side by side rather than one replacing the other."""

    model_config = ConfigDict(strict=True)

    items: list[ReceiveLineItemRequest] = Field(min_length=1)
    received_on: date_type = Field(strict=False)


class ReceiveDirectToEmergencyRequest(BaseModel):
    """Batch direct-to-Emergency-Stock receiving (2026-09 addition) —
    identical shape to `ReceiveStockBatchRequest` above, just landing in
    `emergency_stock_level` instead of `main_stock_level` via
    `InventoryService.receive_directly_to_emergency`, which also auto-
    resolves any pending restock request for each item — see that
    method's own docstring and `InventoryRestockRequest.
    fulfilled_by_direct_receipt_id`'s docstring for the full "why
    auto-resolve, no explicit request_id here" reasoning."""

    model_config = ConfigDict(strict=True)

    items: list[ReceiveLineItemRequest] = Field(min_length=1)
    received_on: date_type = Field(strict=False)


class TransferLineItemRequest(BaseModel):
    """One line of a `TransferStockRequest`'s `items` batch — same
    per-line shape (`item_id`/`quantity`) as `UsageLineItemRequest`
    below, just with no per-line note (nothing about "who carried it"
    varies per item within one batch — that's `carried_by_name`,
    shared across the whole transfer)."""

    model_config = ConfigDict(strict=True)

    item_id: LaxUUID
    quantity: LaxDecimal = Field(gt=0)


class TransferStockRequest(BaseModel):
    """Batch transfer (2026-08-28 addition) — one `transferred_on`/
    `carried_by_name` shared across one-or-more items, submitted
    together the same shape `RecordUsageRequest` established for its
    own `items` batch. `carried_by_name` is required for every transfer
    from this addition onward (free text — the person who physically
    carried the stock, not necessarily a system user); pre-existing
    transfer rows predate this field entirely and stay `NULL` forever
    rather than backfilled with a fabricated value — see the migration
    that added this column for the full rationale."""

    model_config = ConfigDict(strict=True)

    items: list[TransferLineItemRequest] = Field(min_length=1)
    transferred_on: date_type = Field(strict=False)
    carried_by_name: str = Field(min_length=1, max_length=150)


class UsageLineItemRequest(BaseModel):
    """One line of a `RecordUsageRequest`'s `items` batch — same
    per-line shape (`item_id`/`quantity` plus an optional per-line
    note) as `pharmacy/schemas.py`'s `MedicineBillLineItemRequest`.
    `reason_note` is per-line (not a single top-level field) since two
    items used for the same patient in the same batch can easily have
    different reasons."""

    model_config = ConfigDict(strict=True)

    item_id: LaxUUID
    quantity: LaxDecimal = Field(gt=0)
    reason_note: str | None = Field(default=None, max_length=200)


class RecordUsageRequest(BaseModel):
    """Batch usage recording (2026-08-27 addition) — one patient
    context (linked or manual) plus one-or-more items, submitted
    together the same way `CreateMedicineBillRequest.items` batches
    medicine lines. This does **not** introduce a batch/session parent
    entity: `InventoryService.record_usage` still writes one fully
    independent `InventoryUsageEntry` row per line (see models.py's
    `InventoryUsageEntry` docstring), just atomically — all rows
    commit together, or none do — matching `PharmacyService.
    create_bill`'s own all-or-nothing shape."""

    model_config = ConfigDict(strict=True)

    items: list[UsageLineItemRequest] = Field(min_length=1)
    used_on: date_type = Field(strict=False)
    # Patient-linked (mutually exclusive with the manual fields below,
    # all-or-nothing) — see models.py's InventoryUsageEntry docstring
    # for the full rationale; cross-field validation happens in
    # InventoryService.record_usage, not here. Fixed for the whole
    # batch, mirroring RegisterVisitForm keeping one patient context
    # while procedures are added one at a time.
    patient_id: LaxUUID | None = None
    manual_patient_name: str | None = Field(default=None, min_length=1, max_length=150)
    manual_patient_age: int | None = Field(default=None, ge=0, le=150)
    manual_patient_phone: str | None = Field(default=None, min_length=6, max_length=20)


class RaiseRestockRequestRequest(BaseModel):
    model_config = ConfigDict(strict=True)

    item_id: LaxUUID
    # Optional — "just flag it low" (manager's judgment on how much) is
    # a legitimate request with no specific number, see models.py's
    # InventoryRestockRequest docstring.
    requested_quantity: LaxDecimal | None = Field(default=None, gt=0)
    note: str | None = Field(default=None, max_length=200)


class PrintRequirementLineItem(BaseModel):
    """One line of a `PrintRequirementListRequest`'s `items` list —
    `quantity` is optional (same "just flag it low" design as
    `RaiseRestockRequestRequest.requested_quantity`, see
    `InventoryRestockRequest`'s own docstring): the printed Requirement
    document must be able to show an item with no specific number
    attached just as legitimately as one with a number."""

    model_config = ConfigDict(strict=True)

    item_id: LaxUUID
    quantity: LaxDecimal | None = Field(default=None, gt=0)


class PrintRequirementListRequest(BaseModel):
    """Vitals' "Build Requirement" checklist's own downloadable-PDF
    request (2026-09 addition) — renders directly from whatever items/
    quantities the caller's own in-progress checklist currently holds,
    never a query over already-saved `InventoryRestockRequest` rows (see
    `render_inventory_requirement_list`'s own docstring for the full
    "point-in-time snapshot, not a historical query" rationale). No
    `used_on`/date field at all — unlike every other batch request in
    this module, this one has no effective date of its own; it is
    rendered "as of now"."""

    model_config = ConfigDict(strict=True)

    items: list[PrintRequirementLineItem] = Field(min_length=1)


class FulfillRestockRequestRequest(BaseModel):
    """Fulfilling a request performs a transfer internally (see
    `InventoryService.fulfill_request`'s own docstring) — `carried_by_name`
    is required here too, for the same reason it's required on
    `TransferStockRequest`: the model has no way to tell the two paths
    apart, and "who physically carried it" applies just as much to a
    fulfillment-driven transfer as a manually-initiated one."""

    model_config = ConfigDict(strict=True)

    transfer_quantity: LaxDecimal = Field(gt=0)
    transferred_on: date_type = Field(strict=False)
    carried_by_name: str = Field(min_length=1, max_length=150)


class RejectRestockRequestRequest(BaseModel):
    model_config = ConfigDict(strict=True)

    rejection_reason: str | None = Field(default=None, max_length=200)


# ---------------------------------------------------------------------
# Responses
# ---------------------------------------------------------------------


class InventoryItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    category: InventoryCategory
    unit: InventoryUnit
    low_stock_threshold: Decimal | None
    main_stock_level: Decimal
    emergency_stock_level: Decimal
    is_active: bool
    # Computed, never stored — see models.py's InventoryItem docstring
    # on why this is a live comparison, not a cached flag.
    is_low_stock: bool
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_item(cls, item: InventoryItem) -> "InventoryItemOut":
        is_low_stock = (
            item.low_stock_threshold is not None
            and item.emergency_stock_level <= item.low_stock_threshold
        )
        return cls(
            id=item.id,
            name=item.name,
            category=item.category,
            unit=item.unit,
            low_stock_threshold=item.low_stock_threshold,
            main_stock_level=item.main_stock_level,
            emergency_stock_level=item.emergency_stock_level,
            is_active=item.is_active,
            is_low_stock=is_low_stock,
            created_at=item.created_at,
            updated_at=item.updated_at,
        )


class InventoryMainStockReceiptOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    item_id: UUID
    quantity: Decimal
    received_on: date_type
    created_by: UUID | None
    created_at: datetime

    @classmethod
    def from_receipt(cls, receipt: InventoryMainStockReceipt) -> "InventoryMainStockReceiptOut":
        return cls(
            id=receipt.id,
            item_id=receipt.item_id,
            quantity=receipt.quantity,
            received_on=receipt.received_on,
            created_by=receipt.created_by,
            created_at=receipt.created_at,
        )


class InventoryEmergencyDirectReceiptOut(BaseModel):
    """Mirrors `InventoryMainStockReceiptOut` exactly — same fields, same
    shape, a different ledger table underneath (see
    `InventoryEmergencyDirectReceipt`'s own docstring)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    item_id: UUID
    quantity: Decimal
    received_on: date_type
    created_by: UUID | None
    created_at: datetime

    @classmethod
    def from_receipt(
        cls, receipt: InventoryEmergencyDirectReceipt
    ) -> "InventoryEmergencyDirectReceiptOut":
        return cls(
            id=receipt.id,
            item_id=receipt.item_id,
            quantity=receipt.quantity,
            received_on=receipt.received_on,
            created_by=receipt.created_by,
            created_at=receipt.created_at,
        )


class InventoryTransferOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    item_id: UUID
    quantity: Decimal
    transferred_on: date_type
    # `None` for every transfer recorded before this field existed —
    # see TransferStockRequest's own docstring; displayed as "—"
    # wherever a transfer is shown.
    carried_by_name: str | None
    created_by: UUID | None
    created_at: datetime

    @classmethod
    def from_transfer(cls, transfer: InventoryTransfer) -> "InventoryTransferOut":
        return cls(
            id=transfer.id,
            item_id=transfer.item_id,
            quantity=transfer.quantity,
            transferred_on=transfer.transferred_on,
            carried_by_name=transfer.carried_by_name,
            created_by=transfer.created_by,
            created_at=transfer.created_at,
        )


class InventoryUsageEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    item_id: UUID
    quantity: Decimal
    used_on: date_type
    patient_id: UUID | None
    manual_patient_name: str | None
    manual_patient_age: int | None
    manual_patient_phone: str | None
    reason_note: str | None
    created_by: UUID | None
    created_at: datetime
    # Always the final display string — `manual_patient_name` when
    # present, else the resolved `"{full_name} (MR: {mr_number})"` for
    # a search-linked patient, else "—" (2026-08-28 addition; the
    # on-screen History table used to fall back to a raw patient_id
    # fragment for search-linked entries instead of resolving it — see
    # this field's caller in router.py's list_usage_entries for the
    # actual resolution, the identical PatientService.list_by_ids join
    # the print log has always used). Callers that can't resolve a
    # patient (none currently) just pass `patient=None`.
    patient_display_name: str | None
    # The recording staff member's own display name (2026-09-04 addition,
    # Daily Usage view) - resolved the identical way patient_display_name
    # already is, and by the same router.py caller that already does this
    # exact UserService.list_by_ids batch join for print_history_log's
    # own "Recorded By" column. Added here (not left print-only) because
    # this endpoint is shared cross-role (inventory:read - Inventory
    # Manager, Admin, and Vitals), and Vitals holds no users:read to
    # resolve a colleague's name itself via GET /users/{id} the way an
    # Admin screen's own useUsersForLabBills-style join does - resolving
    # it here, once, server-side, is the only way every holder of
    # inventory:read can see who recorded an entry without a new
    # permission grant. None when the creator is unknown/unresolved, the
    # same "let the frontend render its own dash" convention
    # patient_display_name already establishes.
    created_by_display_name: str | None

    @classmethod
    def from_entry(
        cls,
        entry: InventoryUsageEntry,
        patient: Patient | None = None,
        creator: User | None = None,
    ) -> "InventoryUsageEntryOut":
        if entry.manual_patient_name:
            patient_display_name = entry.manual_patient_name
        elif patient is not None:
            patient_display_name = f"{patient.full_name} (MR: {patient.mr_number})"
        else:
            patient_display_name = None
        return cls(
            id=entry.id,
            item_id=entry.item_id,
            quantity=entry.quantity,
            used_on=entry.used_on,
            patient_id=entry.patient_id,
            manual_patient_name=entry.manual_patient_name,
            manual_patient_age=entry.manual_patient_age,
            manual_patient_phone=entry.manual_patient_phone,
            reason_note=entry.reason_note,
            created_by=entry.created_by,
            created_at=entry.created_at,
            patient_display_name=patient_display_name,
            created_by_display_name=creator.full_name if creator is not None else None,
        )


class InventoryRestockRequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    item_id: UUID
    requested_quantity: Decimal | None
    note: str | None
    status: InventoryRestockRequestStatus
    fulfilled_by_transfer_id: UUID | None
    # 2026-09 addition — set instead of `fulfilled_by_transfer_id` when a
    # direct-to-Emergency receipt auto-resolved this request rather than
    # a transfer; the two are mutually exclusive, see
    # InventoryRestockRequest's own docstring.
    fulfilled_by_direct_receipt_id: UUID | None
    rejection_reason: str | None
    resolved_by: UUID | None
    resolved_at: datetime | None
    created_by: UUID | None
    created_at: datetime

    @classmethod
    def from_request(cls, request: InventoryRestockRequest) -> "InventoryRestockRequestOut":
        return cls(
            id=request.id,
            item_id=request.item_id,
            requested_quantity=request.requested_quantity,
            note=request.note,
            status=request.status,
            fulfilled_by_transfer_id=request.fulfilled_by_transfer_id,
            fulfilled_by_direct_receipt_id=request.fulfilled_by_direct_receipt_id,
            rejection_reason=request.rejection_reason,
            resolved_by=request.resolved_by,
            resolved_at=request.resolved_at,
            created_by=request.created_by,
            created_at=request.created_at,
        )


class InventoryPatientContextVisitOut(BaseModel):
    """The minimal Visit projection the usage-entry screen's read-only
    preview needs — deliberately not `visits.schemas.VisitSummary` (which
    omits `procedure`, the one field this preview actually exists to
    show)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    queue_token: str
    procedure: str

    @classmethod
    def from_visit(cls, visit: Visit) -> "InventoryPatientContextVisitOut":
        return cls(id=visit.id, queue_token=visit.queue_token, procedure=visit.procedure)


class InventoryPatientContextOut(BaseModel):
    """`GET /inventory/patients/{id}/context`'s response — the patient's
    MR number/identity plus their most recent registered visit's
    procedure, if any (`None` for a genuine ward/emergency patient with
    no OPD visit on file — a normal outcome, never an error; see
    InventoryService.get_patient_context's own docstring)."""

    model_config = ConfigDict(strict=True)

    patient_id: UUID
    mr_number: str
    full_name: str
    age_years: int
    phone_number: str
    latest_visit: InventoryPatientContextVisitOut | None

    @classmethod
    def from_context(
        cls, patient: Patient, latest_visit: Visit | None
    ) -> "InventoryPatientContextOut":
        return cls(
            patient_id=patient.id,
            mr_number=patient.mr_number,
            full_name=patient.full_name,
            age_years=patient.age_years,
            phone_number=patient.phone_number,
            latest_visit=(
                InventoryPatientContextVisitOut.from_visit(latest_visit) if latest_visit else None
            ),
        )

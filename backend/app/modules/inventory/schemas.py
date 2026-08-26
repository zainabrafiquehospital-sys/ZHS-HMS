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

from app.modules.inventory.models import (
    InventoryCategory,
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


class TransferStockRequest(BaseModel):
    model_config = ConfigDict(strict=True)

    quantity: LaxDecimal = Field(gt=0)
    transferred_on: date_type = Field(strict=False)


class RecordUsageRequest(BaseModel):
    model_config = ConfigDict(strict=True)

    item_id: LaxUUID
    quantity: LaxDecimal = Field(gt=0)
    used_on: date_type = Field(strict=False)
    # Patient-linked (mutually exclusive with the manual fields below,
    # all-or-nothing) — see models.py's InventoryUsageEntry docstring
    # for the full rationale; cross-field validation happens in
    # InventoryService.record_usage, not here.
    patient_id: LaxUUID | None = None
    manual_patient_name: str | None = Field(default=None, min_length=1, max_length=150)
    manual_patient_age: int | None = Field(default=None, ge=0, le=150)
    manual_patient_phone: str | None = Field(default=None, min_length=6, max_length=20)
    reason_note: str | None = Field(default=None, max_length=200)


class RaiseRestockRequestRequest(BaseModel):
    model_config = ConfigDict(strict=True)

    item_id: LaxUUID
    # Optional — "just flag it low" (manager's judgment on how much) is
    # a legitimate request with no specific number, see models.py's
    # InventoryRestockRequest docstring.
    requested_quantity: LaxDecimal | None = Field(default=None, gt=0)
    note: str | None = Field(default=None, max_length=200)


class FulfillRestockRequestRequest(BaseModel):
    model_config = ConfigDict(strict=True)

    transfer_quantity: LaxDecimal = Field(gt=0)
    transferred_on: date_type = Field(strict=False)


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


class InventoryTransferOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    item_id: UUID
    quantity: Decimal
    transferred_on: date_type
    created_by: UUID | None
    created_at: datetime

    @classmethod
    def from_transfer(cls, transfer: InventoryTransfer) -> "InventoryTransferOut":
        return cls(
            id=transfer.id,
            item_id=transfer.item_id,
            quantity=transfer.quantity,
            transferred_on=transfer.transferred_on,
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

    @classmethod
    def from_entry(cls, entry: InventoryUsageEntry) -> "InventoryUsageEntryOut":
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
        )


class InventoryRestockRequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    item_id: UUID
    requested_quantity: Decimal | None
    note: str | None
    status: InventoryRestockRequestStatus
    fulfilled_by_transfer_id: UUID | None
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

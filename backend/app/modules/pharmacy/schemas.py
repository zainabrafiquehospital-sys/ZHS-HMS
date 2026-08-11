"""Pydantic request/response schemas for the Pharmacy / Medicine Billing
module — mirrors app/modules/billing/schemas.py's shape and conventions
exactly (LaxUUID/LaxDecimal for strict-mode request bodies,
`from_attributes` + a `from_x` classmethod for responses)."""

from datetime import datetime
from decimal import Decimal
from enum import Enum as PyEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.pharmacy.models import (
    Medicine,
    MedicineBill,
    MedicineBillItem,
    MedicineCategory,
)
from app.shared.schema_types import LaxDecimal, LaxUUID


class MedicineSortField(str, PyEnum):
    CREATED_AT = "created_at"
    NAME = "name"


# ---------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------


class CreateMedicineRequest(BaseModel):
    model_config = ConfigDict(strict=True)

    name: str = Field(min_length=1, max_length=150)
    category: MedicineCategory = Field(strict=False)
    unit_price: LaxDecimal = Field(gt=0)


class UpdateMedicineRequest(BaseModel):
    """All fields optional for PATCH-style partial update — see
    app/modules/auth/permission_schemas.py's `UpdatePermissionRequest`
    docstring for the identical `exclude_unset` semantics
    `PharmacyService` relies on."""

    model_config = ConfigDict(strict=True)

    name: str | None = Field(default=None, min_length=1, max_length=150)
    category: MedicineCategory | None = Field(default=None, strict=False)
    unit_price: LaxDecimal | None = Field(default=None, gt=0)
    is_active: bool | None = None


class MedicineBillLineItemRequest(BaseModel):
    model_config = ConfigDict(strict=True)

    medicine_id: LaxUUID
    quantity: int = Field(gt=0, le=1000)


class CreateMedicineBillRequest(BaseModel):
    model_config = ConfigDict(strict=True)

    visit_id: LaxUUID | None = None
    items: list[MedicineBillLineItemRequest] = Field(min_length=1)


# ---------------------------------------------------------------------
# Responses
# ---------------------------------------------------------------------


class MedicineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    category: MedicineCategory
    unit_price: Decimal
    is_active: bool
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_medicine(cls, medicine: Medicine) -> "MedicineOut":
        return cls(
            id=medicine.id,
            name=medicine.name,
            category=medicine.category,
            unit_price=medicine.unit_price,
            is_active=medicine.is_active,
            created_at=medicine.created_at,
            updated_at=medicine.updated_at,
        )


class MedicineBillItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    medicine_id: UUID
    medicine_name_snapshot: str
    category_snapshot: MedicineCategory
    unit_price_snapshot: Decimal
    quantity: int
    line_total: Decimal

    @classmethod
    def from_item(cls, item: MedicineBillItem) -> "MedicineBillItemOut":
        return cls(
            id=item.id,
            medicine_id=item.medicine_id,
            medicine_name_snapshot=item.medicine_name_snapshot,
            category_snapshot=item.category_snapshot,
            unit_price_snapshot=item.unit_price_snapshot,
            quantity=item.quantity,
            line_total=item.line_total,
        )


class MedicineBillOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    visit_id: UUID | None
    total_amount: Decimal
    created_by: UUID | None
    created_at: datetime
    items: list[MedicineBillItemOut] = Field(default_factory=list)

    @classmethod
    def from_bill(
        cls, bill: MedicineBill, items: list[MedicineBillItem] | None = None
    ) -> "MedicineBillOut":
        return cls(
            id=bill.id,
            visit_id=bill.visit_id,
            total_amount=bill.total_amount,
            created_by=bill.created_by,
            created_at=bill.created_at,
            items=[MedicineBillItemOut.from_item(item) for item in (items or [])],
        )


class MedicineBillSummaryOut(BaseModel):
    """The Admin Overview Medicine Bills tab's row shape — `total_amount`
    plus `item_count` (not the full item list, to keep `GET
    /pharmacy/bills?date=` a single query rather than N+1 line-item
    fetches; see repository.py's `count_items_for_bills`)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    visit_id: UUID | None
    total_amount: Decimal
    created_by: UUID | None
    created_at: datetime
    item_count: int

    @classmethod
    def from_bill(cls, bill: MedicineBill, item_count: int) -> "MedicineBillSummaryOut":
        return cls(
            id=bill.id,
            visit_id=bill.visit_id,
            total_amount=bill.total_amount,
            created_by=bill.created_by,
            created_at=bill.created_at,
            item_count=item_count,
        )

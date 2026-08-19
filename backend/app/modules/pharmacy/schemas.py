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
    MedicineBillPayment,
    MedicineBillStatus,
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
    # Optional payment recorded atomically alongside creation — the
    # "Advance Received" field on Pharmacy's single merged counter
    # form (see PharmacyService.create_bill's docstring). Validated
    # against the remaining balance server-side same as any other
    # payment; schema only enforces >= 0 here.
    initial_payment_amount: LaxDecimal = Field(default=Decimal("0"), ge=0)
    # Purely display information for the printed slip when no
    # visit_id is linked — see PharmacyService.create_bill's docstring.
    # Same per-field shape as app/modules/patients/schemas.py's
    # CreatePatientRequest (full_name/age_years/phone_number); whether
    # these are required together, and mutually exclusive with
    # visit_id, is a cross-field business rule left to the service
    # (same convention every other request here already follows).
    manual_patient_name: str | None = Field(default=None, min_length=1, max_length=150)
    manual_patient_age: int | None = Field(default=None, ge=0, le=150)
    manual_patient_phone: str | None = Field(default=None, min_length=6, max_length=20)
    # Optional flat discount, applied at creation time only (2026-08-19
    # addition) — same shape as app/modules/billing/schemas.py's
    # GenerateInvoiceRequest.discount_amount/discount_reason, except
    # discount_reason here is always optional (a deliberate product
    # decision for this feature; see PharmacyService.create_bill's
    # docstring — there is no cross-field "reason required" rule to
    # enforce, unlike Invoice's discount).
    discount_amount: LaxDecimal = Field(default=Decimal("0"), ge=0)
    discount_reason: str | None = Field(default=None, max_length=200)


class RecordMedicineBillPaymentRequest(BaseModel):
    model_config = ConfigDict(strict=True)

    amount: LaxDecimal = Field(gt=0)


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


class MedicineBillPaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    amount: Decimal
    created_by: UUID | None
    created_at: datetime

    @classmethod
    def from_payment(cls, payment: MedicineBillPayment) -> "MedicineBillPaymentOut":
        return cls(
            id=payment.id,
            amount=payment.amount,
            created_by=payment.created_by,
            created_at=payment.created_at,
        )


class MedicineBillOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    visit_id: UUID | None
    total_amount: Decimal
    amount_paid: Decimal
    status: MedicineBillStatus
    paid_at: datetime | None
    created_by: UUID | None
    created_at: datetime
    manual_patient_name: str | None
    manual_patient_age: int | None
    manual_patient_phone: str | None
    discount_amount: Decimal
    discount_reason: str | None
    items: list[MedicineBillItemOut] = Field(default_factory=list)
    payments: list[MedicineBillPaymentOut] = Field(default_factory=list)

    @classmethod
    def from_bill(
        cls,
        bill: MedicineBill,
        items: list[MedicineBillItem] | None = None,
        payments: list[MedicineBillPayment] | None = None,
    ) -> "MedicineBillOut":
        return cls(
            id=bill.id,
            visit_id=bill.visit_id,
            total_amount=bill.total_amount,
            amount_paid=bill.amount_paid,
            status=bill.status,
            paid_at=bill.paid_at,
            created_by=bill.created_by,
            created_at=bill.created_at,
            manual_patient_name=bill.manual_patient_name,
            manual_patient_age=bill.manual_patient_age,
            manual_patient_phone=bill.manual_patient_phone,
            discount_amount=bill.discount_amount,
            discount_reason=bill.discount_reason,
            items=[MedicineBillItemOut.from_item(item) for item in (items or [])],
            payments=[MedicineBillPaymentOut.from_payment(p) for p in (payments or [])],
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
    amount_paid: Decimal
    status: MedicineBillStatus
    created_by: UUID | None
    created_at: datetime
    item_count: int
    # Only the name, not age/phone — the Medicine Bills tab's "Patient"
    # column shows a linked visit's patient name the same minimal way
    # (see MedicineBillOut for the full manual-entry field set, used by
    # the print slip instead).
    manual_patient_name: str | None
    # 2026-08-19 addition — lets a summary row (both Admin's day view
    # and a receptionist's own "My Medicine Bills" list, see
    # PharmacyService.list_bills_for_creator) show whether a discount
    # was applied without a second fetch of the full MedicineBillOut.
    discount_amount: Decimal

    @classmethod
    def from_bill(cls, bill: MedicineBill, item_count: int) -> "MedicineBillSummaryOut":
        return cls(
            id=bill.id,
            visit_id=bill.visit_id,
            total_amount=bill.total_amount,
            amount_paid=bill.amount_paid,
            status=bill.status,
            created_by=bill.created_by,
            created_at=bill.created_at,
            item_count=item_count,
            manual_patient_name=bill.manual_patient_name,
            discount_amount=bill.discount_amount,
        )


class MedicineBillCreatorStatOut(BaseModel):
    """One row of `GET /pharmacy/bills/stats/by-creator`'s response —
    one user's "medicine bills created" count and "revenue billed" sum
    (of `total_amount`, not `amount_paid` — see repository.py's
    `count_and_revenue_by_creator` docstring). Not an ORM-backed schema,
    same plain-aggregate shape as
    app/modules/visits/schemas.py's `VisitCreatorStatOut`. Powers the
    Admin "Employee Accounts & Stats" page."""

    model_config = ConfigDict(strict=True)

    user_id: UUID
    count: int
    revenue: Decimal

"""Pydantic request/response schemas for the Laboratory Billing module
— mirrors app/modules/pharmacy/schemas.py's shape and conventions
exactly (LaxUUID/LaxDecimal for strict-mode request bodies,
`from_attributes` + a `from_x` classmethod for responses)."""

from datetime import datetime
from decimal import Decimal
from enum import Enum as PyEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.lab.models import (
    LabBill,
    LabBillItem,
    LabBillPayment,
    LabBillStatus,
    LabTest,
    LabTestCategory,
)
from app.shared.payment_method import PaymentMethod
from app.shared.schema_types import LaxDecimal, LaxUUID


class LabTestSortField(str, PyEnum):
    CREATED_AT = "created_at"
    NAME = "name"


# ---------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------


class CreateLabTestRequest(BaseModel):
    model_config = ConfigDict(strict=True)

    name: str = Field(min_length=1, max_length=150)
    category: LabTestCategory = Field(strict=False)
    price: LaxDecimal = Field(gt=0)


class UpdateLabTestRequest(BaseModel):
    """All fields optional for PATCH-style partial update — see
    app/modules/pharmacy/schemas.py's `UpdateMedicineRequest` docstring
    for the identical `exclude_unset` semantics `LabService` relies
    on."""

    model_config = ConfigDict(strict=True)

    name: str | None = Field(default=None, min_length=1, max_length=150)
    category: LabTestCategory | None = Field(default=None, strict=False)
    price: LaxDecimal | None = Field(default=None, gt=0)
    is_active: bool | None = None


class CreateLabBillRequest(BaseModel):
    """`items` is a plain list of `lab_test_id`s — no per-line quantity
    (confirmed design, see models.py's `LabBillItem` docstring); the
    same test id appearing twice simply becomes two independent lines."""

    model_config = ConfigDict(strict=True)

    patient_id: LaxUUID | None = None
    items: list[LaxUUID] = Field(min_length=1)
    # Optional payment recorded atomically alongside creation — the
    # same "Advance Received" shape Pharmacy's own merged counter form
    # uses (see LabService.create_bill's docstring). `initial_payment_
    # method` is required whenever `initial_payment_amount > 0` — a
    # cross-field rule left to the service.
    initial_payment_amount: LaxDecimal = Field(default=Decimal("0"), ge=0)
    initial_payment_method: PaymentMethod | None = Field(default=None, strict=False)
    # Purely display information for the printed slip when no
    # patient_id is linked — see LabService.create_bill's docstring.
    manual_patient_name: str | None = Field(default=None, min_length=1, max_length=150)
    manual_patient_age: int | None = Field(default=None, ge=0, le=150)
    manual_patient_phone: str | None = Field(default=None, min_length=6, max_length=20)
    # Optional flat discount, applied at creation time only — same
    # shape as app/modules/pharmacy/schemas.py's identical
    # CreateMedicineBillRequest.discount_amount/discount_reason.
    discount_amount: LaxDecimal = Field(default=Decimal("0"), ge=0)
    discount_reason: str | None = Field(default=None, max_length=200)


class RecordLabBillPaymentRequest(BaseModel):
    model_config = ConfigDict(strict=True)

    amount: LaxDecimal = Field(gt=0)
    payment_method: PaymentMethod = Field(strict=False)


class AdminUpdateLabBillRequest(BaseModel):
    """Admin-only "Edit Bill" — corrects a mistakenly-entered lab
    bill's manual patient details and/or its discount, in one call (see
    LabService.admin_update_bill's docstring). Every field optional/
    PATCH-style (`exclude_unset`), same convention as app/modules/
    pharmacy/schemas.py's `AdminUpdateMedicineBillRequest`.

    `manual_patient_name`/`_age`/`_phone` are only meaningful — and
    only accepted by the service — when the target bill has no linked
    `patient_id`. `discount_amount`/`discount_reason` are always
    eligible regardless of `patient_id`, but the whole update is
    blocked outright once the bill has any recorded payment."""

    model_config = ConfigDict(strict=True)

    manual_patient_name: str | None = Field(default=None, min_length=1, max_length=150)
    manual_patient_age: int | None = Field(default=None, ge=0, le=150)
    manual_patient_phone: str | None = Field(default=None, min_length=6, max_length=20)
    discount_amount: LaxDecimal | None = Field(default=None, ge=0)
    discount_reason: str | None = Field(default=None, max_length=200)


# ---------------------------------------------------------------------
# Responses
# ---------------------------------------------------------------------


class LabTestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    category: LabTestCategory
    price: Decimal
    is_active: bool
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_test(cls, test: LabTest) -> "LabTestOut":
        return cls(
            id=test.id,
            name=test.name,
            category=test.category,
            price=test.price,
            is_active=test.is_active,
            created_at=test.created_at,
            updated_at=test.updated_at,
        )


class LabBillItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    lab_test_id: UUID
    lab_test_name_snapshot: str
    category_snapshot: LabTestCategory
    unit_price_snapshot: Decimal

    @classmethod
    def from_item(cls, item: LabBillItem) -> "LabBillItemOut":
        return cls(
            id=item.id,
            lab_test_id=item.lab_test_id,
            lab_test_name_snapshot=item.lab_test_name_snapshot,
            category_snapshot=item.category_snapshot,
            unit_price_snapshot=item.unit_price_snapshot,
        )


class LabBillPaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    amount: Decimal
    payment_method: PaymentMethod
    created_by: UUID | None
    created_at: datetime

    @classmethod
    def from_payment(cls, payment: LabBillPayment) -> "LabBillPaymentOut":
        return cls(
            id=payment.id,
            amount=payment.amount,
            payment_method=payment.payment_method,
            created_by=payment.created_by,
            created_at=payment.created_at,
        )


class LabBillOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    patient_id: UUID | None
    queue_token: str | None
    total_amount: Decimal
    amount_paid: Decimal
    status: LabBillStatus
    paid_at: datetime | None
    created_by: UUID | None
    created_at: datetime
    manual_patient_name: str | None
    manual_patient_age: int | None
    manual_patient_phone: str | None
    discount_amount: Decimal
    discount_reason: str | None
    items: list[LabBillItemOut] = Field(default_factory=list)
    payments: list[LabBillPaymentOut] = Field(default_factory=list)

    @classmethod
    def from_bill(
        cls,
        bill: LabBill,
        items: list[LabBillItem] | None = None,
        payments: list[LabBillPayment] | None = None,
    ) -> "LabBillOut":
        return cls(
            id=bill.id,
            patient_id=bill.patient_id,
            queue_token=bill.queue_token,
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
            items=[LabBillItemOut.from_item(item) for item in (items or [])],
            payments=[LabBillPaymentOut.from_payment(p) for p in (payments or [])],
        )


class LabBillSummaryOut(BaseModel):
    """The Admin Overview Lab Bills tab's row shape — `total_amount`
    plus `item_count` (not the full item list), identical shape to
    app/modules/pharmacy/schemas.py's `MedicineBillSummaryOut`."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    patient_id: UUID | None
    total_amount: Decimal
    amount_paid: Decimal
    status: LabBillStatus
    created_by: UUID | None
    created_at: datetime
    item_count: int
    manual_patient_name: str | None
    discount_amount: Decimal
    payment_methods: list[str]

    @classmethod
    def from_bill(
        cls, bill: LabBill, item_count: int, payment_methods: list[str] | None = None
    ) -> "LabBillSummaryOut":
        return cls(
            id=bill.id,
            patient_id=bill.patient_id,
            total_amount=bill.total_amount,
            amount_paid=bill.amount_paid,
            status=bill.status,
            created_by=bill.created_by,
            created_at=bill.created_at,
            item_count=item_count,
            manual_patient_name=bill.manual_patient_name,
            discount_amount=bill.discount_amount,
            payment_methods=payment_methods or [],
        )


class LabBillCreatorStatOut(BaseModel):
    """One row of `GET /lab/bills/stats/by-creator`'s response — one
    user's "lab bills created" count and "revenue billed" sum (of
    `total_amount`, not `amount_paid`). Not an ORM-backed schema, same
    plain-aggregate shape as app/modules/pharmacy/schemas.py's
    `MedicineBillCreatorStatOut`. Powers the Admin "Employee Accounts &
    Stats" page."""

    model_config = ConfigDict(strict=True)

    user_id: UUID
    count: int
    revenue: Decimal

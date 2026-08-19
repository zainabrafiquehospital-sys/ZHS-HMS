"""Pydantic request/response schemas for the Billing module."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.billing.models import (
    Invoice,
    InvoiceLineItem,
    InvoicePayment,
    InvoiceStatus,
    PendingBillingItem,
    PendingBillingItemStatus,
)
from app.shared.payment_method import PaymentMethod
from app.shared.schema_types import LaxDecimal, LaxUUID


class SubmitPendingItemRequest(BaseModel):
    model_config = ConfigDict(strict=True)

    visit_id: LaxUUID
    description: str = Field(min_length=1, max_length=200)
    amount: LaxDecimal = Field(gt=0)


class GenerateInvoiceRequest(BaseModel):
    model_config = ConfigDict(strict=True)

    visit_id: LaxUUID
    base_description: str = Field(min_length=1, max_length=200)
    base_amount: LaxDecimal = Field(gt=0)
    # Optional flat discount applied at generation time only — see
    # BillingService.generate_invoice's docstring. Whether a non-zero
    # discount requires discount_reason is a cross-field business rule,
    # left to the service (same "schema only enforces per-field shape"
    # convention every other request here already follows).
    discount_amount: LaxDecimal = Field(default=Decimal("0"), ge=0)
    discount_reason: str | None = Field(default=None, max_length=200)
    # Optional payment recorded atomically alongside generation — the
    # "Advance Received" field on Billing's single merged form (see
    # BillingService.generate_invoice's docstring). Validated against
    # the remaining balance server-side same as any other payment;
    # schema only enforces >= 0 here. `initial_payment_method`
    # (2026-08-19 addition) is required whenever `initial_payment_amount
    # > 0` — a cross-field rule left to the service, same convention as
    # discount_reason above — and otherwise simply ignored.
    initial_payment_amount: LaxDecimal = Field(default=Decimal("0"), ge=0)
    initial_payment_method: PaymentMethod | None = Field(default=None, strict=False)


class RecordPaymentRequest(BaseModel):
    model_config = ConfigDict(strict=True)

    amount: LaxDecimal = Field(gt=0)
    payment_method: PaymentMethod = Field(strict=False)


class PendingBillingItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    visit_id: UUID
    description: str
    amount: Decimal
    status: PendingBillingItemStatus
    created_at: datetime

    @classmethod
    def from_item(cls, item: PendingBillingItem) -> "PendingBillingItemOut":
        return cls(
            id=item.id,
            visit_id=item.visit_id,
            description=item.description,
            amount=item.amount,
            status=item.status,
            created_at=item.created_at,
        )


class InvoiceLineItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    description: str
    amount: Decimal
    pending_billing_item_id: UUID | None

    @classmethod
    def from_line_item(cls, line_item: InvoiceLineItem) -> "InvoiceLineItemOut":
        return cls(
            id=line_item.id,
            description=line_item.description,
            amount=line_item.amount,
            pending_billing_item_id=line_item.pending_billing_item_id,
        )


class InvoicePaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    amount: Decimal
    payment_method: PaymentMethod
    created_by: UUID | None
    created_at: datetime

    @classmethod
    def from_payment(cls, payment: InvoicePayment) -> "InvoicePaymentOut":
        return cls(
            id=payment.id,
            amount=payment.amount,
            payment_method=payment.payment_method,
            created_by=payment.created_by,
            created_at=payment.created_at,
        )


class InvoiceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    visit_id: UUID
    status: InvoiceStatus
    total_amount: Decimal
    amount_paid: Decimal
    discount_amount: Decimal
    discount_reason: str | None
    paid_at: datetime | None
    created_at: datetime
    line_items: list[InvoiceLineItemOut] = Field(default_factory=list)
    payments: list[InvoicePaymentOut] = Field(default_factory=list)

    @classmethod
    def from_invoice(
        cls,
        invoice: Invoice,
        line_items: list[InvoiceLineItem] | None = None,
        payments: list[InvoicePayment] | None = None,
    ) -> "InvoiceOut":
        return cls(
            id=invoice.id,
            visit_id=invoice.visit_id,
            status=invoice.status,
            total_amount=invoice.total_amount,
            amount_paid=invoice.amount_paid,
            discount_amount=invoice.discount_amount,
            discount_reason=invoice.discount_reason,
            paid_at=invoice.paid_at,
            created_at=invoice.created_at,
            line_items=[InvoiceLineItemOut.from_line_item(li) for li in (line_items or [])],
            payments=[InvoicePaymentOut.from_payment(p) for p in (payments or [])],
        )

"""Pydantic request/response schemas for the Billing module."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.billing.models import (
    Invoice,
    InvoiceLineItem,
    InvoiceStatus,
    PendingBillingItem,
    PendingBillingItemStatus,
)
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


class RecordPaymentRequest(BaseModel):
    model_config = ConfigDict(strict=True)

    amount: LaxDecimal = Field(gt=0)


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


class InvoiceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    visit_id: UUID
    status: InvoiceStatus
    total_amount: Decimal
    amount_paid: Decimal
    paid_at: datetime | None
    created_at: datetime
    line_items: list[InvoiceLineItemOut] = Field(default_factory=list)

    @classmethod
    def from_invoice(
        cls, invoice: Invoice, line_items: list[InvoiceLineItem] | None = None
    ) -> "InvoiceOut":
        return cls(
            id=invoice.id,
            visit_id=invoice.visit_id,
            status=invoice.status,
            total_amount=invoice.total_amount,
            amount_paid=invoice.amount_paid,
            paid_at=invoice.paid_at,
            created_at=invoice.created_at,
            line_items=[InvoiceLineItemOut.from_line_item(li) for li in (line_items or [])],
        )

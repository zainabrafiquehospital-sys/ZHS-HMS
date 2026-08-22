"""HTTP endpoints for the Billing module. Every mutating endpoint here
requires either `billing:submit_charge` (doctor-side, submit only) or
`billing:manage` (Reception-side, everything else) — see constants.py's
module docstring for the segregation-of-duties rationale."""

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse

from app.core.config import Settings, get_settings
from app.modules.auth.dependencies import require_permission
from app.modules.auth.models import User
from app.modules.billing.constants import (
    PERMISSION_BILLING_MANAGE,
    PERMISSION_BILLING_READ,
    PERMISSION_BILLING_SUBMIT_CHARGE,
)
from app.modules.billing.dependencies import get_billing_service
from app.modules.billing.models import PendingBillingItemStatus
from app.modules.billing.schemas import (
    GenerateInvoiceRequest,
    InvoiceOut,
    PendingBillingItemOut,
    RecordPaymentRequest,
    SubmitPendingItemRequest,
)
from app.modules.billing.service import BillingService
from app.modules.patients.dependencies import get_patient_service
from app.modules.patients.service import PatientService
from app.modules.visits.dependencies import get_visit_service
from app.modules.visits.schemas import RecordVisitPaymentRequest, VisitOut
from app.modules.visits.service import VisitService
from app.shared.envelope import success_envelope
from app.shared.printing.service import render_invoice_receipt

router = APIRouter(prefix="/billing", tags=["billing"])


@router.post("/pending-items", status_code=201)
async def submit_pending_item(
    payload: SubmitPendingItemRequest,
    billing_service: BillingService = Depends(get_billing_service),
    actor: User = Depends(require_permission(PERMISSION_BILLING_SUBMIT_CHARGE)),
) -> dict:
    item = await billing_service.submit_pending_item(
        actor=actor,
        visit_id=payload.visit_id,
        description=payload.description,
        amount=payload.amount,
    )
    return success_envelope(PendingBillingItemOut.from_item(item).model_dump(mode="json"))


@router.get("/visits/{visit_id}/pending-items")
async def list_pending_items(
    visit_id: UUID,
    status: PendingBillingItemStatus | None = Query(default=None),
    billing_service: BillingService = Depends(get_billing_service),
    _actor: User = Depends(require_permission(PERMISSION_BILLING_READ)),
) -> dict:
    items = await billing_service.list_pending_items(visit_id, status=status)
    body = [PendingBillingItemOut.from_item(item).model_dump(mode="json") for item in items]
    return success_envelope(body)


@router.post("/pending-items/{item_id}/approve")
async def approve_pending_item(
    item_id: UUID,
    billing_service: BillingService = Depends(get_billing_service),
    actor: User = Depends(require_permission(PERMISSION_BILLING_MANAGE)),
) -> dict:
    item = await billing_service.approve_pending_item(actor=actor, item_id=item_id)
    return success_envelope(PendingBillingItemOut.from_item(item).model_dump(mode="json"))


@router.post("/pending-items/{item_id}/reject")
async def reject_pending_item(
    item_id: UUID,
    billing_service: BillingService = Depends(get_billing_service),
    actor: User = Depends(require_permission(PERMISSION_BILLING_MANAGE)),
) -> dict:
    item = await billing_service.reject_pending_item(actor=actor, item_id=item_id)
    return success_envelope(PendingBillingItemOut.from_item(item).model_dump(mode="json"))


@router.post("/invoices", status_code=201)
async def generate_invoice(
    payload: GenerateInvoiceRequest,
    billing_service: BillingService = Depends(get_billing_service),
    actor: User = Depends(require_permission(PERMISSION_BILLING_MANAGE)),
) -> dict:
    invoice = await billing_service.generate_invoice(
        actor=actor,
        visit_id=payload.visit_id,
        base_description=payload.base_description,
        base_amount=payload.base_amount,
        discount_amount=payload.discount_amount,
        discount_reason=payload.discount_reason,
        initial_payment_amount=payload.initial_payment_amount,
        initial_payment_method=payload.initial_payment_method,
    )
    line_items = await billing_service.get_line_items(invoice.id)
    payments = await billing_service.get_payments(invoice.id)
    return success_envelope(
        InvoiceOut.from_invoice(invoice, line_items, payments).model_dump(mode="json")
    )


@router.get("/invoices/{invoice_id}")
async def get_invoice(
    invoice_id: UUID,
    billing_service: BillingService = Depends(get_billing_service),
    _actor: User = Depends(require_permission(PERMISSION_BILLING_READ)),
) -> dict:
    invoice = await billing_service.get_invoice(invoice_id)
    line_items = await billing_service.get_line_items(invoice.id)
    payments = await billing_service.get_payments(invoice.id)
    return success_envelope(
        InvoiceOut.from_invoice(invoice, line_items, payments).model_dump(mode="json")
    )


@router.get("/visits/{visit_id}/invoices")
async def list_invoices_for_visit(
    visit_id: UUID,
    billing_service: BillingService = Depends(get_billing_service),
    _actor: User = Depends(require_permission(PERMISSION_BILLING_READ)),
) -> dict:
    invoices = await billing_service.list_invoices_for_visit(visit_id)
    body = [InvoiceOut.from_invoice(invoice).model_dump(mode="json") for invoice in invoices]
    return success_envelope(body)


@router.post("/invoices/{invoice_id}/pay")
async def record_payment(
    invoice_id: UUID,
    payload: RecordPaymentRequest,
    billing_service: BillingService = Depends(get_billing_service),
    actor: User = Depends(require_permission(PERMISSION_BILLING_MANAGE)),
) -> dict:
    invoice = await billing_service.record_payment(
        actor=actor,
        invoice_id=invoice_id,
        amount=payload.amount,
        payment_method=payload.payment_method,
    )
    line_items = await billing_service.get_line_items(invoice.id)
    payments = await billing_service.get_payments(invoice.id)
    return success_envelope(
        InvoiceOut.from_invoice(invoice, line_items, payments).model_dump(mode="json")
    )


@router.post("/visits/{visit_id}/payments")
async def record_visit_payment(
    visit_id: UUID,
    payload: RecordVisitPaymentRequest,
    billing_service: BillingService = Depends(get_billing_service),
    visit_service: VisitService = Depends(get_visit_service),
    actor: User = Depends(require_permission(PERMISSION_BILLING_MANAGE)),
) -> dict:
    """Tops up a Visit's own registration-charge payment (2026-08-22
    addition) — a ledger entirely independent of the Invoice endpoints
    above (see VisitService.record_payment's own docstring). Gated on
    `billing:manage` like every other mutating action on this screen,
    not on a Reception permission, even though the underlying write
    happens through `VisitService` — the Billing screen's top-up panel
    is where this action's UI lives."""
    visit = await billing_service.record_visit_payment(
        actor=actor,
        visit_id=visit_id,
        amount=payload.amount,
        payment_method=payload.payment_method,
    )
    procedure_items = await visit_service.list_procedure_items(visit.id)
    payments = await visit_service.list_payments(visit.id)
    return success_envelope(
        VisitOut.from_visit(visit, procedure_items, payments).model_dump(mode="json")
    )


@router.get("/invoices/{invoice_id}/print", response_class=HTMLResponse)
async def print_invoice(
    invoice_id: UUID,
    billing_service: BillingService = Depends(get_billing_service),
    patient_service: PatientService = Depends(get_patient_service),
    visit_service: VisitService = Depends(get_visit_service),
    settings: Settings = Depends(get_settings),
    _actor: User = Depends(require_permission(PERMISSION_BILLING_READ)),
) -> HTMLResponse:
    """Billing decides *whether* this invoice may be printed (the same
    `billing:read` gate as viewing it) and supplies the data — the
    Central Print Service (app/shared/printing/service.py) only ever
    renders it (Phase 6 §14)."""
    invoice = await billing_service.get_invoice(invoice_id)
    line_items = await billing_service.get_line_items(invoice.id)
    payments = await billing_service.get_payments(invoice.id)
    visit = await visit_service.get_visit(invoice.visit_id)
    patient = await patient_service.get_patient(visit.patient_id)

    html_document = render_invoice_receipt(
        hospital_name=settings.app_name,
        patient_full_name=patient.full_name,
        patient_mr_number=patient.mr_number,
        visit_queue_token=visit.queue_token,
        visit_procedure=visit.procedure,
        invoice_id=str(invoice.id),
        invoice_status=invoice.status.value,
        invoice_created_at=invoice.created_at,
        line_items=[(item.description, item.amount) for item in line_items],
        # Distinct payment methods used, in first-payment order — see
        # render_invoice_receipt's own docstring for why this is a
        # summary line, not a full itemized payment breakdown.
        payment_methods=list(dict.fromkeys(payment.payment_method.value for payment in payments)),
        total_amount=invoice.total_amount,
        amount_paid=invoice.amount_paid,
        discount_amount=invoice.discount_amount,
        discount_reason=invoice.discount_reason,
    )
    return HTMLResponse(content=html_document)

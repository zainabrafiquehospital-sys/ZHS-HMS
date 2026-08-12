"""FastAPI dependency-injection providers for the Billing module — see
app/modules/reception/dependencies.py's identical composition pattern."""

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.modules.billing.repository import (
    InvoiceLineItemRepository,
    InvoicePaymentRepository,
    InvoiceRepository,
    PendingBillingItemRepository,
)
from app.modules.billing.service import BillingService
from app.modules.visits.dependencies import get_visit_service
from app.modules.visits.service import VisitService
from app.shared.audit.dependencies import get_audit_log_repository
from app.shared.audit.repository import AuditLogRepository


def get_pending_billing_item_repository(
    db: AsyncSession = Depends(get_db),
) -> PendingBillingItemRepository:
    return PendingBillingItemRepository(db)


def get_invoice_repository(db: AsyncSession = Depends(get_db)) -> InvoiceRepository:
    return InvoiceRepository(db)


def get_invoice_line_item_repository(
    db: AsyncSession = Depends(get_db),
) -> InvoiceLineItemRepository:
    return InvoiceLineItemRepository(db)


def get_invoice_payment_repository(
    db: AsyncSession = Depends(get_db),
) -> InvoicePaymentRepository:
    return InvoicePaymentRepository(db)


def get_billing_service(
    db: AsyncSession = Depends(get_db),
    pending_billing_item_repository: PendingBillingItemRepository = Depends(
        get_pending_billing_item_repository
    ),
    invoice_repository: InvoiceRepository = Depends(get_invoice_repository),
    invoice_line_item_repository: InvoiceLineItemRepository = Depends(
        get_invoice_line_item_repository
    ),
    invoice_payment_repository: InvoicePaymentRepository = Depends(get_invoice_payment_repository),
    visit_service: VisitService = Depends(get_visit_service),
    audit_repository: AuditLogRepository = Depends(get_audit_log_repository),
) -> BillingService:
    return BillingService(
        session=db,
        pending_billing_item_repository=pending_billing_item_repository,
        invoice_repository=invoice_repository,
        invoice_line_item_repository=invoice_line_item_repository,
        invoice_payment_repository=invoice_payment_repository,
        visit_service=visit_service,
        audit_repository=audit_repository,
    )

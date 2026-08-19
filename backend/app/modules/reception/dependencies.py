"""FastAPI dependency-injection providers for the Reception module.
Composes the already-existing Patient/Visit/Queue service providers
rather than rebuilding their repository graphs here — each `Depends(...)`
resolves to the exact same request-scoped instances those modules'
own endpoints would receive, all sharing the one request-scoped
`AsyncSession` from `Depends(get_db)` (FastAPI's dependency cache
guarantees a single call to `get_db` per request, so every service
built from it operates on the same session/transaction scope)."""

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.modules.billing.dependencies import get_invoice_repository
from app.modules.billing.repository import InvoiceRepository
from app.modules.patients.dependencies import get_patient_service
from app.modules.patients.service import PatientService
from app.modules.queue.dependencies import get_queue_service
from app.modules.queue.service import QueueService
from app.modules.reception.repository import ReceptionRepository
from app.modules.reception.service import ReceptionService
from app.modules.visits.dependencies import get_visit_service
from app.modules.visits.service import VisitService
from app.shared.audit.dependencies import get_audit_log_repository
from app.shared.audit.repository import AuditLogRepository


def get_reception_repository(db: AsyncSession = Depends(get_db)) -> ReceptionRepository:
    return ReceptionRepository(session=db)


def get_reception_service(
    db: AsyncSession = Depends(get_db),
    patient_service: PatientService = Depends(get_patient_service),
    visit_service: VisitService = Depends(get_visit_service),
    queue_service: QueueService = Depends(get_queue_service),
    audit_repository: AuditLogRepository = Depends(get_audit_log_repository),
    reception_repository: ReceptionRepository = Depends(get_reception_repository),
    # 2026-08-19 addition — see ReceptionService.__init__'s own docstring
    # for why this one read-only Billing dependency is here at all.
    # Reused directly from billing/dependencies.py rather than
    # re-declared, the same "compose the already-existing provider"
    # convention this file's own module docstring already states.
    invoice_repository: InvoiceRepository = Depends(get_invoice_repository),
) -> ReceptionService:
    return ReceptionService(
        session=db,
        patient_service=patient_service,
        visit_service=visit_service,
        queue_service=queue_service,
        audit_repository=audit_repository,
        reception_repository=reception_repository,
        invoice_repository=invoice_repository,
    )

"""FastAPI dependency-injection providers for the Reception module.
Composes the already-existing Patient/Visit/Queue service providers
rather than rebuilding their repository graphs here — each `Depends(...)`
resolves to the exact same request-scoped instances those modules'
own endpoints would receive, all sharing the one request-scoped
`AsyncSession` from `Depends(get_db)` (FastAPI's dependency cache
guarantees a single call to `get_db` per request, so every service
built from it operates on the same session/transaction scope).

`require_any_permission` (2026-08-25, originally defined here) was
promoted to app/modules/auth/dependencies.py in 2026-09 once Inventory
needed the identical "either the broad permission or a narrower
alternative" gate (`POST /inventory/items` accepts `inventory:manage`
OR `inventory:create_item`) — one shared definition alongside
`require_permission`, rather than a second module reaching into this
one for it. `reception/router.py` now imports it from there directly."""

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.modules.billing.dependencies import get_invoice_repository
from app.modules.billing.repository import InvoiceRepository
from app.modules.lab.dependencies import get_lab_bill_repository
from app.modules.lab.repository import LabBillRepository
from app.modules.patients.dependencies import get_patient_service
from app.modules.patients.service import PatientService
from app.modules.pharmacy.dependencies import get_medicine_bill_repository
from app.modules.pharmacy.repository import MedicineBillRepository
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
    # 2026-08-19 addition, same shape/rationale as invoice_repository
    # above — reused directly from pharmacy/dependencies.py.
    medicine_bill_repository: MedicineBillRepository = Depends(get_medicine_bill_repository),
    # Step 4 addition, same shape/rationale as medicine_bill_repository
    # above — reused directly from lab/dependencies.py, backs the "Lab"
    # third of get_own_revenue's now-3-way breakdown.
    lab_bill_repository: LabBillRepository = Depends(get_lab_bill_repository),
) -> ReceptionService:
    return ReceptionService(
        session=db,
        patient_service=patient_service,
        visit_service=visit_service,
        queue_service=queue_service,
        audit_repository=audit_repository,
        reception_repository=reception_repository,
        invoice_repository=invoice_repository,
        medicine_bill_repository=medicine_bill_repository,
        lab_bill_repository=lab_bill_repository,
    )

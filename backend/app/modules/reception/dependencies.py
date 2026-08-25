"""FastAPI dependency-injection providers for the Reception module.
Composes the already-existing Patient/Visit/Queue service providers
rather than rebuilding their repository graphs here — each `Depends(...)`
resolves to the exact same request-scoped instances those modules'
own endpoints would receive, all sharing the one request-scoped
`AsyncSession` from `Depends(get_db)` (FastAPI's dependency cache
guarantees a single call to `get_db` per request, so every service
built from it operates on the same session/transaction scope).

`require_any_permission` (2026-08-25 addition) lives here rather than
in app/modules/auth/dependencies.py, which is frozen Phase 5 code not
modified for anything short of a genuine defect (see that module's own
docstring) — adding an "any of these permissions" composition helper
there would be a new capability, not a fix. This is purely a consumer
of AuthService's already-public `effective_permission_codes` — the
identical method `require_permission` itself already calls — never a
modification of Auth's own code, the same "observer of Auth's public
interface" boundary this codebase already established for Attendance
(see that module's own docstring for the precedent). Used by exactly
one endpoint so far: GET /reception/visits/{id}/slip/print, which
needs to accept either the existing PERMISSION_RECEPTION_REGISTER_VISIT
(Reception's own, unchanged access) or the narrower
PERMISSION_RECEPTION_VIEW_SLIP (Doctor's new, read-only access) — see
reception/constants.py's own docstring on that permission."""

from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.core.exceptions import PermissionDeniedError
from app.modules.auth.dependencies import get_auth_service, get_current_active_user
from app.modules.auth.exceptions import PasswordChangeRequiredError
from app.modules.auth.models import User
from app.modules.auth.service import AuthService
from app.modules.billing.dependencies import get_invoice_repository
from app.modules.billing.repository import InvoiceRepository
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


def require_any_permission(*permission_codes: str) -> Callable[..., Coroutine[Any, Any, User]]:
    async def dependency(
        user: User = Depends(get_current_active_user),
        auth_service: AuthService = Depends(get_auth_service),
    ) -> User:
        # Same must_change_password gate as require_permission, checked
        # first for the identical reason — see that dependency's own
        # comment (app/modules/auth/dependencies.py).
        if user.must_change_password:
            raise PasswordChangeRequiredError
        held = auth_service.effective_permission_codes(user)
        if not held.intersection(permission_codes):
            raise PermissionDeniedError(
                f"Missing required permission (any of): {', '.join(permission_codes)}"
            )
        return user

    return dependency


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
    )

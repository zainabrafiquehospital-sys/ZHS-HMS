"""FastAPI dependency-injection providers for the Patient module — the
same pattern app/modules/auth/dependencies.py already establishes:
request-scoped repositories/services built fresh per request from
`Depends(get_db)`, since each carries a request-scoped `AsyncSession`
that must never be shared across concurrent requests."""

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.modules.patients.repository import PatientRepository
from app.modules.patients.service import PatientService
from app.shared.audit.dependencies import get_audit_log_repository
from app.shared.audit.repository import AuditLogRepository


def get_patient_repository(db: AsyncSession = Depends(get_db)) -> PatientRepository:
    return PatientRepository(db)


def get_patient_service(
    db: AsyncSession = Depends(get_db),
    patient_repository: PatientRepository = Depends(get_patient_repository),
    audit_repository: AuditLogRepository = Depends(get_audit_log_repository),
) -> PatientService:
    return PatientService(
        session=db, patient_repository=patient_repository, audit_repository=audit_repository
    )

"""FastAPI dependency-injection providers for the Visit module — see
app/modules/patients/dependencies.py's identical module docstring."""

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.modules.visits.repository import (
    ProcedureRepository,
    VisitPaymentRepository,
    VisitProcedureItemRepository,
    VisitRepository,
)
from app.modules.visits.service import VisitService
from app.shared.audit.dependencies import get_audit_log_repository
from app.shared.audit.repository import AuditLogRepository


def get_visit_repository(db: AsyncSession = Depends(get_db)) -> VisitRepository:
    return VisitRepository(db)


def get_procedure_repository(db: AsyncSession = Depends(get_db)) -> ProcedureRepository:
    return ProcedureRepository(db)


def get_visit_procedure_item_repository(
    db: AsyncSession = Depends(get_db),
) -> VisitProcedureItemRepository:
    return VisitProcedureItemRepository(db)


def get_visit_payment_repository(
    db: AsyncSession = Depends(get_db),
) -> VisitPaymentRepository:
    return VisitPaymentRepository(db)


def get_visit_service(
    db: AsyncSession = Depends(get_db),
    visit_repository: VisitRepository = Depends(get_visit_repository),
    audit_repository: AuditLogRepository = Depends(get_audit_log_repository),
    procedure_repository: ProcedureRepository = Depends(get_procedure_repository),
    procedure_item_repository: VisitProcedureItemRepository = Depends(
        get_visit_procedure_item_repository
    ),
    visit_payment_repository: VisitPaymentRepository = Depends(get_visit_payment_repository),
) -> VisitService:
    return VisitService(
        session=db,
        visit_repository=visit_repository,
        audit_repository=audit_repository,
        procedure_repository=procedure_repository,
        procedure_item_repository=procedure_item_repository,
        visit_payment_repository=visit_payment_repository,
    )

"""FastAPI dependency-injection providers for the Consultation module —
see app/modules/reception/dependencies.py's identical composition
pattern."""

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.modules.consultation.repository import ConsultationRepository
from app.modules.consultation.service import ConsultationService
from app.modules.queue.dependencies import get_queue_service
from app.modules.queue.service import QueueService
from app.modules.visits.dependencies import get_visit_service
from app.modules.visits.service import VisitService
from app.shared.audit.dependencies import get_audit_log_repository
from app.shared.audit.repository import AuditLogRepository


def get_consultation_repository(db: AsyncSession = Depends(get_db)) -> ConsultationRepository:
    return ConsultationRepository(db)


def get_consultation_service(
    db: AsyncSession = Depends(get_db),
    consultation_repository: ConsultationRepository = Depends(get_consultation_repository),
    visit_service: VisitService = Depends(get_visit_service),
    queue_service: QueueService = Depends(get_queue_service),
    audit_repository: AuditLogRepository = Depends(get_audit_log_repository),
) -> ConsultationService:
    return ConsultationService(
        session=db,
        consultation_repository=consultation_repository,
        visit_service=visit_service,
        queue_service=queue_service,
        audit_repository=audit_repository,
    )

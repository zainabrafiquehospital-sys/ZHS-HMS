"""FastAPI dependency-injection providers for the Vitals module — see
app/modules/reception/dependencies.py's identical composition pattern."""

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.modules.consultation.dependencies import get_consultation_service
from app.modules.consultation.service import ConsultationService
from app.modules.queue.dependencies import get_queue_service
from app.modules.queue.service import QueueService
from app.modules.visits.dependencies import get_visit_service
from app.modules.visits.service import VisitService
from app.modules.vitals.repository import VitalsRecordRepository
from app.modules.vitals.service import VitalsService
from app.shared.audit.dependencies import get_audit_log_repository
from app.shared.audit.repository import AuditLogRepository


def get_vitals_record_repository(db: AsyncSession = Depends(get_db)) -> VitalsRecordRepository:
    return VitalsRecordRepository(db)


def get_vitals_service(
    db: AsyncSession = Depends(get_db),
    vitals_record_repository: VitalsRecordRepository = Depends(get_vitals_record_repository),
    visit_service: VisitService = Depends(get_visit_service),
    queue_service: QueueService = Depends(get_queue_service),
    consultation_service: ConsultationService = Depends(get_consultation_service),
    audit_repository: AuditLogRepository = Depends(get_audit_log_repository),
) -> VitalsService:
    return VitalsService(
        session=db,
        vitals_record_repository=vitals_record_repository,
        visit_service=visit_service,
        queue_service=queue_service,
        consultation_service=consultation_service,
        audit_repository=audit_repository,
    )

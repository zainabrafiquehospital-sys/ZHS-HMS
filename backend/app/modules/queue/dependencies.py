"""FastAPI dependency-injection providers for the Queue module — see
app/modules/patients/dependencies.py's identical module docstring."""

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.modules.queue.repository import QueueEntryRepository
from app.modules.queue.service import QueueService
from app.shared.audit.dependencies import get_audit_log_repository
from app.shared.audit.repository import AuditLogRepository


def get_queue_entry_repository(db: AsyncSession = Depends(get_db)) -> QueueEntryRepository:
    return QueueEntryRepository(db)


def get_queue_service(
    db: AsyncSession = Depends(get_db),
    queue_entry_repository: QueueEntryRepository = Depends(get_queue_entry_repository),
    audit_repository: AuditLogRepository = Depends(get_audit_log_repository),
) -> QueueService:
    return QueueService(
        session=db, queue_entry_repository=queue_entry_repository, audit_repository=audit_repository
    )

"""HTTP endpoints for the Queue module. Routing itself (`route_to`) has
no public endpoint — it is always a side effect of a business action
owned by another module (Reception registers, Vitals completes,
Consultation sends-to-vitals/completes), called service-to-service
within the same backend process, never via a generic client-facing
"move this visit" endpoint (see schemas.py's module docstring)."""

from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.modules.auth.dependencies import require_permission
from app.modules.auth.models import User
from app.modules.queue.constants import PERMISSION_QUEUE_MANAGE, PERMISSION_QUEUE_READ
from app.modules.queue.dependencies import get_queue_service
from app.modules.queue.models import QueueDestination, QueueEntryStatus
from app.modules.queue.schemas import QueueEntryOut
from app.modules.queue.service import QueueService
from app.shared.envelope import success_envelope
from app.shared.pagination import PaginationMeta

router = APIRouter(prefix="/queue", tags=["queue"])


@router.get("/worklist")
async def get_worklist(
    destination: QueueDestination = Query(...),
    status: QueueEntryStatus | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    queue_service: QueueService = Depends(get_queue_service),
    _actor: User = Depends(require_permission(PERMISSION_QUEUE_READ)),
) -> dict:
    entries, total = await queue_service.worklist(
        destination=destination, status=status, page=page, page_size=page_size
    )
    body = [QueueEntryOut.from_entry(entry).model_dump(mode="json") for entry in entries]
    meta = PaginationMeta(page=page, page_size=page_size, total=total).model_dump(mode="json")
    return success_envelope(body, meta)


@router.get("/visits/{visit_id}/active")
async def get_active_entry(
    visit_id: UUID,
    queue_service: QueueService = Depends(get_queue_service),
    _actor: User = Depends(require_permission(PERMISSION_QUEUE_READ)),
) -> dict:
    entry = await queue_service.get_active_for_visit(visit_id)
    body = QueueEntryOut.from_entry(entry).model_dump(mode="json") if entry else None
    return success_envelope(body)


@router.get("/visits/{visit_id}/history")
async def get_visit_history(
    visit_id: UUID,
    queue_service: QueueService = Depends(get_queue_service),
    _actor: User = Depends(require_permission(PERMISSION_QUEUE_READ)),
) -> dict:
    entries = await queue_service.get_history_for_visit(visit_id)
    body = [QueueEntryOut.from_entry(entry).model_dump(mode="json") for entry in entries]
    return success_envelope(body)


@router.post("/entries/{entry_id}/start")
async def start_serving(
    entry_id: UUID,
    queue_service: QueueService = Depends(get_queue_service),
    actor: User = Depends(require_permission(PERMISSION_QUEUE_MANAGE)),
) -> dict:
    entry = await queue_service.start_serving(actor=actor, entry_id=entry_id)
    return success_envelope(QueueEntryOut.from_entry(entry).model_dump(mode="json"))

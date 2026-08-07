"""Pydantic response schemas for the Queue module. There is no
`CreateQueueEntryRequest` — every routing change happens through
`QueueService.route_to`, called by the module whose business action
caused it (Reception/Vitals/Consultation), never a generic client-facing
create endpoint (see app/modules/visits/schemas.py's identical
rationale)."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.modules.queue.models import QueueDestination, QueueEntry, QueueEntryStatus


class QueueEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    visit_id: UUID
    destination: QueueDestination
    status: QueueEntryStatus
    reason: str | None
    created_at: datetime
    left_at: datetime | None

    @classmethod
    def from_entry(cls, entry: QueueEntry) -> "QueueEntryOut":
        return cls(
            id=entry.id,
            visit_id=entry.visit_id,
            destination=entry.destination,
            status=entry.status,
            reason=entry.reason,
            created_at=entry.created_at,
            left_at=entry.left_at,
        )

"""Persistence for the generic cross-module audit log — see models.py's
module docstring. Every feature module's service layer depends on this
(one-directional: this table depends on nothing but `user`), mirroring
how every module already depends on shared/base_entity, shared/envelope,
etc."""

from typing import Any
from uuid import UUID

from app.shared.audit.models import AuditEntry
from app.shared.repository.base_repository import BaseRepository


class AuditLogRepository(BaseRepository[AuditEntry]):
    model = AuditEntry

    async def record(
        self,
        *,
        module: str,
        action: str,
        entity_type: str,
        entity_id: UUID | None = None,
        actor_user_id: UUID | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AuditEntry:
        entry = AuditEntry(
            module=module,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            actor_user_id=actor_user_id,
            metadata_=metadata,
        )
        return await self.add(entry)

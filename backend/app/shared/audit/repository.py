"""Persistence for the generic cross-module audit log — see models.py's
module docstring. Every feature module's service layer depends on this
(one-directional: this table depends on nothing but `user`), mirroring
how every module already depends on shared/base_entity, shared/envelope,
etc."""

from typing import Any
from uuid import UUID

from sqlalchemy import select

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

    async def get_latest_for_entity(
        self, *, entity_type: str, entity_id: UUID, action: str
    ) -> AuditEntry | None:
        """The most recent audit entry of `action` recorded against
        `(entity_type, entity_id)` — added (2026-08-19) so a feature can
        use "when was the last time X happened to this entity" as a
        cheap, schema-free reset point, without adding a dedicated
        column/table for it. First user: ReceptionService.
        get_own_revenue/clear_own_revenue, which treats the latest
        `reception.revenue_cleared` entry for `entity_type="user"` as a
        receptionist's own revenue-counter reset point — this table
        already has the exact index this needs
        (`ix_audit_log_entity_type_entity_id_created_at`)."""
        stmt = (
            select(AuditEntry)
            .where(
                AuditEntry.entity_type == entity_type,
                AuditEntry.entity_id == entity_id,
                AuditEntry.action == action,
            )
            .order_by(AuditEntry.created_at.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

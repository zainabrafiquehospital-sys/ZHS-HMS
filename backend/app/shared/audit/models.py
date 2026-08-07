"""The module-agnostic generic audit log every non-auth feature module
writes to — the table app/modules/auth/models.py's `AuditLog` docstring
explicitly anticipated ("a later decision to introduce a module-agnostic
generic audit log never collides with a table that already holds live
compliance history"). Table name `audit_log`, deliberately distinct from
auth's `auth_audit_log`, for exactly that reason.

`action` is a plain string, not a closed PyEnum like auth's
`AuditEventType` — unlike the auth module (one module, one fixed
vocabulary of events), this table is written to by every feature module
(patients, visits, queue, reception, and every module built after them).
A single project-wide enum would have to be edited every time any module
adds a new kind of event, coupling unrelated modules through one shared
type and violating the one-directional dependency graph (Phase 6
architecture §12) this platform otherwise maintains strictly. Convention:
`"<module>.<event>"`, e.g. `"patients.created"`, `"visits.status_changed"`
— enforced by callers (each module's own service layer), not the schema.

Append-only: never updated, never soft-deleted — same reasoning as
auth's AuditLog and PasswordHistory (a record of the past must never
change), hence TimestampedEntity, not BaseEntity."""

from typing import Any
from uuid import UUID

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base_entity import TimestampedEntity


class AuditEntry(TimestampedEntity):
    __tablename__ = "audit_log"
    __table_args__ = (
        Index(
            "ix_audit_log_entity_type_entity_id_created_at",
            "entity_type",
            "entity_id",
            "created_at",
        ),
        Index("ix_audit_log_module_action_created_at", "module", "action", "created_at"),
        Index("ix_audit_log_actor_user_id", "actor_user_id"),
    )

    module: Mapped[str] = mapped_column(String(50), nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[UUID | None] = mapped_column()
    actor_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("user.id", ondelete="SET NULL"))
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB)

"""Shared base-entity columns every persisted table uses: a UUIDv7 primary
key, server-generated timestamps, soft delete, and audit-on-write actor
references — the standards defined in the Phase 0 / Phase 0.5 architecture
documents, applied uniformly instead of being repeated on each model.

`created_by`/`updated_by` reference `user.id`, so any table using this
mixin depends on the `user` table already existing at migration time.
`User` is the one exception: its own audit columns reference itself
(a legal self-referential FK within a single `CREATE TABLE`), which is why
it must be the first table created — every other table's audit columns
depend on it, not the other way around."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column
from uuid6 import uuid7

from app.db.base import Base


class BaseEntity(Base):
    """Abstract mixin providing the standard id/audit/soft-delete columns.
    Feature-module models inherit this instead of `Base` directly."""

    __abstract__ = True

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column()
    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("user.id", ondelete="SET NULL"))
    updated_by: Mapped[UUID | None] = mapped_column(ForeignKey("user.id", ondelete="SET NULL"))


class TimestampedEntity(Base):
    """Abstract mixin providing only `id` + `created_at` — for tables that
    deliberately do not participate in `BaseEntity`'s soft-delete or
    created_by/updated_by audit-actor convention:

    - Truly immutable, append-only rows (PasswordHistory, AuditLog): a
      soft-delete column on evidence/history rows would defeat their
      purpose, and `created_by` is redundant when the row's own `user_id`
      (or `actor_user_id`/`target_user_id`) already identifies whose action
      it records.
    - Rows that ARE mutated in place after creation (RefreshToken's
      `revoked_at`, LoginSession's `logout_at`/`is_active`) but are still
      never soft-deleted (they're purged by a retention job instead) and
      have no independent "audit actor" concept — they belong to exactly
      one user, already captured by their own `user_id` column."""

    __abstract__ = True

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

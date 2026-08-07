from datetime import datetime
from typing import Any, Generic, TypeVar
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import Base

ModelType = TypeVar("ModelType", bound=Base)


class BaseRepository(Generic[ModelType]):
    """Generic, entity-agnostic data access. Feature modules subclass this
    with their own model type; no query logic for a specific entity lives
    here."""

    model: type[ModelType]

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def _exclude_soft_deleted(self, stmt: Select[Any], *, include_deleted: bool) -> Select[Any]:
        """Applies the `deleted_at IS NULL` filter every query in this
        repository must honor by default. Models that don't participate in
        soft delete (e.g. append-only audit/history tables) have no
        `deleted_at` column, so they are left untouched rather than raising."""
        if include_deleted or not hasattr(self.model, "deleted_at"):
            return stmt
        return stmt.where(self.model.deleted_at.is_(None))

    async def get_by_id(
        self, record_id: UUID, *, include_deleted: bool = False
    ) -> ModelType | None:
        stmt = self._exclude_soft_deleted(
            select(self.model).where(self.model.id == record_id),
            include_deleted=include_deleted,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list(
        self, limit: int = 20, offset: int = 0, *, include_deleted: bool = False
    ) -> list[ModelType]:
        stmt = self._exclude_soft_deleted(
            select(self.model).limit(limit).offset(offset),
            include_deleted=include_deleted,
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def add(self, instance: ModelType) -> ModelType:
        self.session.add(instance)
        await self.session.flush()
        return instance

    async def soft_delete(
        self, instance: ModelType, *, deleted_at: datetime, deleted_by: UUID | None = None
    ) -> ModelType:
        """Marks `instance` deleted by setting `deleted_at` (and
        `updated_by`, if the caller supplies an acting user) rather than
        issuing a DB-level DELETE — the soft-delete convention every
        `BaseEntity`-derived model follows (see
        app/shared/base_entity.py). Callers are responsible for using
        this only against models that actually participate in soft
        delete; a `TimestampedEntity`-only model (RefreshToken,
        LoginSession, PasswordHistory, AuditLog) never should, and each
        already has its own purpose-built mutation method instead (e.g.
        `RefreshTokenRepository.revoke`)."""
        instance.deleted_at = deleted_at
        if deleted_by is not None:
            instance.updated_by = deleted_by
        return await self.add(instance)

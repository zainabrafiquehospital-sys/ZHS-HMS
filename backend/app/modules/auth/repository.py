"""Persistence-only repositories for the Authentication module. Each
subclasses `BaseRepository` (soft-delete filtering, `get_by_id`, `list`,
`add` already provided there — see app/shared/repository/base_repository.py)
and adds only the entity-specific queries this module's services actually
need. No password hashing, no token generation, no audit-event
interpretation, no policy decisions live here — persistence only, exactly
as the layered `router → service → repository → model` architecture
requires.

Updating an already-loaded row (e.g. `user.failed_login_attempts += 1`)
reuses the inherited `add()` rather than a bespoke `update()` method — for
an object already in the session's identity map, `session.add()` is a safe
no-op and `flush()` persists the pending change, matching the existing
BaseRepository contract rather than extending it.

`LoginSessionRepository` is not among the repositories named in the Phase 4
brief, but "Session creation" and "Session revocation" are explicit
AuthService responsibilities, and this codebase's layering never lets a
service touch the database directly — a repository is the only
architecturally consistent way to persist LoginSession rows."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import InstrumentedAttribute

from app.modules.auth.models import (
    AuditEventStatus,
    AuditEventType,
    AuditLog,
    LoginSession,
    LoginSessionLogoutReason,
    PasswordHistory,
    Permission,
    RefreshToken,
    RefreshTokenRevokedReason,
    Role,
    RolePermission,
    User,
    UserRole,
    UserStatus,
)
from app.modules.auth.validators import normalize_email
from app.shared.repository.base_repository import BaseRepository

# Whitelist of columns `UserRepository.search` may sort by — never accept a
# raw column/attribute name from a caller and interpolate it, even
# indirectly via getattr(), since that would let request input select
# arbitrary model attributes. `user_schemas.UserSortField` is the
# API-boundary enum that maps onto exactly these same keys.
USER_SORTABLE_COLUMNS: dict[str, InstrumentedAttribute] = {
    "created_at": User.created_at,
    "email": User.email,
    "full_name": User.full_name,
    "status": User.status,
    "last_login_at": User.last_login_at,
}

# Same whitelisting rationale as USER_SORTABLE_COLUMNS, for
# `RoleRepository.search` (`role_schemas.RoleSortField` mirrors these
# same keys).
ROLE_SORTABLE_COLUMNS: dict[str, InstrumentedAttribute] = {
    "created_at": Role.created_at,
    "name": Role.name,
}

# Same whitelisting rationale, for `PermissionRepository.search`
# (`permission_schemas.PermissionSortField` mirrors these same keys).
PERMISSION_SORTABLE_COLUMNS: dict[str, InstrumentedAttribute] = {
    "created_at": Permission.created_at,
    "code": Permission.code,
    "group": Permission.group,
    "display_name": Permission.display_name,
}


class UserRepository(BaseRepository[User]):
    model = User

    async def get_by_email(self, email: str) -> User | None:
        stmt = self._exclude_soft_deleted(
            select(User).where(User.email == normalize_email(email)),
            include_deleted=False,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_phone_number(self, phone_number: str) -> User | None:
        stmt = self._exclude_soft_deleted(
            select(User).where(User.phone_number == phone_number),
            include_deleted=False,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def search(
        self,
        *,
        search: str | None,
        status: UserStatus | None,
        role_id: UUID | None,
        sort_column: InstrumentedAttribute,
        sort_desc: bool,
        limit: int,
        offset: int,
    ) -> tuple[list[User], int]:
        """Backs `GET /users`'s pagination/sorting/search/filtering. Never
        soft-deleted, matching every other query in this repository.
        `sort_column` must be one of `USER_SORTABLE_COLUMNS`'s values —
        the caller (UserService) is responsible for that whitelisting;
        this method just applies whatever column object it's given."""
        conditions = [User.deleted_at.is_(None)]
        if search:
            pattern = f"%{search}%"
            conditions.append(or_(User.email.ilike(pattern), User.full_name.ilike(pattern)))
        if status is not None:
            conditions.append(User.status == status)

        stmt = select(User).where(*conditions)
        if role_id is not None:
            stmt = stmt.join(UserRole, UserRole.user_id == User.id).where(
                UserRole.role_id == role_id, UserRole.deleted_at.is_(None)
            )

        total = (
            await self.session.execute(select(func.count()).select_from(stmt.subquery()))
        ).scalar_one()

        order_column = sort_column.desc() if sort_desc else sort_column.asc()
        stmt = stmt.order_by(order_column, User.id).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total


class UserRoleRepository(BaseRepository[UserRole]):
    """Backs the User Management module's role-assignment endpoints
    (assign/remove/replace). Not needed by Phase 4's auth flows — those
    only ever *read* `user.user_roles` (already eagerly loaded via
    `lazy="selectin"`) to compute effective roles/permissions, never
    create or revoke an assignment."""

    model = UserRole

    async def count_active_for_role(self, role_id: UUID) -> int:
        """Used by RoleService to block deleting a role that's still
        actively assigned to at least one user (see role_service.py's
        module docstring for why that's a hard block, not a cascade)."""
        stmt = (
            select(func.count())
            .select_from(UserRole)
            .where(UserRole.role_id == role_id, UserRole.deleted_at.is_(None))
        )
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def get_active(self, user_id: UUID, role_id: UUID) -> UserRole | None:
        stmt = self._exclude_soft_deleted(
            select(UserRole).where(UserRole.user_id == user_id, UserRole.role_id == role_id),
            include_deleted=False,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()


class RoleRepository(BaseRepository[Role]):
    model = Role

    async def get_by_name(self, name: str) -> Role | None:
        stmt = self._exclude_soft_deleted(
            select(Role).where(Role.name == name), include_deleted=False
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def search(
        self,
        *,
        search: str | None,
        is_active: bool | None,
        sort_column: InstrumentedAttribute,
        sort_desc: bool,
        limit: int,
        offset: int,
    ) -> tuple[list[Role], int]:
        """Backs `GET /roles`'s pagination/sorting/search/filtering —
        the same shape as `UserRepository.search`. `sort_column` must be
        one of `ROLE_SORTABLE_COLUMNS`'s values; the caller (RoleService)
        is responsible for that whitelisting."""
        conditions = [Role.deleted_at.is_(None)]
        if search:
            pattern = f"%{search}%"
            conditions.append(or_(Role.name.ilike(pattern), Role.description.ilike(pattern)))
        if is_active is not None:
            conditions.append(Role.is_active == is_active)

        stmt = select(Role).where(*conditions)
        total = (
            await self.session.execute(select(func.count()).select_from(stmt.subquery()))
        ).scalar_one()

        order_column = sort_column.desc() if sort_desc else sort_column.asc()
        stmt = stmt.order_by(order_column, Role.id).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total


class PermissionRepository(BaseRepository[Permission]):
    model = Permission

    async def get_by_code(self, code: str) -> Permission | None:
        stmt = self._exclude_soft_deleted(
            select(Permission).where(Permission.code == code), include_deleted=False
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def search(
        self,
        *,
        search: str | None,
        group: str | None,
        sort_column: InstrumentedAttribute,
        sort_desc: bool,
        limit: int,
        offset: int,
    ) -> tuple[list[Permission], int]:
        """Backs `GET /permissions`'s pagination/sorting/search/
        filtering — the same shape as `RoleRepository.search`.
        `sort_column` must be one of `PERMISSION_SORTABLE_COLUMNS`'s
        values; the caller (PermissionService) is responsible for that
        whitelisting. `group` (not `is_active`, which this model has no
        column for) is the filter dimension — it uses the existing
        `ix_permission_group` index directly."""
        conditions = [Permission.deleted_at.is_(None)]
        if search:
            pattern = f"%{search}%"
            conditions.append(
                or_(
                    Permission.code.ilike(pattern),
                    Permission.display_name.ilike(pattern),
                    Permission.description.ilike(pattern),
                )
            )
        if group is not None:
            conditions.append(Permission.group == group)

        stmt = select(Permission).where(*conditions)
        total = (
            await self.session.execute(select(func.count()).select_from(stmt.subquery()))
        ).scalar_one()

        order_column = sort_column.desc() if sort_desc else sort_column.asc()
        stmt = stmt.order_by(order_column, Permission.id).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total


class RolePermissionRepository(BaseRepository[RolePermission]):
    """Association-table repository for Role<->Permission, mirroring
    `UserRoleRepository` for User<->Role exactly. `count_active_for_permission`
    was added in Phase 5 Step 4 for that step's delete protection;
    `get_active` was added in Phase 5 Step 5 for
    `RoleService.assign_permissions`/`remove_permissions`/
    `replace_permissions` — the same two-step growth pattern
    `UserRoleRepository` went through across Steps 2 and 3."""

    model = RolePermission

    async def count_active_for_permission(self, permission_id: UUID) -> int:
        """Used by PermissionService to block deleting a permission
        that's still actively granted to at least one role (see
        permission_service.py's module docstring for why that's a hard
        block, not a cascade)."""
        stmt = (
            select(func.count())
            .select_from(RolePermission)
            .where(
                RolePermission.permission_id == permission_id,
                RolePermission.deleted_at.is_(None),
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def get_active(self, role_id: UUID, permission_id: UUID) -> RolePermission | None:
        stmt = self._exclude_soft_deleted(
            select(RolePermission).where(
                RolePermission.role_id == role_id,
                RolePermission.permission_id == permission_id,
            ),
            include_deleted=False,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()


class RefreshTokenRepository(BaseRepository[RefreshToken]):
    model = RefreshToken

    async def get_by_token_hash(self, token_hash: str) -> RefreshToken | None:
        stmt = select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def claim_rotation(
        self, token_id: UUID, replaced_by_id: UUID, revoked_at: datetime
    ) -> bool:
        """Atomically marks `token_id` revoked/rotated, but only if it
        hasn't already been revoked by a concurrent request — the
        race-safe "claim this rotation" write app/core/token_rotation.py's
        module docstring describes. A Core-level conditional UPDATE, not a
        load-then-mutate, so two simultaneous callers can never both
        believe they won.

        Returns True if this call won the race (the caller should proceed
        with the new token it just created), False if it lost (the caller
        should re-fetch this row to see the state the winner wrote, then
        pass that to app.core.token_rotation.classify_reuse)."""
        stmt = (
            update(RefreshToken)
            .where(RefreshToken.id == token_id, RefreshToken.revoked_at.is_(None))
            .values(
                revoked_at=revoked_at,
                revoked_reason=RefreshTokenRevokedReason.ROTATED,
                replaced_by_id=replaced_by_id,
            )
        )
        result = await self.session.execute(stmt)
        return result.rowcount == 1

    async def revoke(
        self, token: RefreshToken, reason: RefreshTokenRevokedReason, revoked_at: datetime
    ) -> RefreshToken:
        token.revoked_at = revoked_at
        token.revoked_reason = reason
        return await self.add(token)

    async def revoke_family(
        self, family_id: UUID, reason: RefreshTokenRevokedReason, revoked_at: datetime
    ) -> None:
        stmt = (
            update(RefreshToken)
            .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=revoked_at, revoked_reason=reason)
        )
        await self.session.execute(stmt)

    async def revoke_all_for_user(
        self, user_id: UUID, reason: RefreshTokenRevokedReason, revoked_at: datetime
    ) -> None:
        stmt = (
            update(RefreshToken)
            .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=revoked_at, revoked_reason=reason)
        )
        await self.session.execute(stmt)


class LoginSessionRepository(BaseRepository[LoginSession]):
    model = LoginSession

    async def revoke(
        self,
        session_row: LoginSession,
        reason: LoginSessionLogoutReason,
        logged_out_at: datetime,
    ) -> LoginSession:
        session_row.is_active = False
        session_row.logout_at = logged_out_at
        session_row.logout_reason = reason
        return await self.add(session_row)

    async def revoke_all_for_user(
        self, user_id: UUID, reason: LoginSessionLogoutReason, logged_out_at: datetime
    ) -> None:
        stmt = (
            update(LoginSession)
            .where(LoginSession.user_id == user_id, LoginSession.is_active.is_(True))
            .values(is_active=False, logout_at=logged_out_at, logout_reason=reason)
        )
        await self.session.execute(stmt)


class PasswordHistoryRepository(BaseRepository[PasswordHistory]):
    model = PasswordHistory

    async def list_recent(self, user_id: UUID, limit: int) -> list[PasswordHistory]:
        stmt = (
            select(PasswordHistory)
            .where(PasswordHistory.user_id == user_id)
            .order_by(PasswordHistory.created_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class AuditRepository(BaseRepository[AuditLog]):
    model = AuditLog

    async def record(
        self,
        *,
        event_type: AuditEventType,
        status: AuditEventStatus,
        actor_user_id: UUID | None = None,
        target_user_id: UUID | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AuditLog:
        entry = AuditLog(
            event_type=event_type,
            status=status,
            actor_user_id=actor_user_id,
            target_user_id=target_user_id,
            ip_address=ip_address,
            user_agent=user_agent,
            metadata_=metadata,
        )
        return await self.add(entry)

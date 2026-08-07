"""Permission Management business logic (Phase 5 Step 4) — CRUD over the
`Permission` entity itself. A sibling to `RoleService`/`UserService`/
`AuthService`, sharing this module's repositories; see
role_service.py's module docstring for the identical SRP-split
reasoning applied here.

Does not subclass the shared `BaseService`
(app/shared/service/base_service.py), for the same reason the other
three services don't.

Every mutating method ends with an explicit `await self._session.commit()`,
matching the established transaction-boundary convention.

`code` is permanently immutable after creation — deliberately not even
present in `UpdatePermissionRequest`/`update_permission`'s `updates`
handling. This is a stronger guarantee than Role's "in-use" protection
(Step 3): `Role.name` is only ever looked up dynamically at runtime
(`RoleRepository.get_by_name`), but `Permission.code` is referenced
throughout the actual application code as a **hardcoded string
literal** — every `require_permission("some:code")` call in every
router. Renaming a `Permission.code` row after creation would silently
break every one of those checks the moment it no longer matches any
constant in app/modules/auth/constants.py, with no error, no exception,
just permission checks that quietly stop passing (or, if a still-valid
code happens to collide, quietly start passing for the wrong reason).
Immutability closes this off entirely rather than mitigating it.

`group` is likewise never independently settable — always derived from
`code`'s prefix at creation, via `validators.derive_permission_group`
(see the `Permission` model's docstring).

`get_roles_for_permission` (Phase 5 Step 5) is a read-only inverse of
`RoleOut.permissions` (Phase 5 Step 3) — needs no new repository
dependency, since `RolePermissionRepository` was already injected here
in Step 4 for `delete_permission`'s in-use check, and the data itself
comes from the already-`lazy="selectin"`-loaded `permission.role_permissions`
relationship, not a new query."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ValidationError
from app.modules.auth.exceptions import (
    PermissionCodeAlreadyExistsError,
    PermissionInUseError,
    PermissionNotFoundError,
)
from app.modules.auth.models import AuditEventStatus, AuditEventType, Permission, Role, User
from app.modules.auth.repository import (
    PERMISSION_SORTABLE_COLUMNS,
    AuditRepository,
    PermissionRepository,
    RolePermissionRepository,
)
from app.modules.auth.validators import derive_permission_group, validate_permission_code
from app.shared.db_errors import unique_violation_constraint_name

# The unique-while-active index backing Permission.code — see
# app/modules/auth/models.py and app/shared/db_errors.py for the full
# race-condition rationale (also applied in role_service.py/
# user_service.py/service.py for their own unique fields).
_PERMISSION_CODE_CONSTRAINT = "ix_permission_code_active"


class PermissionService:
    def __init__(
        self,
        session: AsyncSession,
        permission_repository: PermissionRepository,
        role_permission_repository: RolePermissionRepository,
        audit_repository: AuditRepository,
    ) -> None:
        self._session = session
        self._permission_repo = permission_repository
        self._role_permission_repo = role_permission_repository
        self._audit_repo = audit_repository

    # ------------------------------------------------------------------
    # Create / Get / List / Update / Delete
    # ------------------------------------------------------------------

    async def create_permission(
        self,
        *,
        actor: User,
        code: str,
        display_name: str,
        description: str | None,
    ) -> Permission:
        """Re-validates `code`'s format even though
        `CreatePermissionRequest`'s field validator already did — the
        same defense-in-depth precedent `AuthService.register` follows
        for `PasswordService.validate_policy`, for any caller that
        reaches this method without going through the HTTP schema.

        The `get_by_code` pre-check is not by itself race-safe — see
        app/shared/db_errors.py — hence the `try`/`except` around
        `add()` below, which is what actually closes that window."""
        validate_permission_code(code)
        if await self._permission_repo.get_by_code(code) is not None:
            raise PermissionCodeAlreadyExistsError

        permission = Permission(
            code=code,
            group=derive_permission_group(code),
            display_name=display_name,
            description=description,
            created_by=actor.id,
            updated_by=actor.id,
        )
        try:
            await self._permission_repo.add(permission)
        except IntegrityError as exc:
            await self._session.rollback()
            if unique_violation_constraint_name(exc) == _PERMISSION_CODE_CONSTRAINT:
                raise PermissionCodeAlreadyExistsError from exc
            raise
        await self._audit_repo.record(
            event_type=AuditEventType.PERMISSION_CREATED,
            status=AuditEventStatus.SUCCESS,
            actor_user_id=actor.id,
            metadata={"permission_id": str(permission.id), "code": permission.code},
        )
        await self._session.commit()
        return await self._permission_repo.get_by_id(permission.id)

    async def get_permission(self, permission_id: UUID) -> Permission:
        permission = await self._permission_repo.get_by_id(permission_id)
        if permission is None:
            raise PermissionNotFoundError
        return permission

    async def list_permissions(
        self,
        *,
        search: str | None,
        group: str | None,
        sort_by: str,
        sort_desc: bool,
        page: int,
        page_size: int,
    ) -> tuple[list[Permission], int]:
        """`sort_by` must be one of `PERMISSION_SORTABLE_COLUMNS`'s
        keys — see `RoleService.list_roles`'s identical note."""
        sort_column = PERMISSION_SORTABLE_COLUMNS[sort_by]
        return await self._permission_repo.search(
            search=search,
            group=group,
            sort_column=sort_column,
            sort_desc=sort_desc,
            limit=page_size,
            offset=(page - 1) * page_size,
        )

    async def update_permission(
        self, *, actor: User, permission_id: UUID, updates: dict[str, Any]
    ) -> Permission:
        """Only `display_name` and `description` are ever accepted —
        `code` (and therefore `group`) can never appear in `updates`,
        since `UpdatePermissionRequest` has no field for it. See this
        module's docstring for why."""
        permission = await self.get_permission(permission_id)
        if not updates:
            return permission

        if "display_name" in updates:
            if updates["display_name"] is None:
                raise ValidationError("Display name cannot be cleared.")
            permission.display_name = updates["display_name"]

        if "description" in updates:
            permission.description = updates["description"]

        permission.updated_by = actor.id
        await self._permission_repo.add(permission)
        await self._audit_repo.record(
            event_type=AuditEventType.PERMISSION_UPDATED,
            status=AuditEventStatus.SUCCESS,
            actor_user_id=actor.id,
            metadata={"permission_id": str(permission.id), "fields": sorted(updates.keys())},
        )
        await self._session.commit()
        return await self._permission_repo.get_by_id(permission.id)

    async def delete_permission(self, *, actor: User, permission_id: UUID) -> None:
        """Soft-deletes the permission. Blocked (never cascaded) while
        it is still actively granted to at least one role — deleting a
        permission out from under roles that depend on it would
        silently narrow what those roles (and every user holding them)
        can do, with no visible signal at the moment it happens. The
        admin must explicitly revoke it from every role first (Phase 5
        Step 5's responsibility), making the blast radius visible and
        intentional — the exact same philosophy `RoleService.delete_role`
        already applies to roles still assigned to users."""
        permission = await self.get_permission(permission_id)
        active_grants = await self._role_permission_repo.count_active_for_permission(permission.id)
        if active_grants > 0:
            raise PermissionInUseError

        now = datetime.now(UTC)
        await self._permission_repo.soft_delete(permission, deleted_at=now, deleted_by=actor.id)
        await self._audit_repo.record(
            event_type=AuditEventType.PERMISSION_DELETED,
            status=AuditEventStatus.SUCCESS,
            actor_user_id=actor.id,
            metadata={"permission_id": str(permission.id), "code": permission.code},
        )
        await self._session.commit()

    # ------------------------------------------------------------------
    # Role <-> Permission Assignment (Phase 5 Step 5) — read-only inverse
    # ------------------------------------------------------------------

    async def get_roles_for_permission(self, permission_id: UUID) -> list[Role]:
        """The "which roles currently grant this permission" query —
        the permission's-eye view of the same `role_permission` table
        `RoleOut.permissions` reads from the role's-eye view. Filters
        out both soft-deleted grants and soft-deleted roles: a role can
        be soft-deleted while still holding a technically-active grant
        row (see role_service.py's module docstring for why that's left
        as an inert, harmless state rather than blocked at delete time)
        — this method simply doesn't surface such a role as if it were
        still a live, "using" one.

        Explicitly refreshes `role_permissions` before reading it rather
        than trusting whatever `get_permission` returns — the same
        identity-map staleness `RoleService._reload_with_fresh_permissions`
        guards against (first discovered in Phase 5 Step 2): if this
        `Permission` object was already in the session's identity map
        before a grant was added elsewhere (e.g. by `RoleService` in the
        same unit of work), a plain re-fetch by primary key returns that
        same cached object with its `role_permissions` collection frozen
        at its earlier, pre-grant state."""
        permission = await self.get_permission(permission_id)
        await self._session.refresh(permission, attribute_names=["role_permissions"])
        return sorted(
            (
                role_permission.role
                for role_permission in permission.role_permissions
                if role_permission.deleted_at is None and role_permission.role.deleted_at is None
            ),
            key=lambda role: role.name,
        )

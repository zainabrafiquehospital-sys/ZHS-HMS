"""Role Management business logic (Phase 5 Step 3, extended in Phase 5
Step 5 with Role<->Permission assignment) — CRUD over the `Role` entity
itself, plus managing which permissions a role grants. A sibling to
`UserService` (which manages `User` records and the user↔role
assignment built in Step 2) and to `AuthService` (which manages
authentication flows) — all three share this module's repositories,
split by responsibility rather than by module boundary; see
user_service.py's module docstring for the identical reasoning applied
to that split.

`assign_permissions`/`remove_permissions`/`replace_permissions` live
here (on `RoleService`), not on a separate association service —
mirroring `UserService.assign_roles`/`remove_roles`/`replace_roles`'s
precedent exactly: the "owning" entity's service is where its
assignment methods live, not a dedicated per-relationship service.

Does not subclass the shared `BaseService`
(app/shared/service/base_service.py), for the same reason `AuthService`/
`UserService` don't: this coordinates several repositories plus audit
logging, not a single-entity CRUD shape.

Every mutating method ends with an explicit `await self._session.commit()`,
matching `AuthService`/`UserService`'s transaction-boundary convention.

Role hierarchy (`parent_role_id`) is validated here — a role may not be
its own ancestor — and stored, nothing more. This module deliberately does
NOT wire `parent_role_id` into any permission-resolution logic
(`AuthService.effective_permission_codes` remains untouched); a role's
effective permissions are still exactly its own directly-granted ones.
Hierarchical permission inheritance, if ever wanted, is an explicit
future scope decision, not an incidental side effect of adding role CRUD
or role<->permission assignment.

`delete_role` deliberately still only checks for active *user*
assignments, not active *permission* grants — a role can be soft-deleted
while still holding permission grants. This is intentionally left as-is
(a Phase 5 Step 5 design decision, not an oversight): `AuthService.
_active_roles` already filters out soft-deleted roles before computing
effective permissions, so a deleted role's lingering grants can never be
included in anyone's effective permission set — they are inert, not a
security or correctness gap."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ValidationError
from app.modules.auth.exceptions import (
    InvalidParentRoleError,
    PermissionNotFoundError,
    RoleInUseError,
    RoleNameAlreadyExistsError,
    RoleNotFoundError,
    SystemRoleProtectedError,
)
from app.modules.auth.models import (
    AuditEventStatus,
    AuditEventType,
    Permission,
    Role,
    RolePermission,
    User,
)
from app.modules.auth.repository import (
    ROLE_SORTABLE_COLUMNS,
    AuditRepository,
    PermissionRepository,
    RolePermissionRepository,
    RoleRepository,
    UserRoleRepository,
)
from app.shared.db_errors import unique_violation_constraint_name

# The unique-while-active index backing Role.name — see
# app/modules/auth/models.py. Checked against a caught IntegrityError to
# tell a genuine race-lost duplicate apart from any other integrity
# failure (see this module's create_role/update_role docstrings and
# app/shared/db_errors.py for the full race-condition rationale).
_ROLE_NAME_CONSTRAINT = "ix_role_name_active"


class RoleService:
    def __init__(
        self,
        session: AsyncSession,
        role_repository: RoleRepository,
        user_role_repository: UserRoleRepository,
        permission_repository: PermissionRepository,
        role_permission_repository: RolePermissionRepository,
        audit_repository: AuditRepository,
    ) -> None:
        self._session = session
        self._role_repo = role_repository
        self._user_role_repo = user_role_repository
        self._permission_repo = permission_repository
        self._role_permission_repo = role_permission_repository
        self._audit_repo = audit_repository

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _require_active_parent(self, parent_role_id: UUID) -> Role:
        parent = await self._role_repo.get_by_id(parent_role_id)
        if parent is None:
            raise InvalidParentRoleError(f"Parent role '{parent_role_id}' does not exist.")
        if not parent.is_active:
            raise InvalidParentRoleError(f"Parent role '{parent_role_id}' is inactive.")
        return parent

    async def _validate_no_cycle(self, role_id: UUID, new_parent_id: UUID) -> None:
        """Walks the candidate parent's own ancestor chain to ensure
        `role_id` never appears in it — the only way `parent_role_id`
        could otherwise create a cycle (a role transitively its own
        ancestor). Only relevant to `update_role`: a brand-new role
        being created can never already appear in any existing chain,
        since nothing can reference an id that doesn't exist yet."""
        if role_id == new_parent_id:
            raise InvalidParentRoleError("A role cannot be its own parent.")

        visited = {role_id}
        current_id: UUID | None = new_parent_id
        while current_id is not None:
            if current_id in visited:
                raise InvalidParentRoleError(
                    "This parent assignment would create a cycle in the role hierarchy."
                )
            visited.add(current_id)
            current = await self._role_repo.get_by_id(current_id)
            if current is None:
                break
            current_id = current.parent_role_id

    # ------------------------------------------------------------------
    # Create / Get / List / Update / Delete
    # ------------------------------------------------------------------

    async def create_role(
        self,
        *,
        actor: User,
        name: str,
        description: str | None,
        parent_role_id: UUID | None,
    ) -> Role:
        """`is_system_role` is never accepted here — every role created
        through this API is `is_system_role=False` by construction. A
        "system role" is an internal designation for roles the platform
        itself depends on (seeded outside this API), not something an
        admin can grant to an arbitrary role after the fact.

        The `get_by_name` pre-check below is not by itself race-safe —
        two concurrent requests for the same name can both pass it
        before either commits. The `try`/`except` around `add()` is what
        actually closes that window, by catching the database's own
        rejection of the second insert rather than trusting the
        pre-check alone; see app/shared/db_errors.py for the full
        rationale."""
        if await self._role_repo.get_by_name(name) is not None:
            raise RoleNameAlreadyExistsError

        if parent_role_id is not None:
            await self._require_active_parent(parent_role_id)

        role = Role(
            name=name,
            description=description,
            parent_role_id=parent_role_id,
            is_system_role=False,
            created_by=actor.id,
            updated_by=actor.id,
        )
        try:
            await self._role_repo.add(role)
        except IntegrityError as exc:
            await self._session.rollback()
            if unique_violation_constraint_name(exc) == _ROLE_NAME_CONSTRAINT:
                raise RoleNameAlreadyExistsError from exc
            raise
        await self._audit_repo.record(
            event_type=AuditEventType.ROLE_CREATED,
            status=AuditEventStatus.SUCCESS,
            actor_user_id=actor.id,
            metadata={"role_id": str(role.id), "role_name": role.name},
        )
        await self._session.commit()
        return await self._role_repo.get_by_id(role.id)

    async def get_role(self, role_id: UUID) -> Role:
        role = await self._role_repo.get_by_id(role_id)
        if role is None:
            raise RoleNotFoundError(role_id)
        return role

    async def list_roles(
        self,
        *,
        search: str | None,
        is_active: bool | None,
        sort_by: str,
        sort_desc: bool,
        page: int,
        page_size: int,
    ) -> tuple[list[Role], int]:
        """`sort_by` must be one of `ROLE_SORTABLE_COLUMNS`'s keys — see
        `UserService.list_users`'s identical note."""
        sort_column = ROLE_SORTABLE_COLUMNS[sort_by]
        return await self._role_repo.search(
            search=search,
            is_active=is_active,
            sort_column=sort_column,
            sort_desc=sort_desc,
            limit=page_size,
            offset=(page - 1) * page_size,
        )

    async def update_role(self, *, actor: User, role_id: UUID, updates: dict[str, Any]) -> Role:
        """`is_system_role` is never accepted here either — see
        `create_role`'s docstring. Everything else (`name`,
        `description`, `parent_role_id`, `is_active`) is a plain
        editable field; there is no multi-step status workflow the way
        `User.status` has (no session revocation or similar side effect
        is tied to deactivating a role), so a single generic update
        covers all of it without the "never bypass a dedicated
        transition endpoint" concern `UserService.update_user` has."""
        role = await self.get_role(role_id)
        if not updates:
            return role

        if "name" in updates:
            if updates["name"] is None:
                raise ValidationError("Role name cannot be cleared.")
            existing = await self._role_repo.get_by_name(updates["name"])
            if existing is not None and existing.id != role.id:
                raise RoleNameAlreadyExistsError
            role.name = updates["name"]

        if "description" in updates:
            role.description = updates["description"]

        if "parent_role_id" in updates:
            new_parent_id = updates["parent_role_id"]
            if new_parent_id is not None:
                await self._require_active_parent(new_parent_id)
                await self._validate_no_cycle(role.id, new_parent_id)
            role.parent_role_id = new_parent_id

        if "is_active" in updates:
            if updates["is_active"] is None:
                raise ValidationError("is_active cannot be cleared.")
            role.is_active = updates["is_active"]

        role.updated_by = actor.id
        try:
            await self._role_repo.add(role)
        except IntegrityError as exc:
            await self._session.rollback()
            if unique_violation_constraint_name(exc) == _ROLE_NAME_CONSTRAINT:
                raise RoleNameAlreadyExistsError from exc
            raise
        await self._audit_repo.record(
            event_type=AuditEventType.ROLE_UPDATED,
            status=AuditEventStatus.SUCCESS,
            actor_user_id=actor.id,
            metadata={"role_id": str(role.id), "fields": sorted(updates.keys())},
        )
        await self._session.commit()
        return await self._role_repo.get_by_id(role.id)

    async def delete_role(self, *, actor: User, role_id: UUID) -> None:
        """Soft-deletes the role. Blocked (never cascaded) for two
        independent reasons: a system role must never be deletable via
        this API at all, and a role still actively assigned to at least
        one user must not silently deauthorize an unknown number of
        people as a side effect of an unrelated cleanup action — the
        admin must explicitly reassign/remove those users' role first
        (via the Step 2 role-assignment endpoints), making the blast
        radius of losing a role visible and intentional rather than
        implicit."""
        role = await self.get_role(role_id)
        if role.is_system_role:
            raise SystemRoleProtectedError

        active_assignments = await self._user_role_repo.count_active_for_role(role.id)
        if active_assignments > 0:
            raise RoleInUseError

        now = datetime.now(UTC)
        await self._role_repo.soft_delete(role, deleted_at=now, deleted_by=actor.id)
        await self._audit_repo.record(
            event_type=AuditEventType.ROLE_DELETED,
            status=AuditEventStatus.SUCCESS,
            actor_user_id=actor.id,
            metadata={"role_id": str(role.id), "role_name": role.name},
        )
        await self._session.commit()

    # ------------------------------------------------------------------
    # Role <-> Permission Assignment (Phase 5 Step 5)
    # ------------------------------------------------------------------

    def _active_permission_ids(self, role: Role) -> set[UUID]:
        """Every permission_id currently granted to `role` (not soft-
        deleted). Precondition: `role.role_permissions` must already be
        loaded — see `RoleOut.from_role`'s identical precondition
        docstring in role_schemas.py."""
        return {
            role_permission.permission_id
            for role_permission in role.role_permissions
            if role_permission.deleted_at is None
        }

    async def _require_permission(self, permission_id: UUID) -> Permission:
        """Unlike `_require_active_parent` (roles have `is_active`),
        `Permission` has no such column (see permission_service.py's
        module docstring) — existence is the only thing to check."""
        permission = await self._permission_repo.get_by_id(permission_id)
        if permission is None:
            raise PermissionNotFoundError
        return permission

    async def _reload_with_fresh_permissions(self, role: Role) -> Role:
        """Mirrors `UserService._reload_with_fresh_roles` exactly — see
        its docstring for the full identity-map staleness explanation.
        Within the same session, `role.role_permissions` was already
        populated by `get_role()` at the start of the calling method;
        `RolePermission` rows added/soft-deleted since then through a
        separate repository never touch that already-loaded collection
        object in memory, so a plain re-fetch by primary key would
        return the same stale object unchanged. `session.refresh(...,
        attribute_names=[...])` forces exactly that one relationship to
        reload instead."""
        await self._session.refresh(role, attribute_names=["role_permissions"])
        return role

    async def assign_permissions(
        self, *, actor: User, role_id: UUID, permission_ids: list[UUID]
    ) -> Role:
        """Adds permissions not already actively granted; a
        permission_id already granted is silently skipped (idempotent),
        matching `UserService.assign_roles`'s established precedent.
        Audit events are recorded only for permissions actually newly
        granted — never for skipped duplicates."""
        role = await self.get_role(role_id)
        to_add = set(permission_ids) - self._active_permission_ids(role)

        permissions_by_id: dict[UUID, Permission] = {}
        for permission_id in to_add:
            permissions_by_id[permission_id] = await self._require_permission(permission_id)

        for permission_id, permission in permissions_by_id.items():
            await self._role_permission_repo.add(
                RolePermission(role_id=role.id, permission_id=permission_id)
            )
            await self._audit_repo.record(
                event_type=AuditEventType.PERMISSION_GRANTED,
                status=AuditEventStatus.SUCCESS,
                actor_user_id=actor.id,
                metadata={
                    "role_id": str(role.id),
                    "role_name": role.name,
                    "permission_id": str(permission_id),
                    "permission_code": permission.code,
                },
            )
        if permissions_by_id:
            await self._session.commit()
        return await self._reload_with_fresh_permissions(role)

    async def remove_permissions(
        self, *, actor: User, role_id: UUID, permission_ids: list[UUID]
    ) -> Role:
        """Removes (soft-deletes) the given permission grants; a
        permission_id with no currently-active grant is silently
        skipped (idempotent) rather than raising — there is nothing to
        remove, which is not an error condition. Audit events are
        recorded only for grants actually revoked."""
        role = await self.get_role(role_id)
        now = datetime.now(UTC)
        changed = False

        for permission_id in set(permission_ids):
            role_permission = await self._role_permission_repo.get_active(role.id, permission_id)
            if role_permission is None:
                continue
            permission_code = role_permission.permission.code
            await self._role_permission_repo.soft_delete(
                role_permission, deleted_at=now, deleted_by=actor.id
            )
            await self._audit_repo.record(
                event_type=AuditEventType.PERMISSION_REVOKED,
                status=AuditEventStatus.SUCCESS,
                actor_user_id=actor.id,
                metadata={
                    "role_id": str(role.id),
                    "role_name": role.name,
                    "permission_id": str(permission_id),
                    "permission_code": permission_code,
                },
            )
            changed = True

        if changed:
            await self._session.commit()
        return await self._reload_with_fresh_permissions(role)

    async def replace_permissions(
        self, *, actor: User, role_id: UUID, permission_ids: list[UUID]
    ) -> Role:
        """Sets the role's permission grants to exactly
        `permission_ids`: removes every currently-active grant not in
        the given set and adds every one in it that isn't already
        active. Diff-based, never a delete-all-then-recreate-all — a
        permission already granted and still wanted is left completely
        untouched (no soft-delete-then-reinsert, no new audit event),
        and only genuinely added/removed permissions are mutated or
        audit-logged. Every new permission is validated (exists) before
        any mutation is applied, so a partially-invalid request fails
        atomically instead of leaving a half-applied change."""
        role = await self.get_role(role_id)
        current = self._active_permission_ids(role)
        desired = set(permission_ids)
        to_add = desired - current
        to_remove = current - desired

        permissions_by_id: dict[UUID, Permission] = {}
        for permission_id in to_add:
            permissions_by_id[permission_id] = await self._require_permission(permission_id)

        now = datetime.now(UTC)
        for permission_id in to_remove:
            role_permission = await self._role_permission_repo.get_active(role.id, permission_id)
            if role_permission is None:
                continue
            permission_code = role_permission.permission.code
            await self._role_permission_repo.soft_delete(
                role_permission, deleted_at=now, deleted_by=actor.id
            )
            await self._audit_repo.record(
                event_type=AuditEventType.PERMISSION_REVOKED,
                status=AuditEventStatus.SUCCESS,
                actor_user_id=actor.id,
                metadata={
                    "role_id": str(role.id),
                    "role_name": role.name,
                    "permission_id": str(permission_id),
                    "permission_code": permission_code,
                },
            )

        for permission_id, permission in permissions_by_id.items():
            await self._role_permission_repo.add(
                RolePermission(role_id=role.id, permission_id=permission_id)
            )
            await self._audit_repo.record(
                event_type=AuditEventType.PERMISSION_GRANTED,
                status=AuditEventStatus.SUCCESS,
                actor_user_id=actor.id,
                metadata={
                    "role_id": str(role.id),
                    "role_name": role.name,
                    "permission_id": str(permission_id),
                    "permission_code": permission.code,
                },
            )

        if to_add or to_remove:
            await self._session.commit()
        return await self._reload_with_fresh_permissions(role)

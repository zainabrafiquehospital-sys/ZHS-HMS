"""Pydantic request/response schemas for the Role Management module
(Phase 5 Step 3, extended in Phase 5 Step 5 with Role<->Permission
assignment requests) — its own file, mirroring `user_schemas.py`'s
shape and conventions exactly (partial-update `exclude_unset`
semantics, `LaxUUID` for body-carried UUIDs, `from_attributes` response
models built via a `from_role` classmethod).

`AssignPermissionsRequest`/`RemovePermissionsRequest`/
`ReplacePermissionsRequest` mirror `user_schemas.py`'s
`AssignRolesRequest`/`RemoveRolesRequest`/`ReplaceRolesRequest` exactly
— same shape, same rationale, one level down the RBAC graph (a role's
permissions rather than a user's roles).

`RoleOut` deliberately exposes only `parent_role_id` (the raw FK), not a
resolved `parent_role_name`: `Role` has no `parent`/`children`
`relationship()` in app/modules/auth/models.py (only a plain
self-referential FK column) — adding one would be a model change this
step's scope explicitly excludes ("only validate the hierarchy and
store parent_role_id"), and resolving the name for every row in `GET
/roles` would otherwise mean one extra query per row (N+1). A client
that needs the parent's name already has it — either from the same
listing response (the parent is a `Role` too) or a follow-up `GET
/roles/{parent_role_id}`.

`is_system_role` never appears in `CreateRoleRequest`/`UpdateRoleRequest`
— it is an internal designation, immutable via this API (see
role_service.py for the enforcement and why)."""

from datetime import datetime
from enum import Enum as PyEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.auth.models import Role
from app.shared.schema_types import LaxUUID


class RoleSortField(str, PyEnum):
    CREATED_AT = "created_at"
    NAME = "name"


# ---------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------


class CreateRoleRequest(BaseModel):
    model_config = ConfigDict(strict=True)

    name: str = Field(min_length=1, max_length=50)
    description: str | None = Field(default=None, max_length=2000)
    parent_role_id: LaxUUID | None = None


class UpdateRoleRequest(BaseModel):
    """All fields optional for PATCH-style partial update — see
    `user_schemas.py`'s module docstring for the `exclude_unset`
    semantics `RoleService` relies on. `description` and
    `parent_role_id` may be explicitly cleared (`null`, both nullable
    columns); `name` and `is_active` may not (both `NOT NULL`)."""

    model_config = ConfigDict(strict=True)

    name: str | None = Field(default=None, min_length=1, max_length=50)
    description: str | None = Field(default=None, max_length=2000)
    parent_role_id: LaxUUID | None = None
    is_active: bool | None = None


class AssignPermissionsRequest(BaseModel):
    model_config = ConfigDict(strict=True)

    permission_ids: list[LaxUUID] = Field(min_length=1)


class RemovePermissionsRequest(BaseModel):
    model_config = ConfigDict(strict=True)

    permission_ids: list[LaxUUID] = Field(min_length=1)


class ReplacePermissionsRequest(BaseModel):
    """Unlike Assign/Remove, an empty list is meaningful here — it means
    "this role should end up with no permissions" — so it is not
    `min_length`-constrained. Mirrors `user_schemas.ReplaceRolesRequest`
    exactly."""

    model_config = ConfigDict(strict=True)

    permission_ids: list[LaxUUID] = Field(default_factory=list)


# ---------------------------------------------------------------------
# Responses
# ---------------------------------------------------------------------


class PermissionSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str


class RoleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str | None
    parent_role_id: UUID | None
    is_system_role: bool
    is_active: bool
    permissions: list[PermissionSummary]
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_role(cls, role: Role) -> "RoleOut":
        """Precondition: `role.role_permissions` (and each row's
        `.permission`) must already be loaded — guaranteed for any
        `Role` obtained via `RoleRepository.get_by_id`/`get_by_name`/
        `search`, per the `lazy="selectin"` convention
        app/modules/auth/models.py documents. Only non-soft-deleted
        grants are surfaced — this step never mutates
        `role_permissions` (see this module's docstring), but a future
        step's mutations should be reflected consistently here without
        this method needing to change."""
        permissions = sorted(
            (
                PermissionSummary(
                    id=role_permission.permission.id, code=role_permission.permission.code
                )
                for role_permission in role.role_permissions
                if role_permission.deleted_at is None
            ),
            key=lambda permission: permission.code,
        )
        return cls(
            id=role.id,
            name=role.name,
            description=role.description,
            parent_role_id=role.parent_role_id,
            is_system_role=role.is_system_role,
            is_active=role.is_active,
            permissions=permissions,
            created_at=role.created_at,
            updated_at=role.updated_at,
        )

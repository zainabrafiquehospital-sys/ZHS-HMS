"""HTTP endpoints for the Role Management module (Phase 5 Step 3, CRUD
over the `Role` entity itself; extended in Phase 5 Step 5 with
Role<->Permission assignment). Every endpoint requires the matching
`roles:*` permission via the existing `require_permission()` dependency
factory (Phase 5 Step 1); see app/modules/auth/constants.py for the
permission codes.

The three assignment endpoints all require `roles:manage_permissions` —
a dedicated code, separate from `roles:update`, mirroring
`user_router.py`'s `users:manage_roles` for the identical shape of
capability one level up the RBAC graph. There is deliberately no `GET
/roles/{role_id}/permissions` — `GET /roles/{role_id}` already returns
a role's permissions via `RoleOut.permissions` (Phase 5 Step 3); adding
a second endpoint for the same data would be pure duplication."""

from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.modules.auth.constants import (
    PERMISSION_ROLES_CREATE,
    PERMISSION_ROLES_DELETE,
    PERMISSION_ROLES_MANAGE_PERMISSIONS,
    PERMISSION_ROLES_READ,
    PERMISSION_ROLES_UPDATE,
)
from app.modules.auth.dependencies import get_role_service, require_permission
from app.modules.auth.models import User
from app.modules.auth.role_schemas import (
    AssignPermissionsRequest,
    CreateRoleRequest,
    RemovePermissionsRequest,
    ReplacePermissionsRequest,
    RoleOut,
    RoleSortField,
    UpdateRoleRequest,
)
from app.modules.auth.role_service import RoleService
from app.shared.envelope import success_envelope
from app.shared.pagination import PaginationMeta, SortOrder

router = APIRouter(prefix="/roles", tags=["roles"])


@router.post("", status_code=201)
async def create_role(
    payload: CreateRoleRequest,
    role_service: RoleService = Depends(get_role_service),
    actor: User = Depends(require_permission(PERMISSION_ROLES_CREATE)),
) -> dict:
    role = await role_service.create_role(
        actor=actor,
        name=payload.name,
        description=payload.description,
        parent_role_id=payload.parent_role_id,
    )
    return success_envelope(RoleOut.from_role(role).model_dump(mode="json"))


@router.get("")
async def list_roles(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    search: str | None = Query(default=None, max_length=150),
    is_active: bool | None = Query(default=None),
    sort_by: RoleSortField = Query(default=RoleSortField.CREATED_AT),
    sort_order: SortOrder = Query(default=SortOrder.DESC),
    role_service: RoleService = Depends(get_role_service),
    _actor: User = Depends(require_permission(PERMISSION_ROLES_READ)),
) -> dict:
    roles, total = await role_service.list_roles(
        search=search,
        is_active=is_active,
        sort_by=sort_by.value,
        sort_desc=sort_order == SortOrder.DESC,
        page=page,
        page_size=page_size,
    )
    body = [RoleOut.from_role(role).model_dump(mode="json") for role in roles]
    meta = PaginationMeta(page=page, page_size=page_size, total=total).model_dump(mode="json")
    return success_envelope(body, meta)


@router.get("/{role_id}")
async def get_role(
    role_id: UUID,
    role_service: RoleService = Depends(get_role_service),
    _actor: User = Depends(require_permission(PERMISSION_ROLES_READ)),
) -> dict:
    role = await role_service.get_role(role_id)
    return success_envelope(RoleOut.from_role(role).model_dump(mode="json"))


@router.patch("/{role_id}")
async def update_role(
    role_id: UUID,
    payload: UpdateRoleRequest,
    role_service: RoleService = Depends(get_role_service),
    actor: User = Depends(require_permission(PERMISSION_ROLES_UPDATE)),
) -> dict:
    updated = await role_service.update_role(
        actor=actor, role_id=role_id, updates=payload.model_dump(exclude_unset=True)
    )
    return success_envelope(RoleOut.from_role(updated).model_dump(mode="json"))


@router.delete("/{role_id}")
async def delete_role(
    role_id: UUID,
    role_service: RoleService = Depends(get_role_service),
    actor: User = Depends(require_permission(PERMISSION_ROLES_DELETE)),
) -> dict:
    await role_service.delete_role(actor=actor, role_id=role_id)
    return success_envelope(None)


@router.post("/{role_id}/permissions/assign")
async def assign_permissions(
    role_id: UUID,
    payload: AssignPermissionsRequest,
    role_service: RoleService = Depends(get_role_service),
    actor: User = Depends(require_permission(PERMISSION_ROLES_MANAGE_PERMISSIONS)),
) -> dict:
    role = await role_service.assign_permissions(
        actor=actor, role_id=role_id, permission_ids=payload.permission_ids
    )
    return success_envelope(RoleOut.from_role(role).model_dump(mode="json"))


@router.post("/{role_id}/permissions/remove")
async def remove_permissions(
    role_id: UUID,
    payload: RemovePermissionsRequest,
    role_service: RoleService = Depends(get_role_service),
    actor: User = Depends(require_permission(PERMISSION_ROLES_MANAGE_PERMISSIONS)),
) -> dict:
    role = await role_service.remove_permissions(
        actor=actor, role_id=role_id, permission_ids=payload.permission_ids
    )
    return success_envelope(RoleOut.from_role(role).model_dump(mode="json"))


@router.put("/{role_id}/permissions")
async def replace_permissions(
    role_id: UUID,
    payload: ReplacePermissionsRequest,
    role_service: RoleService = Depends(get_role_service),
    actor: User = Depends(require_permission(PERMISSION_ROLES_MANAGE_PERMISSIONS)),
) -> dict:
    role = await role_service.replace_permissions(
        actor=actor, role_id=role_id, permission_ids=payload.permission_ids
    )
    return success_envelope(RoleOut.from_role(role).model_dump(mode="json"))

"""HTTP endpoints for the Permission Management module (Phase 5 Step 4,
CRUD over the `Permission` entity itself; extended in Phase 5 Step 5
with the read-only "roles for a permission" inverse query). Every
endpoint requires the matching `permissions:*` permission via the
existing `require_permission()` dependency factory; see
app/modules/auth/constants.py for the permission codes.

No endpoint here accepts or mutates `role_permission` (granting a
permission to a role) — the mutating side of that association lives on
`role_router.py` (`roles:manage_permissions`), mirroring exactly how
`user_router.py` owns the mutating side of User<->Role while
`role_router.py` never did. `code` never appears in the update
endpoint's request body — it is immutable after creation."""

from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.modules.auth.constants import (
    PERMISSION_PERMISSIONS_CREATE,
    PERMISSION_PERMISSIONS_DELETE,
    PERMISSION_PERMISSIONS_READ,
    PERMISSION_PERMISSIONS_UPDATE,
)
from app.modules.auth.dependencies import get_permission_service, require_permission
from app.modules.auth.models import User
from app.modules.auth.permission_schemas import (
    CreatePermissionRequest,
    PermissionOut,
    PermissionSortField,
    UpdatePermissionRequest,
)
from app.modules.auth.permission_service import PermissionService
from app.shared.envelope import success_envelope
from app.shared.pagination import PaginationMeta, SortOrder
from app.shared.schema_types import RoleSummary

router = APIRouter(prefix="/permissions", tags=["permissions"])


@router.post("", status_code=201)
async def create_permission(
    payload: CreatePermissionRequest,
    permission_service: PermissionService = Depends(get_permission_service),
    actor: User = Depends(require_permission(PERMISSION_PERMISSIONS_CREATE)),
) -> dict:
    permission = await permission_service.create_permission(
        actor=actor,
        code=payload.code,
        display_name=payload.display_name,
        description=payload.description,
    )
    return success_envelope(PermissionOut.from_permission(permission).model_dump(mode="json"))


@router.get("")
async def list_permissions(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    search: str | None = Query(default=None, max_length=150),
    group: str | None = Query(default=None, max_length=50),
    sort_by: PermissionSortField = Query(default=PermissionSortField.CREATED_AT),
    sort_order: SortOrder = Query(default=SortOrder.DESC),
    permission_service: PermissionService = Depends(get_permission_service),
    _actor: User = Depends(require_permission(PERMISSION_PERMISSIONS_READ)),
) -> dict:
    permissions, total = await permission_service.list_permissions(
        search=search,
        group=group,
        sort_by=sort_by.value,
        sort_desc=sort_order == SortOrder.DESC,
        page=page,
        page_size=page_size,
    )
    body = [
        PermissionOut.from_permission(permission).model_dump(mode="json")
        for permission in permissions
    ]
    meta = PaginationMeta(page=page, page_size=page_size, total=total).model_dump(mode="json")
    return success_envelope(body, meta)


@router.get("/{permission_id}")
async def get_permission(
    permission_id: UUID,
    permission_service: PermissionService = Depends(get_permission_service),
    _actor: User = Depends(require_permission(PERMISSION_PERMISSIONS_READ)),
) -> dict:
    permission = await permission_service.get_permission(permission_id)
    return success_envelope(PermissionOut.from_permission(permission).model_dump(mode="json"))


@router.patch("/{permission_id}")
async def update_permission(
    permission_id: UUID,
    payload: UpdatePermissionRequest,
    permission_service: PermissionService = Depends(get_permission_service),
    actor: User = Depends(require_permission(PERMISSION_PERMISSIONS_UPDATE)),
) -> dict:
    updated = await permission_service.update_permission(
        actor=actor,
        permission_id=permission_id,
        updates=payload.model_dump(exclude_unset=True),
    )
    return success_envelope(PermissionOut.from_permission(updated).model_dump(mode="json"))


@router.delete("/{permission_id}")
async def delete_permission(
    permission_id: UUID,
    permission_service: PermissionService = Depends(get_permission_service),
    actor: User = Depends(require_permission(PERMISSION_PERMISSIONS_DELETE)),
) -> dict:
    await permission_service.delete_permission(actor=actor, permission_id=permission_id)
    return success_envelope(None)


@router.get("/{permission_id}/roles")
async def get_roles_for_permission(
    permission_id: UUID,
    permission_service: PermissionService = Depends(get_permission_service),
    _actor: User = Depends(require_permission(PERMISSION_PERMISSIONS_READ)),
) -> dict:
    """Unpaginated by design — a utility endpoint for management
    visibility ("if needed for management" per the approved scope), and
    the realistic cardinality of roles holding any one permission is
    small, unlike the primary paginated listings."""
    roles = await permission_service.get_roles_for_permission(permission_id)
    body = [RoleSummary.model_validate(role).model_dump(mode="json") for role in roles]
    return success_envelope(body)

"""HTTP endpoints for the User Management module (Phase 5 Step 2):
admin CRUD over users, self-service profile update, status transitions,
admin-driven password actions, and role assignment.

"View Profile" from this step's brief is deliberately NOT a new endpoint
here — it is exactly what `GET /api/v1/auth/me` (Phase 5 Step 1) already
returns, so building a second route that does the same lookup would be
a duplicate path to the same data, not a new feature. "Update Own
Profile" (`PATCH /users/me`) is new, since nothing existing lets a user
change their own name/phone number.

Route registration order matters for `/users/me` vs `/users/{user_id}`:
FastAPI/Starlette matches path templates in registration order, and
`{user_id}` (an untyped path segment at the routing layer — UUID
conversion happens only after a route already matches) would otherwise
shadow the literal string "me". `PATCH /users/me` is therefore declared
before any `PATCH /users/{user_id}` route below.

Every admin mutation requires the matching `users:*` permission via the
existing `require_permission()` dependency factory (Phase 5 Step 1); see
app/modules/auth/constants.py for the permission codes. `status` is
never editable through the generic `PATCH /users/{id}` update endpoint
— see `UserService.update_user`'s docstring for why activate/deactivate/
lock/unlock must be the only paths that change it."""

from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Query

from app.core.config import Settings, get_settings
from app.modules.auth.constants import (
    PERMISSION_USERS_CREATE,
    PERMISSION_USERS_DELETE,
    PERMISSION_USERS_MANAGE_PASSWORD,
    PERMISSION_USERS_MANAGE_ROLES,
    PERMISSION_USERS_MANAGE_STATUS,
    PERMISSION_USERS_READ,
    PERMISSION_USERS_UPDATE,
)
from app.modules.auth.dependencies import (
    get_current_active_user,
    get_user_service,
    require_permission,
)
from app.modules.auth.models import User, UserStatus
from app.modules.auth.user_schemas import (
    AssignRolesRequest,
    CreateUserRequest,
    RemoveRolesRequest,
    ReplaceRolesRequest,
    UpdateOwnProfileRequest,
    UpdateUserRequest,
    UserAdminOut,
    UserSortField,
    UserWithTemporaryPasswordOut,
)
from app.modules.auth.user_service import UserService
from app.shared.email.dependencies import get_email_service
from app.shared.email.service import EmailService, render_signup_approved_email
from app.shared.envelope import success_envelope
from app.shared.pagination import PaginationMeta, SortOrder

router = APIRouter(prefix="/users", tags=["users"])


@router.post("", status_code=201)
async def create_user(
    payload: CreateUserRequest,
    user_service: UserService = Depends(get_user_service),
    actor: User = Depends(require_permission(PERMISSION_USERS_CREATE)),
) -> dict:
    user, temporary_password = await user_service.create_user(
        actor=actor,
        email=payload.email,
        full_name=payload.full_name,
        phone_number=payload.phone_number,
    )
    body = UserWithTemporaryPasswordOut(
        user=UserAdminOut.from_user(user), temporary_password=temporary_password
    )
    return success_envelope(body.model_dump(mode="json"))


@router.patch("/me")
async def update_own_profile(
    payload: UpdateOwnProfileRequest,
    user_service: UserService = Depends(get_user_service),
    user: User = Depends(get_current_active_user),
) -> dict:
    updated = await user_service.update_own_profile(
        user=user, updates=payload.model_dump(exclude_unset=True)
    )
    return success_envelope(UserAdminOut.from_user(updated).model_dump(mode="json"))


@router.get("")
async def list_users(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    search: str | None = Query(default=None, max_length=150),
    status: UserStatus | None = Query(default=None),
    role_id: UUID | None = Query(default=None),
    sort_by: UserSortField = Query(default=UserSortField.CREATED_AT),
    sort_order: SortOrder = Query(default=SortOrder.DESC),
    user_service: UserService = Depends(get_user_service),
    _actor: User = Depends(require_permission(PERMISSION_USERS_READ)),
) -> dict:
    users, total = await user_service.list_users(
        search=search,
        status=status,
        role_id=role_id,
        sort_by=sort_by.value,
        sort_desc=sort_order == SortOrder.DESC,
        page=page,
        page_size=page_size,
    )
    body = [UserAdminOut.from_user(user).model_dump(mode="json") for user in users]
    meta = PaginationMeta(page=page, page_size=page_size, total=total).model_dump(mode="json")
    return success_envelope(body, meta)


@router.get("/{user_id}")
async def get_user(
    user_id: UUID,
    user_service: UserService = Depends(get_user_service),
    _actor: User = Depends(require_permission(PERMISSION_USERS_READ)),
) -> dict:
    user = await user_service.get_user(user_id)
    return success_envelope(UserAdminOut.from_user(user).model_dump(mode="json"))


@router.patch("/{user_id}")
async def update_user(
    user_id: UUID,
    payload: UpdateUserRequest,
    user_service: UserService = Depends(get_user_service),
    actor: User = Depends(require_permission(PERMISSION_USERS_UPDATE)),
) -> dict:
    updated = await user_service.update_user(
        actor=actor, user_id=user_id, updates=payload.model_dump(exclude_unset=True)
    )
    return success_envelope(UserAdminOut.from_user(updated).model_dump(mode="json"))


@router.delete("/{user_id}")
async def delete_user(
    user_id: UUID,
    user_service: UserService = Depends(get_user_service),
    actor: User = Depends(require_permission(PERMISSION_USERS_DELETE)),
) -> dict:
    await user_service.delete_user(actor=actor, user_id=user_id)
    return success_envelope(None)


@router.post("/{user_id}/activate")
async def activate_user(
    user_id: UUID,
    user_service: UserService = Depends(get_user_service),
    actor: User = Depends(require_permission(PERMISSION_USERS_MANAGE_STATUS)),
) -> dict:
    user = await user_service.activate_user(actor=actor, user_id=user_id)
    return success_envelope(UserAdminOut.from_user(user).model_dump(mode="json"))


@router.post("/{user_id}/deactivate")
async def deactivate_user(
    user_id: UUID,
    user_service: UserService = Depends(get_user_service),
    actor: User = Depends(require_permission(PERMISSION_USERS_MANAGE_STATUS)),
) -> dict:
    user = await user_service.deactivate_user(actor=actor, user_id=user_id)
    return success_envelope(UserAdminOut.from_user(user).model_dump(mode="json"))


@router.post("/{user_id}/lock")
async def lock_user(
    user_id: UUID,
    user_service: UserService = Depends(get_user_service),
    actor: User = Depends(require_permission(PERMISSION_USERS_MANAGE_STATUS)),
) -> dict:
    user = await user_service.lock_user(actor=actor, user_id=user_id)
    return success_envelope(UserAdminOut.from_user(user).model_dump(mode="json"))


@router.post("/{user_id}/unlock")
async def unlock_user(
    user_id: UUID,
    user_service: UserService = Depends(get_user_service),
    actor: User = Depends(require_permission(PERMISSION_USERS_MANAGE_STATUS)),
) -> dict:
    user = await user_service.unlock_user(actor=actor, user_id=user_id)
    return success_envelope(UserAdminOut.from_user(user).model_dump(mode="json"))


async def _send_approval_email(
    *, email_service: EmailService, settings: Settings, to: str, recipient_name: str
) -> None:
    """Scheduled via `BackgroundTasks` from `approve_signup` below — runs
    only after the HTTP response is already sent, on plain string
    arguments captured before that response was built, never touching
    an ORM object or the request's now-closed DB session. See
    `UserService.approve_signup`'s docstring for the live incident that
    made this necessary: calling `EmailService.send`'s real-delivery
    path (genuine network I/O — originally a blocking, `asyncio.to_thread`-
    wrapped SMTP call; now a native async HTTP POST to the Resend API,
    see shared/email/service.py) from inside the same request/session
    lifecycle as a later ORM attribute access reliably broke that later
    access with `sqlalchemy.exc.MissingGreenlet` — reproduced live,
    fixed by full decoupling rather than reordering. The switch away
    from SMTP doesn't remove the need for this: it's still a real
    network call with real latency, just no longer thread-offloaded."""
    html_body = render_signup_approved_email(
        hospital_name=settings.app_name,
        recipient_name=recipient_name,
        login_url=settings.frontend_login_url,
    )
    await email_service.send(
        to=to,
        subject=f"Your {settings.app_name} account has been approved",
        html_body=html_body,
    )


@router.post("/{user_id}/approve-signup")
async def approve_signup(
    user_id: UUID,
    background_tasks: BackgroundTasks,
    user_service: UserService = Depends(get_user_service),
    email_service: EmailService = Depends(get_email_service),
    settings: Settings = Depends(get_settings),
    actor: User = Depends(require_permission(PERMISSION_USERS_MANAGE_STATUS)),
) -> dict:
    """Same permission as activate/deactivate/lock/unlock — approving a
    signup is a status transition on the User record, not a distinct
    capability (see UserService.approve_signup's docstring)."""
    user = await user_service.approve_signup(actor=actor, user_id=user_id)
    body = UserAdminOut.from_user(user)
    background_tasks.add_task(
        _send_approval_email,
        email_service=email_service,
        settings=settings,
        to=body.email,
        recipient_name=body.full_name,
    )
    return success_envelope(body.model_dump(mode="json"))


@router.post("/{user_id}/reject-signup")
async def reject_signup(
    user_id: UUID,
    user_service: UserService = Depends(get_user_service),
    actor: User = Depends(require_permission(PERMISSION_USERS_MANAGE_STATUS)),
) -> dict:
    user = await user_service.reject_signup(actor=actor, user_id=user_id)
    return success_envelope(UserAdminOut.from_user(user).model_dump(mode="json"))


@router.post("/{user_id}/reset-password")
async def admin_reset_password(
    user_id: UUID,
    user_service: UserService = Depends(get_user_service),
    actor: User = Depends(require_permission(PERMISSION_USERS_MANAGE_PASSWORD)),
) -> dict:
    user, temporary_password = await user_service.admin_reset_password(actor=actor, user_id=user_id)
    body = UserWithTemporaryPasswordOut(
        user=UserAdminOut.from_user(user), temporary_password=temporary_password
    )
    return success_envelope(body.model_dump(mode="json"))


@router.post("/{user_id}/force-password-change")
async def force_password_change(
    user_id: UUID,
    user_service: UserService = Depends(get_user_service),
    actor: User = Depends(require_permission(PERMISSION_USERS_MANAGE_PASSWORD)),
) -> dict:
    user = await user_service.force_password_change(actor=actor, user_id=user_id)
    return success_envelope(UserAdminOut.from_user(user).model_dump(mode="json"))


@router.post("/{user_id}/roles/assign")
async def assign_roles(
    user_id: UUID,
    payload: AssignRolesRequest,
    user_service: UserService = Depends(get_user_service),
    actor: User = Depends(require_permission(PERMISSION_USERS_MANAGE_ROLES)),
) -> dict:
    user = await user_service.assign_roles(actor=actor, user_id=user_id, role_ids=payload.role_ids)
    return success_envelope(UserAdminOut.from_user(user).model_dump(mode="json"))


@router.post("/{user_id}/roles/remove")
async def remove_roles(
    user_id: UUID,
    payload: RemoveRolesRequest,
    user_service: UserService = Depends(get_user_service),
    actor: User = Depends(require_permission(PERMISSION_USERS_MANAGE_ROLES)),
) -> dict:
    user = await user_service.remove_roles(actor=actor, user_id=user_id, role_ids=payload.role_ids)
    return success_envelope(UserAdminOut.from_user(user).model_dump(mode="json"))


@router.put("/{user_id}/roles")
async def replace_roles(
    user_id: UUID,
    payload: ReplaceRolesRequest,
    user_service: UserService = Depends(get_user_service),
    actor: User = Depends(require_permission(PERMISSION_USERS_MANAGE_ROLES)),
) -> dict:
    user = await user_service.replace_roles(actor=actor, user_id=user_id, role_ids=payload.role_ids)
    return success_envelope(UserAdminOut.from_user(user).model_dump(mode="json"))

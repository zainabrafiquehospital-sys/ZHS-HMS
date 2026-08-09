"""Pydantic request/response schemas for the User Management module
(Phase 5 Step 2) — kept in its own file rather than added to
`schemas.py`, which is scoped to the Authentication *flow* (login,
refresh, /me, change-password). User Management is a distinct set of
concerns (administrative CRUD, status, role assignment) over the same
`User`/`Role`/`UserRole` models, following the same file-per-concern
layout this module already uses (constants/exceptions/validators/
password_service/token_service split as separate files).

Update requests use Pydantic v2's `exclude_unset` idiom for partial
updates: a field's Python-level default of `None` represents "not
provided" (the key never appears in `model_dump(exclude_unset=True)`),
distinct from a field explicitly sent as JSON `null` (which *does*
appear, with value `None`) — UserService distinguishes the two so an
admin can explicitly clear `phone_number` (nullable in the database)
while an explicit `null` for `email`/`full_name` (both `NOT NULL`
columns) is rejected as a business-rule violation rather than silently
ignored or allowed to fail as a raw database error.

Role-assignment requests use `app.shared.schema_types.LaxUUID` for their
`role_ids` lists rather than a bare `list[UUID]` — see that module for
why `ConfigDict(strict=True)` otherwise rejects the JSON string every
real client sends for a UUID."""

import re
from datetime import datetime
from enum import Enum as PyEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.modules.auth.models import Shift, SignupRole, User, UserStatus
from app.modules.auth.validators import normalize_email
from app.shared.schema_types import LaxUUID, RoleSummary

_PHONE_NUMBER_PATTERN = re.compile(r"^[0-9+\-() ]{7,20}$")


def _validate_phone_number(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    if not _PHONE_NUMBER_PATTERN.fullmatch(stripped):
        raise ValueError(
            "Phone number must be 7-20 characters using only digits, spaces, "
            "and the symbols + - ( )."
        )
    return stripped


class UserSortField(str, PyEnum):
    CREATED_AT = "created_at"
    EMAIL = "email"
    FULL_NAME = "full_name"
    STATUS = "status"
    LAST_LOGIN_AT = "last_login_at"


# ---------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------


class CreateUserRequest(BaseModel):
    model_config = ConfigDict(strict=True)

    email: EmailStr
    full_name: str = Field(min_length=1, max_length=150)
    phone_number: str | None = Field(default=None, max_length=20)

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, value: str) -> str:
        return normalize_email(value)

    @field_validator("phone_number")
    @classmethod
    def _validate_phone(cls, value: str | None) -> str | None:
        return _validate_phone_number(value)


class UpdateUserRequest(BaseModel):
    """All fields optional for PATCH-style partial update — see this
    module's docstring for the `exclude_unset` semantics UserService
    relies on."""

    model_config = ConfigDict(strict=True)

    email: EmailStr | None = None
    full_name: str | None = Field(default=None, min_length=1, max_length=150)
    phone_number: str | None = Field(default=None, max_length=20)

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, value: str | None) -> str | None:
        return normalize_email(value) if value is not None else None

    @field_validator("phone_number")
    @classmethod
    def _validate_phone(cls, value: str | None) -> str | None:
        return _validate_phone_number(value)


class UpdateOwnProfileRequest(BaseModel):
    """Deliberately excludes `email`: self-service email changes would
    need a re-verification flow that doesn't exist yet (the same reason
    `AuthService.register` sets `status=ACTIVE` explicitly rather than
    relying on email verification) — an admin can still change a user's
    email via `UpdateUserRequest`."""

    model_config = ConfigDict(strict=True)

    full_name: str | None = Field(default=None, min_length=1, max_length=150)
    phone_number: str | None = Field(default=None, max_length=20)

    @field_validator("phone_number")
    @classmethod
    def _validate_phone(cls, value: str | None) -> str | None:
        return _validate_phone_number(value)


class AssignRolesRequest(BaseModel):
    model_config = ConfigDict(strict=True)

    role_ids: list[LaxUUID] = Field(min_length=1)


class RemoveRolesRequest(BaseModel):
    model_config = ConfigDict(strict=True)

    role_ids: list[LaxUUID] = Field(min_length=1)


class ReplaceRolesRequest(BaseModel):
    """Unlike Assign/Remove, an empty list is meaningful here — it means
    "this user should end up with no roles" — so it is not
    `min_length`-constrained."""

    model_config = ConfigDict(strict=True)

    role_ids: list[LaxUUID] = Field(default_factory=list)


# ---------------------------------------------------------------------
# Responses
# ---------------------------------------------------------------------


class UserAdminOut(BaseModel):
    """The administrative view of a user — richer than `schemas.UserOut`
    (used by the self-service login/refresh/me responses), since an
    admin managing accounts needs operational fields (lockout state,
    last login) a user viewing their own profile does not need surfaced
    at that boundary. Two separate schemas rather than one shared one
    with optional fields: the two audiences have genuinely different
    contracts, and conflating them would leak admin-only fields into the
    self-service response shape."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    full_name: str
    phone_number: str | None
    status: UserStatus
    # Nullable — see Shift's own model docstring: only ever set by
    # self-service signup, so an admin-provisioned account (User
    # Management's Create User) has none.
    shift: Shift | None
    # Same nullability reasoning as `shift`. Surfaced specifically so
    # the admin's Pending Approvals list can show what a still-pending
    # signup requested — once approved, `roles` (below) already reflects
    # the real assignment, so this field matters most exactly while
    # `status == PENDING_ADMIN_APPROVAL`.
    signup_role: SignupRole | None
    is_email_verified: bool
    mfa_enabled: bool
    must_change_password: bool
    roles: list[RoleSummary]
    failed_login_attempts: int
    locked_until: datetime | None
    last_login_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_user(cls, user: User) -> "UserAdminOut":
        """Precondition: `user.user_roles` (and each row's `.role`) must
        already be loaded — guaranteed for any `User` obtained via
        `UserRepository.get_by_id`/`get_by_email`/`search`, per the
        `lazy="selectin"` convention app/modules/auth/models.py
        documents; see `AuthService._active_roles`'s docstring for the
        same precondition applied elsewhere in this module. Only
        non-soft-deleted role assignments are surfaced; unlike
        `AuthService.effective_role_names`, an expired-but-not-revoked
        assignment is still included — this is an administrative
        "what's on record" view, not an effective-permission
        computation."""
        roles = sorted(
            (
                RoleSummary(id=user_role.role.id, name=user_role.role.name)
                for user_role in user.user_roles
                if user_role.deleted_at is None
            ),
            key=lambda role: role.name,
        )
        return cls(
            id=user.id,
            email=user.email,
            full_name=user.full_name,
            phone_number=user.phone_number,
            status=user.status,
            shift=user.shift,
            signup_role=user.signup_role,
            is_email_verified=user.is_email_verified,
            mfa_enabled=user.mfa_enabled,
            must_change_password=user.must_change_password,
            roles=roles,
            failed_login_attempts=user.failed_login_attempts,
            locked_until=user.locked_until,
            last_login_at=user.last_login_at,
            created_at=user.created_at,
            updated_at=user.updated_at,
        )


class UserWithTemporaryPasswordOut(BaseModel):
    """Shared response shape for Create User and Admin Reset Password —
    both mint a system-generated temporary password that is only ever
    returned this one time (it is stored solely as an Argon2id hash;
    see PasswordService.generate_temporary_password). There is
    deliberately no email-delivery step here — see this module's
    endpoint docstrings for why."""

    user: UserAdminOut
    temporary_password: str

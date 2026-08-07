"""Pydantic request/response schemas for the Authentication module — the
API's public contract, decoupled from the ORM models (§8 of the
architecture document).

Boundary with validators.py: this file does purely structural/format
validation (field presence, type, length, email shape) via
`field_validator`. `new_password`'s policy check is the one exception —
it calls the *same* centralized `validate_password_policy` function
`AuthService.change_password` also calls, so a violation surfaces as an
immediate, fully-detailed 422 at the API boundary rather than only after
a database round-trip, while the rule itself is still defined in exactly
one place (validators.py), not duplicated. Password *history* reuse
still isn't checkable here — that requires the database — and stays
solely in `PasswordService.check_not_reused`, called from `service.py`.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.modules.auth.constants import PASSWORD_MAX_LENGTH, PASSWORD_MIN_LENGTH
from app.modules.auth.models import User, UserStatus
from app.modules.auth.validators import normalize_email, validate_password_policy


class LoginRequest(BaseModel):
    model_config = ConfigDict(strict=True)

    email: EmailStr
    password: str = Field(min_length=1, max_length=PASSWORD_MAX_LENGTH)
    remember_me: bool = False

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, value: str) -> str:
        return normalize_email(value)


class ChangePasswordRequest(BaseModel):
    model_config = ConfigDict(strict=True)

    current_password: str = Field(min_length=1, max_length=PASSWORD_MAX_LENGTH)
    new_password: str = Field(min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH)

    @field_validator("new_password")
    @classmethod
    def _validate_policy(cls, value: str) -> str:
        validate_password_policy(value)
        return value


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    full_name: str
    phone_number: str | None
    status: UserStatus
    is_email_verified: bool
    mfa_enabled: bool
    must_change_password: bool
    roles: list[str]
    # Additive: the user's effective permission codes (same set
    # `require_permission()` already checks server-side on every
    # request — see AuthService.effective_permission_codes). The backend
    # remains the actual authorization boundary; this only lets the
    # frontend hide navigation/routes it has no business showing,
    # exactly like AuthGuard's own docstring already frames
    # authentication-guard UI as "not itself a trust boundary".
    permissions: list[str]
    created_at: datetime

    @classmethod
    def from_user(cls, user: User, roles: list[str], permissions: list[str]) -> "UserOut":
        """The one place `User` + effective role names/permissions
        become the API's response shape — used by both the
        login/refresh response and `GET /me`, so it's defined once
        rather than assembled inline at each call site."""
        return cls(
            id=user.id,
            email=user.email,
            full_name=user.full_name,
            phone_number=user.phone_number,
            status=user.status,
            is_email_verified=user.is_email_verified,
            mfa_enabled=user.mfa_enabled,
            must_change_password=user.must_change_password,
            roles=roles,
            permissions=permissions,
            created_at=user.created_at,
        )


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut

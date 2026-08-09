"""Pydantic request/response schemas for self-service signup, email
verification, resend, and forgot-password/reset-password — kept in
their own file for the same reason user_schemas.py is separate from
schemas.py: a distinct set of concerns (public, unauthenticated
account-creation/recovery flows) over the same `User` model, not the
authenticated login/refresh/me concerns `schemas.py` owns.

Field set for `SignupRequest` mirrors `CreateUserRequest`/
`PatientIdentityFields`'s established conventions exactly (`EmailStr`
+ `normalize_email`, the same `_PHONE_NUMBER_PATTERN` user_schemas.py
already validates against, `password` policy-checked the same way
`ChangePasswordRequest.new_password` is) rather than inventing new
validation shapes — `shift` is the one genuinely new field, required
here (unlike on `User` itself, where it's nullable — see Shift's model
docstring) since a receptionist signup always states one."""

import re
from enum import Enum as PyEnum

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.modules.auth.constants import PASSWORD_MAX_LENGTH, PASSWORD_MIN_LENGTH
from app.modules.auth.models import Shift
from app.modules.auth.validators import normalize_email, validate_password_policy

_PHONE_NUMBER_PATTERN = re.compile(r"^[0-9+\-() ]{7,20}$")
_OTP_CODE_PATTERN = re.compile(r"^\d{6}$")


def _validate_phone_number(value: str) -> str:
    stripped = value.strip()
    if not _PHONE_NUMBER_PATTERN.fullmatch(stripped):
        raise ValueError(
            "Phone number must be 7-20 characters using only digits, spaces, "
            "and the symbols + - ( )."
        )
    return stripped


def _validate_otp_code(value: str) -> str:
    if not _OTP_CODE_PATTERN.fullmatch(value):
        raise ValueError("Code must be exactly 6 digits.")
    return value


class SignupRole(str, PyEnum):
    """Which role a self-service signup is requesting. Modeled as an
    explicit request field (rather than hardcoding a single role
    invisibly in SignupService) specifically so a second self-service
    role could be added as an additive enum value here, not a rewrite —
    `VITALS` is exactly that: added without touching `RECEPTIONIST`'s
    value or any existing signup/OTP/approval code path, only which
    Role name `UserService.approve_signup` resolves this to (see
    models.SignupRole, the persisted-column twin of this schema enum,
    for where the value actually gets read back)."""

    RECEPTIONIST = "receptionist"
    VITALS = "vitals"


# ---------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------


class SignupRequest(BaseModel):
    model_config = ConfigDict(strict=True)

    full_name: str = Field(min_length=1, max_length=150)
    email: EmailStr
    phone_number: str = Field(min_length=7, max_length=20)
    password: str = Field(min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH)
    shift: Shift
    role: SignupRole = SignupRole.RECEPTIONIST

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, value: str) -> str:
        return normalize_email(value)

    @field_validator("phone_number")
    @classmethod
    def _validate_phone(cls, value: str) -> str:
        return _validate_phone_number(value)

    @field_validator("password")
    @classmethod
    def _validate_policy(cls, value: str) -> str:
        validate_password_policy(value)
        return value


class VerifySignupOtpRequest(BaseModel):
    model_config = ConfigDict(strict=True)

    email: EmailStr
    code: str

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, value: str) -> str:
        return normalize_email(value)

    @field_validator("code")
    @classmethod
    def _validate_code(cls, value: str) -> str:
        return _validate_otp_code(value)


class ResendSignupOtpRequest(BaseModel):
    """Signup-verification-only — forgot-password's own "resend" is just
    re-submitting `ForgotPasswordRequest` to `/auth/forgot-password`
    (already cooldown-protected the same way, via the same `_issue_otp`
    codepath), so there is no separate PASSWORD_RESET-purpose resend
    endpoint to build."""

    model_config = ConfigDict(strict=True)

    email: EmailStr

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, value: str) -> str:
        return normalize_email(value)


class ForgotPasswordRequest(BaseModel):
    model_config = ConfigDict(strict=True)

    email: EmailStr

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, value: str) -> str:
        return normalize_email(value)


class VerifyResetOtpRequest(BaseModel):
    """Non-consuming check ("is this code currently valid") — see
    SignupService/AuthService docstrings for why forgot-password's OTP
    is deliberately not consumed until `ResetPasswordRequest` actually
    changes the password, unlike signup's `VerifySignupOtpRequest`."""

    model_config = ConfigDict(strict=True)

    email: EmailStr
    code: str

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, value: str) -> str:
        return normalize_email(value)

    @field_validator("code")
    @classmethod
    def _validate_code(cls, value: str) -> str:
        return _validate_otp_code(value)


class ResetPasswordRequest(BaseModel):
    model_config = ConfigDict(strict=True)

    email: EmailStr
    code: str
    new_password: str = Field(min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH)

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, value: str) -> str:
        return normalize_email(value)

    @field_validator("code")
    @classmethod
    def _validate_code(cls, value: str) -> str:
        return _validate_otp_code(value)

    @field_validator("new_password")
    @classmethod
    def _validate_policy(cls, value: str) -> str:
        validate_password_policy(value)
        return value


# ---------------------------------------------------------------------
# Responses
# ---------------------------------------------------------------------


class SignupResponse(BaseModel):
    """Deliberately minimal — no user id, no status detail beyond the
    message. `email` is echoed back only so the frontend can pre-fill
    the OTP-verification screen without holding it in a separate piece
    of client state across the redirect."""

    message: str
    email: str


class GenericOtpMessageResponse(BaseModel):
    """Shared shape for every step that must not reveal account
    existence/state beyond a generic acknowledgement — resend and
    forgot-password both return exactly this, worded identically
    regardless of whether the email matched an account (see
    AuthService.request_password_reset's docstring for the standard
    "don't leak whether an email is registered" reasoning already
    established for login/forgot-password in this module)."""

    message: str


class VerifySignupOtpResponse(BaseModel):
    message: str
    status: str

"""Authentication-specific client-facing exceptions. All subclass the
existing `app/core/exceptions.py` hierarchy — never a parallel one — so
every endpoint in the app, auth or otherwise, produces the same error
envelope and status-code mapping.

Deliberately generic messages throughout: distinguishing "wrong password"
from "no such account" (or "token expired" from "token revoked" from
"token reused") in the client-visible message would leak information an
attacker can use for enumeration — see app/core/token_rotation.py and the
architecture document's §6 for the same principle applied elsewhere."""

from app.core.exceptions import (
    AuthenticationError,
    ConflictError,
    NotFoundError,
    RecordLockedError,
    ValidationError,
)


class InvalidCredentialsError(AuthenticationError):
    code = "INVALID_CREDENTIALS"

    def __init__(self) -> None:
        super().__init__("Invalid email or password.")


class AccountLockedError(RecordLockedError):
    code = "ACCOUNT_LOCKED"

    def __init__(self) -> None:
        super().__init__("This account is temporarily locked. Try again later.")


class AccountSuspendedError(AuthenticationError):
    code = "ACCOUNT_SUSPENDED"
    status_code = 403

    def __init__(self) -> None:
        super().__init__("This account cannot sign in.")


class AccountPendingEmailVerificationError(AuthenticationError):
    code = "ACCOUNT_PENDING_EMAIL_VERIFICATION"
    status_code = 403

    def __init__(self) -> None:
        super().__init__("Please verify your email before signing in.")


class AccountPendingApprovalError(AuthenticationError):
    code = "ACCOUNT_PENDING_APPROVAL"
    status_code = 403

    def __init__(self) -> None:
        super().__init__(
            "Your account is awaiting admin approval. You'll receive an email once it's approved."
        )


class TokenInvalidError(AuthenticationError):
    code = "TOKEN_INVALID"

    def __init__(self) -> None:
        super().__init__("Invalid or expired token.")


class PasswordPolicyViolationError(ValidationError):
    code = "PASSWORD_POLICY_VIOLATION"

    def __init__(self, reasons: list[str]) -> None:
        super().__init__("Password does not meet the required policy.", {"reasons": reasons})


class PasswordReusedError(ConflictError):
    code = "PASSWORD_REUSED"

    def __init__(self) -> None:
        super().__init__("This password has been used recently. Choose a different one.")


class EmailAlreadyRegisteredError(ConflictError):
    code = "EMAIL_ALREADY_REGISTERED"

    def __init__(self) -> None:
        super().__init__("An account with this email already exists.")


class PhoneNumberAlreadyRegisteredError(ConflictError):
    code = "PHONE_NUMBER_ALREADY_REGISTERED"

    def __init__(self) -> None:
        super().__init__("An account with this phone number already exists.")


# ---------------------------------------------------------------------
# User Management (Phase 5 Step 2)
# ---------------------------------------------------------------------


class UserNotFoundError(NotFoundError):
    code = "USER_NOT_FOUND"

    def __init__(self) -> None:
        super().__init__("User not found.")


class RoleNotFoundError(NotFoundError):
    code = "ROLE_NOT_FOUND"

    def __init__(self, role_id: object) -> None:
        super().__init__(f"Role '{role_id}' not found.", {"role_id": str(role_id)})


class RoleInactiveError(ValidationError):
    code = "ROLE_INACTIVE"

    def __init__(self, role_id: object) -> None:
        super().__init__(
            f"Role '{role_id}' is inactive and cannot be assigned.", {"role_id": str(role_id)}
        )


class InvalidUserStatusTransitionError(ValidationError):
    code = "INVALID_STATUS_TRANSITION"


class SelfActionNotAllowedError(ValidationError):
    code = "SELF_ACTION_NOT_ALLOWED"

    def __init__(self) -> None:
        super().__init__("This action cannot be performed on your own account.")


# ---------------------------------------------------------------------
# Role Management (Phase 5 Step 3)
# ---------------------------------------------------------------------


class RoleNameAlreadyExistsError(ConflictError):
    code = "ROLE_NAME_ALREADY_EXISTS"

    def __init__(self) -> None:
        super().__init__("A role with this name already exists.")


class SystemRoleProtectedError(ValidationError):
    code = "SYSTEM_ROLE_PROTECTED"

    def __init__(self) -> None:
        super().__init__("System roles cannot be deleted.")


class RoleInUseError(ConflictError):
    code = "ROLE_IN_USE"

    def __init__(self) -> None:
        super().__init__(
            "This role is currently assigned to one or more users and cannot be deleted."
        )


class InvalidParentRoleError(ValidationError):
    code = "INVALID_PARENT_ROLE"


# ---------------------------------------------------------------------
# Permission Management (Phase 5 Step 4)
# ---------------------------------------------------------------------


class PermissionCodeAlreadyExistsError(ConflictError):
    code = "PERMISSION_CODE_ALREADY_EXISTS"

    def __init__(self) -> None:
        super().__init__("A permission with this code already exists.")


class PermissionNotFoundError(NotFoundError):
    code = "PERMISSION_NOT_FOUND"

    def __init__(self) -> None:
        super().__init__("Permission not found.")


class InvalidPermissionCodeError(ValidationError):
    code = "INVALID_PERMISSION_CODE"

    def __init__(self) -> None:
        super().__init__(
            "Permission code must be in the form 'group:action' — lowercase letters, "
            "digits, and underscores only, e.g. 'patients:create'."
        )


class PermissionInUseError(ConflictError):
    code = "PERMISSION_IN_USE"

    def __init__(self) -> None:
        super().__init__(
            "This permission is currently granted to one or more roles and cannot be deleted."
        )


# ---------------------------------------------------------------------
# Self-Service Signup / OTP
# ---------------------------------------------------------------------


class OtpInvalidError(AuthenticationError):
    """Deliberately the one error for wrong code, expired code, and
    too-many-attempts alike — same "don't leak which reason" philosophy
    this module's own docstring states for InvalidCredentialsError, now
    applied to a second low-entropy secret."""

    code = "OTP_INVALID"

    def __init__(self) -> None:
        super().__init__("This code is invalid or has expired. Request a new one.")


class SignupNotPendingApprovalError(ValidationError):
    code = "SIGNUP_NOT_PENDING_APPROVAL"

    def __init__(self) -> None:
        super().__init__("This account is not awaiting approval.")

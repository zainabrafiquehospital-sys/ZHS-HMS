"""Reusable validation functions shared across `schemas.py` (structural,
per-field validation at the request boundary) and `services/` (business-
rule validation that needs configuration or database access, e.g. password
history). Centralized here instead of duplicated inline so the rule is
defined exactly once regardless of how many call sites need it."""

import re
import string

from app.modules.auth.constants import (
    COMMON_PASSWORDS,
    PASSWORD_MAX_LENGTH,
    PASSWORD_MIN_LENGTH,
    PASSWORD_REQUIRED_CHARACTER_CLASSES,
    PERMISSION_GROUP_MAX_LENGTH,
)
from app.modules.auth.exceptions import InvalidPermissionCodeError, PasswordPolicyViolationError

_PERMISSION_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*:[a-z][a-z0-9_]*$")


def normalize_email(email: str) -> str:
    """Per the architecture document's Blocking Issue #5 resolution: email
    uniqueness is enforced at the database via a plain (not `citext`)
    unique index, so the application must guarantee lowercasing before any
    insert or lookup — this is the single place that happens."""
    return email.strip().lower()


def validate_password_policy(password: str) -> None:
    """Raises `PasswordPolicyViolationError` (with every violated rule
    listed, not just the first) if `password` doesn't meet the minimum
    length, character-class diversity, and common-password requirements
    from the architecture document's §5. Does not check password history
    reuse — that requires the user's stored hashes and belongs to
    `PasswordService.check_not_reused`, not this purely structural check.
    """
    reasons: list[str] = []

    if len(password) < PASSWORD_MIN_LENGTH:
        reasons.append(f"Must be at least {PASSWORD_MIN_LENGTH} characters long.")
    if len(password) > PASSWORD_MAX_LENGTH:
        reasons.append(f"Must be at most {PASSWORD_MAX_LENGTH} characters long.")

    character_classes_present = sum(
        [
            any(c in string.ascii_uppercase for c in password),
            any(c in string.ascii_lowercase for c in password),
            any(c in string.digits for c in password),
            any(c not in string.ascii_letters + string.digits for c in password),
        ]
    )
    if character_classes_present < PASSWORD_REQUIRED_CHARACTER_CLASSES:
        reasons.append(
            "Must contain at least "
            f"{PASSWORD_REQUIRED_CHARACTER_CLASSES} of: uppercase letter, "
            "lowercase letter, digit, symbol."
        )

    if password.lower() in COMMON_PASSWORDS:
        reasons.append("This password is too common. Choose a less predictable one.")

    if reasons:
        raise PasswordPolicyViolationError(reasons)


def validate_permission_code(code: str) -> None:
    """Raises `InvalidPermissionCodeError` unless `code` matches the
    `group:action` convention every permission code in this codebase
    already follows (see the `Permission` model's docstring and
    app/modules/auth/constants.py's `PERMISSION_*` constants for the
    same shape) — lowercase letters, digits, and underscores only, with
    a single `:` separating a non-empty group from a non-empty action.
    Called from both `CreatePermissionRequest`'s field validator
    (immediate 422) and `PermissionService.create_permission`
    (defense-in-depth for any caller that bypasses the HTTP layer),
    matching `validate_password_policy`'s identical dual-call-site
    precedent. `code` is immutable after creation (see
    permission_service.py's module docstring), so this is only ever
    called once per permission's lifetime, on creation."""
    if not _PERMISSION_CODE_PATTERN.fullmatch(code):
        raise InvalidPermissionCodeError
    if len(code.split(":", 1)[0]) > PERMISSION_GROUP_MAX_LENGTH:
        raise InvalidPermissionCodeError


def derive_permission_group(code: str) -> str:
    """The `group` half of `code`, split on its first `:` — the single
    place this derivation happens, so `Permission.group` can never
    drift out of sync with `Permission.code` (see the `Permission`
    model's docstring for why `group` is never independently supplied
    by a caller). Assumes `code` has already passed
    `validate_permission_code`."""
    return code.split(":", 1)[0]

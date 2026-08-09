"""FastAPI dependency-injection providers for the Authentication module —
the same `Depends()`-chained provider-function pattern already established
by app/core/dependencies.py's `get_db`, extended here for repositories,
services, and the current-user/permission/role checks every other module's
protected endpoints will eventually depend on too.

`PasswordService` is an `@lru_cache` singleton, matching how
`get_settings`/`get_jwt_key_registry`/`get_redis_client` are already built
elsewhere: it's stateless with respect to any single request, and
`PasswordService.__init__` does one deliberately-expensive Argon2id hash
up front (see password_service.py) — constructing a fresh instance on
every request would add that cost to every single authenticated call.
`TokenService.__init__` does no comparable expensive work, so
`get_token_service` is built fresh per request instead — see its own
docstring for why (in short: `Settings` isn't hashable, which would break
`@lru_cache` outright, and there's no performance reason to fight that).
Repositories and `AuthService` are the same story: built fresh per request
from `Depends(get_db)`, since they carry a request-scoped `AsyncSession`
that must never be shared across concurrent requests.

`get_token_service` takes its collaborators as `Depends(...)`-injected
parameters rather than calling `get_jwt_key_registry()`/`get_redis_client()`
directly in its body — the latter would be invisible to FastAPI's
`app.dependency_overrides`, which only intercepts parameters declared via
`Depends()` in a function signature, not calls made inside it. Tests need
to substitute a real-but-temporary JWT key pair and a fakeredis client for
the real ones."""

from collections.abc import Callable, Coroutine
from functools import lru_cache
from typing import Any
from uuid import UUID

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.dependencies import get_db, get_rate_limiter
from app.core.exceptions import AuthenticationError, PermissionDeniedError
from app.core.jwt_keys import JWTKeyRegistry, get_jwt_key_registry
from app.core.rate_limit import RateLimiter
from app.modules.auth.exceptions import AccountSuspendedError, TokenInvalidError
from app.modules.auth.models import User, UserStatus
from app.modules.auth.otp_service import OtpService
from app.modules.auth.password_service import PasswordService
from app.modules.auth.permission_service import PermissionService
from app.modules.auth.repository import (
    AuditRepository,
    LoginSessionRepository,
    OtpCodeRepository,
    PasswordHistoryRepository,
    PermissionRepository,
    RefreshTokenRepository,
    RolePermissionRepository,
    RoleRepository,
    UserRepository,
    UserRoleRepository,
)
from app.modules.auth.role_service import RoleService
from app.modules.auth.service import AuthService
from app.modules.auth.signup_service import SignupService
from app.modules.auth.token_service import TokenService
from app.modules.auth.user_service import UserService
from app.redis.client import get_redis_client
from app.shared.email.dependencies import get_email_service
from app.shared.email.service import EmailService

_bearer_scheme = HTTPBearer(auto_error=False)

# ----------------------------------------------------------------------
# Repositories (request-scoped)
# ----------------------------------------------------------------------


def get_user_repository(db: AsyncSession = Depends(get_db)) -> UserRepository:
    return UserRepository(db)


def get_role_repository(db: AsyncSession = Depends(get_db)) -> RoleRepository:
    return RoleRepository(db)


def get_user_role_repository(db: AsyncSession = Depends(get_db)) -> UserRoleRepository:
    return UserRoleRepository(db)


def get_permission_repository(db: AsyncSession = Depends(get_db)) -> PermissionRepository:
    return PermissionRepository(db)


def get_role_permission_repository(
    db: AsyncSession = Depends(get_db),
) -> RolePermissionRepository:
    return RolePermissionRepository(db)


def get_refresh_token_repository(db: AsyncSession = Depends(get_db)) -> RefreshTokenRepository:
    return RefreshTokenRepository(db)


def get_login_session_repository(db: AsyncSession = Depends(get_db)) -> LoginSessionRepository:
    return LoginSessionRepository(db)


def get_password_history_repository(
    db: AsyncSession = Depends(get_db),
) -> PasswordHistoryRepository:
    return PasswordHistoryRepository(db)


def get_audit_repository(db: AsyncSession = Depends(get_db)) -> AuditRepository:
    return AuditRepository(db)


def get_otp_code_repository(db: AsyncSession = Depends(get_db)) -> OtpCodeRepository:
    return OtpCodeRepository(db)


# ----------------------------------------------------------------------
# Services (crypto services are process-lifetime singletons; AuthService
# is request-scoped since it owns the request's transaction boundary)
# ----------------------------------------------------------------------


@lru_cache
def get_password_service() -> PasswordService:
    return PasswordService()


@lru_cache
def get_otp_service() -> OtpService:
    """`@lru_cache`d like `get_password_service`, not because OTP
    hashing is expensive (see OtpCode's own model docstring — it's
    deliberately fast, unlike Argon2id) but because it's equally
    stateless with respect to any single request; building a fresh
    instance per call would just be pointless allocation."""
    return OtpService()


def get_token_service(
    key_registry: JWTKeyRegistry = Depends(get_jwt_key_registry),
    settings: Settings = Depends(get_settings),
    redis: Redis = Depends(get_redis_client),
) -> TokenService:
    """Not `@lru_cache`d, unlike `get_password_service` — unlike
    `PasswordService.__init__`, `TokenService.__init__` does no expensive
    work (it only stores references), so there's no real cost to building
    a fresh one per request. That also sidesteps `Settings` not being
    hashable (it isn't `frozen=True`), which would otherwise break
    `lru_cache`'s cache-key computation outright."""
    return TokenService(key_registry=key_registry, settings=settings, redis=redis)


def get_auth_service(
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    user_repository: UserRepository = Depends(get_user_repository),
    refresh_token_repository: RefreshTokenRepository = Depends(get_refresh_token_repository),
    login_session_repository: LoginSessionRepository = Depends(get_login_session_repository),
    password_history_repository: PasswordHistoryRepository = Depends(
        get_password_history_repository
    ),
    audit_repository: AuditRepository = Depends(get_audit_repository),
    password_service: PasswordService = Depends(get_password_service),
    token_service: TokenService = Depends(get_token_service),
    otp_code_repository: OtpCodeRepository = Depends(get_otp_code_repository),
    otp_service: OtpService = Depends(get_otp_service),
    email_service: EmailService = Depends(get_email_service),
) -> AuthService:
    return AuthService(
        session=db,
        settings=settings,
        user_repository=user_repository,
        refresh_token_repository=refresh_token_repository,
        login_session_repository=login_session_repository,
        password_history_repository=password_history_repository,
        audit_repository=audit_repository,
        password_service=password_service,
        token_service=token_service,
        otp_code_repository=otp_code_repository,
        otp_service=otp_service,
        email_service=email_service,
    )


def get_signup_service(
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    user_repository: UserRepository = Depends(get_user_repository),
    otp_code_repository: OtpCodeRepository = Depends(get_otp_code_repository),
    audit_repository: AuditRepository = Depends(get_audit_repository),
    password_service: PasswordService = Depends(get_password_service),
    otp_service: OtpService = Depends(get_otp_service),
    email_service: EmailService = Depends(get_email_service),
) -> SignupService:
    return SignupService(
        session=db,
        settings=settings,
        user_repository=user_repository,
        otp_code_repository=otp_code_repository,
        audit_repository=audit_repository,
        password_service=password_service,
        otp_service=otp_service,
        email_service=email_service,
    )


def get_user_service(
    db: AsyncSession = Depends(get_db),
    user_repository: UserRepository = Depends(get_user_repository),
    role_repository: RoleRepository = Depends(get_role_repository),
    user_role_repository: UserRoleRepository = Depends(get_user_role_repository),
    password_history_repository: PasswordHistoryRepository = Depends(
        get_password_history_repository
    ),
    refresh_token_repository: RefreshTokenRepository = Depends(get_refresh_token_repository),
    login_session_repository: LoginSessionRepository = Depends(get_login_session_repository),
    audit_repository: AuditRepository = Depends(get_audit_repository),
    password_service: PasswordService = Depends(get_password_service),
) -> UserService:
    return UserService(
        session=db,
        user_repository=user_repository,
        role_repository=role_repository,
        user_role_repository=user_role_repository,
        password_history_repository=password_history_repository,
        refresh_token_repository=refresh_token_repository,
        login_session_repository=login_session_repository,
        audit_repository=audit_repository,
        password_service=password_service,
    )


def get_role_service(
    db: AsyncSession = Depends(get_db),
    role_repository: RoleRepository = Depends(get_role_repository),
    user_role_repository: UserRoleRepository = Depends(get_user_role_repository),
    permission_repository: PermissionRepository = Depends(get_permission_repository),
    role_permission_repository: RolePermissionRepository = Depends(get_role_permission_repository),
    audit_repository: AuditRepository = Depends(get_audit_repository),
) -> RoleService:
    return RoleService(
        session=db,
        role_repository=role_repository,
        user_role_repository=user_role_repository,
        permission_repository=permission_repository,
        role_permission_repository=role_permission_repository,
        audit_repository=audit_repository,
    )


def get_permission_service(
    db: AsyncSession = Depends(get_db),
    permission_repository: PermissionRepository = Depends(get_permission_repository),
    role_permission_repository: RolePermissionRepository = Depends(get_role_permission_repository),
    audit_repository: AuditRepository = Depends(get_audit_repository),
) -> PermissionService:
    return PermissionService(
        session=db,
        permission_repository=permission_repository,
        role_permission_repository=role_permission_repository,
        audit_repository=audit_repository,
    )


# ----------------------------------------------------------------------
# Rate limiting
# ----------------------------------------------------------------------


async def enforce_login_rate_limit(
    request: Request,
    settings: Settings = Depends(get_settings),
    limiter: RateLimiter = Depends(get_rate_limiter),
) -> None:
    """Bounds login attempts per source IP, independent of and in
    addition to `account_lockout_threshold` (which bounds attempts
    against one specific account). This is what actually blunts a
    credential-stuffing sweep that spreads a handful of guesses across
    many different accounts from the same source rather than hammering
    one account repeatedly.

    Applies regardless of whether the attempt succeeds or fails — an
    attacker who eventually guesses correctly is still bound by the same
    request budget as one who never does.

    Falls back to a shared "unknown" bucket when the ASGI server hasn't
    populated `request.client` (as under a raw test transport, or a
    misconfigured reverse proxy that doesn't forward the real client
    address) — this assumes deployment behind a reverse proxy that sets
    the ASGI scope's client correctly; parsing `X-Forwarded-For` safely
    (i.e. only trusting a proxy-controlled hop, not attacker-supplied
    headers) is a separate concern for the deployment/infra layer, not
    this dependency.
    """
    ip = request.client.host if request.client else "unknown"
    await limiter.enforce(
        key=f"login:{ip}",
        limit=settings.login_rate_limit_attempts,
        window_seconds=settings.login_rate_limit_window_seconds,
    )


async def enforce_otp_request_rate_limit(
    request: Request,
    settings: Settings = Depends(get_settings),
    limiter: RateLimiter = Depends(get_rate_limiter),
) -> None:
    """Bounds how often *new* OTP codes can be requested from one source —
    signup, resend, and forgot-password all funnel through this, same
    per-IP-bucket shape as `enforce_login_rate_limit` (see that
    function's docstring for the "unknown" bucket fallback rationale).
    Independent of `otp_resend_cooldown_seconds` (the OtpCode-row-level
    cooldown SignupService/AuthService enforce for one specific account)
    the same way `login_rate_limit_*` is independent of
    `account_lockout_threshold` — this bounds overall request volume
    from one source, that bounds repeated requests against one account."""
    ip = request.client.host if request.client else "unknown"
    await limiter.enforce(
        key=f"otp-request:{ip}",
        limit=settings.otp_request_rate_limit_attempts,
        window_seconds=settings.otp_request_rate_limit_window_seconds,
    )


async def enforce_otp_verify_rate_limit(
    request: Request,
    settings: Settings = Depends(get_settings),
    limiter: RateLimiter = Depends(get_rate_limiter),
) -> None:
    """Bounds OTP verification attempts per source IP — the second,
    independent layer defending the 6-digit code against brute-forcing,
    alongside the per-code `attempts`/`otp_max_attempts` counter OtpCode
    itself tracks (see that model's docstring)."""
    ip = request.client.host if request.client else "unknown"
    await limiter.enforce(
        key=f"otp-verify:{ip}",
        limit=settings.otp_verify_rate_limit_attempts,
        window_seconds=settings.otp_verify_rate_limit_window_seconds,
    )


# ----------------------------------------------------------------------
# Authentication dependency (shared decode+lookup, two public entry
# points: with and without the token's `jti`)
# ----------------------------------------------------------------------


async def _authenticate(
    credentials: HTTPAuthorizationCredentials | None,
    token_service: TokenService,
    user_repository: UserRepository,
) -> tuple[User, dict]:
    if credentials is None:
        raise AuthenticationError("Authentication required.")
    claims = await token_service.decode_access_token(credentials.credentials)
    user = await user_repository.get_by_id(UUID(claims["sub"]))
    if user is None:
        # The user this token names no longer exists (hard-deleted) —
        # client-visible outcome is identical to any other invalid token.
        raise TokenInvalidError
    return user, claims


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    token_service: TokenService = Depends(get_token_service),
    user_repository: UserRepository = Depends(get_user_repository),
) -> User:
    user, _claims = await _authenticate(credentials, token_service, user_repository)
    return user


async def get_current_user_and_jti(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    token_service: TokenService = Depends(get_token_service),
    user_repository: UserRepository = Depends(get_user_repository),
) -> tuple[User, str]:
    """Identical to `get_current_user`, but also returns the access
    token's `jti` — needed only by the logout-all endpoint, to blacklist
    the specific token used to authenticate that call (see
    AuthService.logout_all)."""
    return await _authenticate(credentials, token_service, user_repository)


async def get_current_active_user(user: User = Depends(get_current_user)) -> User:
    if user.status not in (UserStatus.ACTIVE, UserStatus.PENDING_VERIFICATION):
        raise AccountSuspendedError
    return user


# ----------------------------------------------------------------------
# Authorization dependency factories
# ----------------------------------------------------------------------


def require_permission(permission_code: str) -> Callable[..., Coroutine[Any, Any, User]]:
    async def dependency(
        user: User = Depends(get_current_active_user),
        auth_service: AuthService = Depends(get_auth_service),
    ) -> User:
        if permission_code not in auth_service.effective_permission_codes(user):
            raise PermissionDeniedError(f"Missing required permission: {permission_code}")
        return user

    return dependency


def require_role(role_name: str) -> Callable[..., Coroutine[Any, Any, User]]:
    async def dependency(
        user: User = Depends(get_current_active_user),
        auth_service: AuthService = Depends(get_auth_service),
    ) -> User:
        if role_name not in auth_service.effective_role_names(user):
            raise PermissionDeniedError(f"Missing required role: {role_name}")
        return user

    return dependency

"""HTTP endpoints for the Authentication module — exactly the six named in
the Authentication APIs scope: login, refresh, logout, logout-all,
change-password, me. `AuthService.register` exists and is fully tested
(see service.py and tests/) but deliberately has no endpoint here — no
email-verification flow exists yet, and exposing it wasn't part of this
step's endpoint list.

Refresh tokens travel as an httpOnly, `SameSite=Strict` cookie (never in a
JSON body), per the architecture document's §2 — the access token, sent as
an `Authorization: Bearer` header on every other request rather than a
cookie, is what makes that header immune to CSRF in the first place (a
cookie-based access token would need a separate CSRF-token defense; a
bearer header doesn't). The cookie is scoped to this router's own path so
it's never sent to unrelated endpoints.

`login` also enforces a per-source-IP rate limit (see
app/modules/auth/dependencies.py's `enforce_login_rate_limit` and
app/core/rate_limit.py) — the endpoint where request-volume throttling
matters most, since it's the one an attacker can hit without already
holding any valid credential."""

from fastapi import APIRouter, Depends, Request, Response

from app.core.config import Settings, get_settings
from app.modules.auth.dependencies import (
    enforce_login_rate_limit,
    get_auth_service,
    get_current_active_user,
    get_current_user_and_jti,
)
from app.modules.auth.exceptions import TokenInvalidError
from app.modules.auth.models import User
from app.modules.auth.schemas import ChangePasswordRequest, LoginRequest, TokenResponse, UserOut
from app.modules.auth.service import AuthService, LoginResult, RefreshResult
from app.shared.envelope import success_envelope

router = APIRouter(prefix="/auth", tags=["auth"])

_REFRESH_COOKIE_NAME = "refresh_token"
_SECONDS_PER_DAY = 24 * 60 * 60


def _cookie_path(settings: Settings) -> str:
    return f"{settings.api_v1_prefix}{router.prefix}"


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _set_refresh_cookie(
    response: Response, raw_refresh_token: str, remember_me: bool, settings: Settings
) -> None:
    expire_days = (
        settings.jwt_refresh_token_remember_me_expire_days
        if remember_me
        else settings.jwt_refresh_token_expire_days
    )
    response.set_cookie(
        key=_REFRESH_COOKIE_NAME,
        value=raw_refresh_token,
        max_age=expire_days * _SECONDS_PER_DAY,
        path=_cookie_path(settings),
        httponly=True,
        secure=settings.is_production,
        samesite="strict",
    )


def _clear_refresh_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(key=_REFRESH_COOKIE_NAME, path=_cookie_path(settings))


def _token_response(
    result: LoginResult | RefreshResult, settings: Settings, auth_service: AuthService
) -> dict:
    body = TokenResponse(
        access_token=result.access_token,
        expires_in=settings.jwt_access_token_expire_minutes * 60,
        user=UserOut.from_user(
            result.user,
            auth_service.effective_role_names(result.user),
            sorted(auth_service.effective_permission_codes(result.user)),
        ),
    )
    return success_envelope(body.model_dump(mode="json"))


@router.post("/login")
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    settings: Settings = Depends(get_settings),
    auth_service: AuthService = Depends(get_auth_service),
    _rate_limit: None = Depends(enforce_login_rate_limit),
) -> dict:
    result = await auth_service.login(
        email=payload.email,
        password=payload.password,
        remember_me=payload.remember_me,
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    _set_refresh_cookie(response, result.raw_refresh_token, result.remember_me, settings)
    return _token_response(result, settings, auth_service)


@router.post("/refresh")
async def refresh(
    request: Request,
    response: Response,
    settings: Settings = Depends(get_settings),
    auth_service: AuthService = Depends(get_auth_service),
) -> dict:
    raw_refresh_token = request.cookies.get(_REFRESH_COOKIE_NAME)
    if not raw_refresh_token:
        raise TokenInvalidError
    result = await auth_service.refresh(
        raw_refresh_token=raw_refresh_token,
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    _set_refresh_cookie(response, result.raw_refresh_token, result.remember_me, settings)
    return _token_response(result, settings, auth_service)


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    settings: Settings = Depends(get_settings),
    auth_service: AuthService = Depends(get_auth_service),
) -> dict:
    """Deliberately does not require a valid access token — a client with
    an already-expired access token but a still-valid refresh cookie must
    still be able to log out cleanly (see AuthService.logout's own
    idempotency note)."""
    raw_refresh_token = request.cookies.get(_REFRESH_COOKIE_NAME)
    if raw_refresh_token:
        await auth_service.logout(raw_refresh_token=raw_refresh_token)
    _clear_refresh_cookie(response, settings)
    return success_envelope(None)


@router.post("/logout-all")
async def logout_all(
    response: Response,
    settings: Settings = Depends(get_settings),
    auth_service: AuthService = Depends(get_auth_service),
    current: tuple[User, str] = Depends(get_current_user_and_jti),
) -> dict:
    user, jti = current
    await auth_service.logout_all(user=user, current_access_token_jti=jti)
    _clear_refresh_cookie(response, settings)
    return success_envelope(None)


@router.post("/change-password")
async def change_password(
    payload: ChangePasswordRequest,
    response: Response,
    settings: Settings = Depends(get_settings),
    auth_service: AuthService = Depends(get_auth_service),
    user: User = Depends(get_current_active_user),
) -> dict:
    await auth_service.change_password(
        user=user,
        current_password=payload.current_password,
        new_password=payload.new_password,
    )
    # change_password revokes every session for this user, including the
    # one making this call — clearing the cookie here matches that.
    _clear_refresh_cookie(response, settings)
    return success_envelope(None)


@router.get("/me")
async def get_me(
    auth_service: AuthService = Depends(get_auth_service),
    user: User = Depends(get_current_active_user),
) -> dict:
    body = UserOut.from_user(
        user,
        auth_service.effective_role_names(user),
        sorted(auth_service.effective_permission_codes(user)),
    )
    return success_envelope(body.model_dump(mode="json"))

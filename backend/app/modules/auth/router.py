"""HTTP endpoints for the Authentication module — the original six named
in the Authentication APIs scope (login, refresh, logout, logout-all,
change-password, me) plus the self-service signup/verification/forgot-
password endpoints added for self-service staff registration (Receptionist
and Vitals staff — see models.SignupRole).
`AuthService.register` still exists, still fully tested, and still has
no endpoint of its own — it predates this feature and sets `status=
ACTIVE` directly (see its own docstring); self-service signup now goes
through `SignupService.signup` instead, which is the real, login-blocked-
until-verified-and-approved path this module needed.

Signup/verify-email/resend-otp/forgot-password all enforce
`enforce_otp_request_rate_limit`; verify-email and (from Stage 5)
password-reset verification enforce `enforce_otp_verify_rate_limit` —
both per-source-IP, same shape as `login`'s own rate limit, see
app/modules/auth/dependencies.py for why each exists as an independent
layer alongside the OTP row's own `attempts` counter.

Refresh tokens travel as an httpOnly cookie (never in a JSON body), per
the architecture document's §2 — the access token, sent as an
`Authorization: Bearer` header on every other request rather than a
cookie, is what makes that header immune to CSRF in the first place (a
cookie-based access token would need a separate CSRF-token defense; a
bearer header doesn't). The cookie is scoped to this router's own path so
it's never sent to unrelated endpoints. `SameSite` is `Strict` in any
same-site deployment (local dev) but must be `None` (with `Secure`) in
this app's actual production topology, where the frontend and backend
are genuinely cross-site (Vercel vs. Railway) — see `_set_refresh_cookie`
for the full reasoning; a `Strict` cookie is simply never delivered back
on a cross-site request, which is what made every refresh silently fail
in production.

`login` also enforces a per-source-IP rate limit (see
app/modules/auth/dependencies.py's `enforce_login_rate_limit` and
app/core/rate_limit.py) — the endpoint where request-volume throttling
matters most, since it's the one an attacker can hit without already
holding any valid credential."""

from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response

from app.core.config import Settings, get_settings
from app.modules.auth.dependencies import (
    enforce_login_rate_limit,
    enforce_otp_request_rate_limit,
    enforce_otp_verify_rate_limit,
    get_auth_service,
    get_current_active_user,
    get_current_user_and_jti,
    get_signup_service,
)
from app.modules.auth.exceptions import TokenInvalidError
from app.modules.auth.models import SignupRole, User
from app.modules.auth.schemas import ChangePasswordRequest, LoginRequest, TokenResponse, UserOut
from app.modules.auth.service import AuthService, LoginResult, RefreshResult
from app.modules.auth.signup_schemas import (
    ForgotPasswordRequest,
    GenericOtpMessageResponse,
    ResendSignupOtpRequest,
    ResetPasswordRequest,
    SignupRequest,
    SignupResponse,
    VerifyResetOtpRequest,
    VerifySignupOtpRequest,
    VerifySignupOtpResponse,
)
from app.modules.auth.signup_service import SignupService
from app.shared.envelope import success_envelope

router = APIRouter(prefix="/auth", tags=["auth"])

_REFRESH_COOKIE_NAME = "refresh_token"
_SECONDS_PER_DAY = 24 * 60 * 60

# Optional cross-tab identity-pinning header the frontend sends on every
# /auth/refresh call (see AuthService.refresh's `expected_user_id`
# docstring for the full rationale/audit finding this closes). Entirely
# advisory from the router's perspective — a missing or malformed value
# is simply treated as "no expectation", never a 4xx of its own, since
# older/unrelated clients calling this endpoint must keep working
# unchanged.
_EXPECTED_USER_ID_HEADER = "X-Expected-User-Id"


def _cookie_path(settings: Settings) -> str:
    return f"{settings.api_v1_prefix}{router.prefix}"


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _expected_user_id(request: Request) -> UUID | None:
    raw = request.headers.get(_EXPECTED_USER_ID_HEADER)
    if not raw:
        return None
    try:
        return UUID(raw)
    except ValueError:
        return None


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
        # `Settings.cors_allowed_origins` defaults to this deployment's
        # real frontend origin (a Vercel domain) — the backend and
        # frontend are genuinely cross-site in production (Railway vs.
        # Vercel), never merely cross-port the way local dev's
        # localhost:3000 -> localhost:8000 is. A `SameSite=Strict` (or
        # even `Lax`) cookie is *never* sent back by the browser on a
        # cross-site request, at all, regardless of how recently it was
        # set — not flaky, not a race, structurally impossible. That
        # made every `/auth/refresh` call in production silently arrive
        # with no cookie, `raise TokenInvalidError`, and force a logout:
        # on every hard reload (which always needs a fresh refresh) and
        # after every access-token expiry (~15 min) during continuous
        # use. `SameSite=None` is the only setting a genuinely cross-site
        # deployment's refresh cookie can use and still be delivered;
        # browsers require `Secure` alongside it, which this already has
        # via `secure=settings.is_production` — mirrored here with the
        # identical `is_production` gate so local dev (same-site,
        # plain http://localhost) keeps the strictly tighter `Strict`
        # policy unchanged, and only the real cross-site deployment
        # relaxes to what it actually needs to function.
        #
        # This does reopen a narrow CSRF surface on this endpoint alone:
        # a malicious cross-site page can now trigger a blind POST
        # /auth/refresh carrying the victim's cookie. It cannot exploit
        # that for anything meaningful — CORS still blocks the attacker
        # page from *reading* the response (no readable access token
        # exfiltrated), and it cannot lock the legitimate user out
        # either: `AuthService.refresh`'s rotation-race handling already
        # guarantees both a genuine request and a forged blind one each
        # end up with their own independently valid token in the same
        # family (see token_rotation.py's `classify_reuse` /
        # `BENIGN_REPLAY`) rather than one succeeding and the other
        # being revoked. Worst case is an unwanted extra rotation, not
        # session theft. A same-origin deployment (e.g. a Vercel rewrite
        # proxying /api/* to the backend, so the browser only ever talks
        # to one origin) would remove this tradeoff entirely rather than
        # mitigate it, but that is an infrastructure/hosting decision
        # outside this module's scope, not a code change here.
        samesite="none" if settings.is_production else "strict",
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
        expected_user_id=_expected_user_id(request),
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


# ------------------------------------------------------------------
# Self-service signup / email verification (Receptionist or Vitals staff)
# ------------------------------------------------------------------


@router.post("/signup", status_code=201)
async def signup(
    payload: SignupRequest,
    signup_service: SignupService = Depends(get_signup_service),
    _rate_limit: None = Depends(enforce_otp_request_rate_limit),
) -> dict:
    user = await signup_service.signup(
        full_name=payload.full_name,
        email=payload.email,
        phone_number=payload.phone_number,
        password=payload.password,
        shift=payload.shift,
        # `payload.role` is signup_schemas.SignupRole (a str-Enum) — its
        # `.value` matches models.SignupRole's own values exactly (kept
        # in lockstep deliberately, see that enum's docstring), so this
        # is a plain, unambiguous conversion between the request-schema
        # enum and the persisted-column enum, not a lossy mapping.
        signup_role=SignupRole(payload.role.value),
    )
    body = SignupResponse(
        message="Account created. We've sent a verification code to your email.",
        email=user.email,
    )
    return success_envelope(body.model_dump(mode="json"))


@router.post("/verify-email")
async def verify_email(
    payload: VerifySignupOtpRequest,
    signup_service: SignupService = Depends(get_signup_service),
    _rate_limit: None = Depends(enforce_otp_verify_rate_limit),
) -> dict:
    await signup_service.verify_signup_otp(email=payload.email, code=payload.code)
    body = VerifySignupOtpResponse(
        message="Email verified. Your account is now awaiting admin approval.",
        status="pending_admin_approval",
    )
    return success_envelope(body.model_dump(mode="json"))


@router.post("/resend-otp")
async def resend_signup_otp(
    payload: ResendSignupOtpRequest,
    signup_service: SignupService = Depends(get_signup_service),
    _rate_limit: None = Depends(enforce_otp_request_rate_limit),
) -> dict:
    await signup_service.resend_signup_otp(email=payload.email)
    body = GenericOtpMessageResponse(message="A new verification code has been sent to your email.")
    return success_envelope(body.model_dump(mode="json"))


# ------------------------------------------------------------------
# Forgot password (self-service, OTP-based)
# ------------------------------------------------------------------


@router.post("/forgot-password")
async def forgot_password(
    payload: ForgotPasswordRequest,
    auth_service: AuthService = Depends(get_auth_service),
    _rate_limit: None = Depends(enforce_otp_request_rate_limit),
) -> dict:
    """Always the same generic response regardless of whether `email`
    matches an account — see AuthService.request_password_reset's
    docstring. Also this flow's own "resend": re-submitting this same
    request reissues a fresh code once the cooldown elapses, so there is
    no separate PASSWORD_RESET-purpose resend endpoint (see
    ResendSignupOtpRequest's docstring)."""
    await auth_service.request_password_reset(email=payload.email)
    body = GenericOtpMessageResponse(
        message="If an account exists for this email, a reset code has been sent."
    )
    return success_envelope(body.model_dump(mode="json"))


@router.post("/verify-reset-otp")
async def verify_reset_otp(
    payload: VerifyResetOtpRequest,
    auth_service: AuthService = Depends(get_auth_service),
    _rate_limit: None = Depends(enforce_otp_verify_rate_limit),
) -> dict:
    await auth_service.verify_reset_otp(email=payload.email, code=payload.code)
    body = GenericOtpMessageResponse(message="Code verified. You can now set a new password.")
    return success_envelope(body.model_dump(mode="json"))


@router.post("/reset-password")
async def reset_password(
    payload: ResetPasswordRequest,
    auth_service: AuthService = Depends(get_auth_service),
    _rate_limit: None = Depends(enforce_otp_verify_rate_limit),
) -> dict:
    await auth_service.reset_password(
        email=payload.email, code=payload.code, new_password=payload.new_password
    )
    body = GenericOtpMessageResponse(
        message="Password reset. Please sign in with your new password."
    )
    return success_envelope(body.model_dump(mode="json"))

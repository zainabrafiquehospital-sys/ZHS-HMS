"""Full end-to-end HTTP tests for the self-service signup module's
resend-verification-email flow (`POST /auth/resend-otp`) — see
tests/test_auth_endpoints.py's identical module docstring. No prior test
file covered this endpoint at all; scoped here to exactly what it does
(only genuinely `PENDING_EMAIL_VERIFICATION` accounts may resend, and the
per-source-IP rate limit still applies), not the full signup/verify-email
lifecycle, which remains untested elsewhere and out of scope for this
change."""

from app.core.config import get_settings
from app.modules.auth.models import User, UserStatus
from app.modules.auth.password_service import PasswordService
from app.modules.auth.repository import UserRepository
from tests.conftest import make_test_email

_PASSWORD = "Str0ng!Passw0rd#2026"


async def _create_pending_email_verification_user_directly(real_session, suffix: str) -> str:
    """Direct construction rather than going through `POST /auth/signup`
    deliberately: signup itself issues the account's first OTP, and
    resending immediately after would trip `otp_resend_cooldown_seconds`
    (a *separate*, per-account 60s cooldown enforced in `SignupService.
    _issue_otp`, independent of the per-IP `enforce_otp_request_rate_
    limit` this test suite is actually targeting — see that method's
    docstring). A freshly-constructed account has no prior OTP row at
    all, so its first resend is never subject to that cooldown."""
    password_hash = await PasswordService().hash(_PASSWORD)
    email = make_test_email(suffix)
    await UserRepository(real_session).add(
        User(
            email=email,
            password_hash=password_hash,
            full_name="Resend Otp Pending User",
            status=UserStatus.PENDING_EMAIL_VERIFICATION,
        )
    )
    await real_session.commit()
    return email


async def _create_active_user_directly(real_session, suffix: str) -> str:
    password_hash = await PasswordService().hash(_PASSWORD)
    email = make_test_email(suffix)
    await UserRepository(real_session).add(
        User(
            email=email,
            password_hash=password_hash,
            full_name="Resend Otp Active User",
            status=UserStatus.ACTIVE,
            # See tests/test_user_endpoints.py's _create_and_login for
            # why this must be explicit (must_change_password
            # enforcement, 2026-08-19 audit fix pass).
            must_change_password=False,
        )
    )
    await real_session.commit()
    return email


async def test_resend_otp_succeeds_for_pending_email_verification_account(
    api_client, real_session
):
    email = await _create_pending_email_verification_user_directly(real_session, "resend-success")

    resp = await api_client.post("/api/v1/auth/resend-otp", json={"email": email})

    assert resp.status_code == 200
    assert resp.json()["data"]["message"]


async def test_resend_otp_rejects_already_active_account(api_client, real_session):
    """Not just "unverified accounts get a code" — an account that has
    already moved past PENDING_EMAIL_VERIFICATION (active, rejected,
    suspended, etc.) must not be able to trigger a fresh OTP through
    this endpoint at all."""
    email = await _create_active_user_directly(real_session, "resend-already-active")

    resp = await api_client.post("/api/v1/auth/resend-otp", json={"email": email})

    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "OTP_INVALID"


async def test_resend_otp_rejects_unknown_email(api_client):
    resp = await api_client.post(
        "/api/v1/auth/resend-otp", json={"email": make_test_email("resend-unknown")}
    )

    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "OTP_INVALID"


async def test_resend_otp_exceeding_rate_limit_returns_429_with_retry_after(api_client):
    """The rate limit is keyed by source IP and applies regardless of
    whether individual attempts succeed or fail — same property
    test_auth_endpoints.py's `test_login_exceeding_rate_limit_returns_
    429_with_retry_after` already asserts for `/auth/login`, exercised
    here against `/auth/resend-otp` specifically. A nonexistent email is
    enough: `enforce_otp_request_rate_limit` runs before the account
    lookup, so every attempt counts toward the budget whether or not a
    real account is behind it."""
    limit = get_settings().otp_request_rate_limit_attempts
    payload = {"email": make_test_email("resend-rate-limit")}

    for _ in range(limit):
        resp = await api_client.post("/api/v1/auth/resend-otp", json=payload)
        assert resp.status_code == 401

    resp = await api_client.post("/api/v1/auth/resend-otp", json=payload)

    assert resp.status_code == 429
    assert resp.json()["error"]["code"] == "RATE_LIMIT_EXCEEDED"
    assert int(resp.headers["retry-after"]) > 0

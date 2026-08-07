"""Full end-to-end HTTP tests: real ASGI app, real middleware, real
routing, real dependency-injection graph, real Postgres. Only the JWT key
registry and Redis client are substituted (see the `api_client` fixture)
— the same substitution `dependency_overrides` exists for."""

from app.core.config import get_settings
from app.modules.auth.models import User
from app.modules.auth.password_service import PasswordService
from app.modules.auth.repository import UserRepository
from tests.conftest import make_test_email

_PASSWORD = "Str0ng!Passw0rd#2026"


async def _create_user_directly(real_session, suffix: str) -> str:
    """Bypasses the API (no /register endpoint exists — see router.py's
    module docstring) to seed a user for login tests, exactly as an admin
    -provisioning path or seed script would in place of self-registration."""
    password_hash = await PasswordService().hash(_PASSWORD)
    email = make_test_email(suffix)
    user = await UserRepository(real_session).add(
        User(email=email, password_hash=password_hash, full_name="Endpoint Test")
    )
    await real_session.commit()
    return user.email


async def test_login_unknown_user_returns_401_envelope(api_client):
    resp = await api_client.post(
        "/api/v1/auth/login",
        json={"email": make_test_email("nobody"), "password": "whatever12345"},
    )

    assert resp.status_code == 401
    body = resp.json()
    assert body["data"] is None
    assert body["error"]["code"] == "INVALID_CREDENTIALS"


async def test_login_validation_error_returns_422(api_client):
    resp = await api_client.post(
        "/api/v1/auth/login", json={"email": "not-an-email", "password": "x"}
    )

    assert resp.status_code == 422


async def test_login_success_sets_refresh_cookie_and_returns_access_token(api_client, real_session):
    email = await _create_user_directly(real_session, "login-success")

    resp = await api_client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": _PASSWORD, "remember_me": True},
    )

    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["access_token"]
    assert body["token_type"] == "bearer"
    assert body["user"]["email"] == email
    assert "refresh_token" in resp.cookies


async def test_me_requires_authentication(api_client):
    resp = await api_client.get("/api/v1/auth/me")

    assert resp.status_code == 401
    assert resp.headers.get("www-authenticate") == "Bearer"


async def test_me_returns_current_user_with_valid_token(api_client, real_session):
    email = await _create_user_directly(real_session, "me-basic")
    login_resp = await api_client.post(
        "/api/v1/auth/login", json={"email": email, "password": _PASSWORD}
    )
    access_token = login_resp.json()["data"]["access_token"]

    resp = await api_client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {access_token}"}
    )

    assert resp.status_code == 200
    assert resp.json()["data"]["email"] == email


async def test_refresh_without_cookie_returns_401(api_client):
    resp = await api_client.post("/api/v1/auth/refresh")

    assert resp.status_code == 401


async def test_refresh_rotates_cookie_and_access_token(api_client, real_session):
    email = await _create_user_directly(real_session, "refresh-endpoint")
    login_resp = await api_client.post(
        "/api/v1/auth/login", json={"email": email, "password": _PASSWORD}
    )
    original_access_token = login_resp.json()["data"]["access_token"]

    resp = await api_client.post("/api/v1/auth/refresh")

    assert resp.status_code == 200
    assert resp.json()["data"]["access_token"] != original_access_token


async def test_logout_clears_cookie_and_revokes_session(api_client, real_session):
    email = await _create_user_directly(real_session, "logout-endpoint")
    await api_client.post("/api/v1/auth/login", json={"email": email, "password": _PASSWORD})

    logout_resp = await api_client.post("/api/v1/auth/logout")
    assert logout_resp.status_code == 200

    refresh_resp = await api_client.post("/api/v1/auth/refresh")
    assert refresh_resp.status_code == 401


async def test_logout_with_no_session_still_returns_200(api_client):
    resp = await api_client.post("/api/v1/auth/logout")

    assert resp.status_code == 200


async def test_logout_all_requires_authentication(api_client):
    resp = await api_client.post("/api/v1/auth/logout-all")

    assert resp.status_code == 401


async def test_logout_all_revokes_every_session_via_http(api_client, real_session):
    email = await _create_user_directly(real_session, "logout-all-endpoint")
    first_login = await api_client.post(
        "/api/v1/auth/login", json={"email": email, "password": _PASSWORD}
    )
    access_token = first_login.json()["data"]["access_token"]
    first_refresh_cookie = api_client.cookies.get("refresh_token")

    # a second, independent session for the same user
    second_login = await api_client.post(
        "/api/v1/auth/login", json={"email": email, "password": _PASSWORD}
    )
    second_refresh_cookie = second_login.cookies.get("refresh_token")

    resp = await api_client.post(
        "/api/v1/auth/logout-all", headers={"Authorization": f"Bearer {access_token}"}
    )
    assert resp.status_code == 200

    # both sessions' refresh cookies must now be dead
    api_client.cookies.set("refresh_token", first_refresh_cookie)
    assert (await api_client.post("/api/v1/auth/refresh")).status_code == 401
    api_client.cookies.set("refresh_token", second_refresh_cookie)
    assert (await api_client.post("/api/v1/auth/refresh")).status_code == 401


async def test_change_password_requires_authentication(api_client):
    resp = await api_client.post(
        "/api/v1/auth/change-password",
        json={"current_password": _PASSWORD, "new_password": "EvenStr0nger!Pass#2026"},
    )

    assert resp.status_code == 401


async def test_change_password_rejects_weak_new_password_with_422(api_client, real_session):
    email = await _create_user_directly(real_session, "change-pw-weak")
    login_resp = await api_client.post(
        "/api/v1/auth/login", json={"email": email, "password": _PASSWORD}
    )
    access_token = login_resp.json()["data"]["access_token"]

    resp = await api_client.post(
        "/api/v1/auth/change-password",
        json={"current_password": _PASSWORD, "new_password": "short"},
        headers={"Authorization": f"Bearer {access_token}"},
    )

    assert resp.status_code == 422


async def test_change_password_success_revokes_session(api_client, real_session):
    email = await _create_user_directly(real_session, "change-pw-endpoint")
    login_resp = await api_client.post(
        "/api/v1/auth/login", json={"email": email, "password": _PASSWORD}
    )
    access_token = login_resp.json()["data"]["access_token"]

    resp = await api_client.post(
        "/api/v1/auth/change-password",
        json={"current_password": _PASSWORD, "new_password": "EvenStr0nger!Pass#2026"},
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert resp.status_code == 200

    refresh_resp = await api_client.post("/api/v1/auth/refresh")
    assert refresh_resp.status_code == 401

    relogin = await api_client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "EvenStr0nger!Pass#2026"},
    )
    assert relogin.status_code == 200


async def test_login_exceeding_rate_limit_returns_429_with_retry_after(api_client):
    """The rate limit is keyed by source IP and applies regardless of
    whether individual attempts succeed or fail — no real user needs to
    exist for this to trip (see `enforce_login_rate_limit`'s docstring)."""
    limit = get_settings().login_rate_limit_attempts
    payload = {"email": make_test_email("rate-limit"), "password": "wrong-password"}

    for _ in range(limit):
        resp = await api_client.post("/api/v1/auth/login", json=payload)
        assert resp.status_code == 401

    resp = await api_client.post("/api/v1/auth/login", json=payload)

    assert resp.status_code == 429
    assert resp.json()["error"]["code"] == "RATE_LIMIT_EXCEEDED"
    assert int(resp.headers["retry-after"]) > 0

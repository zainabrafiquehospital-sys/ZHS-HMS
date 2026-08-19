"""Full end-to-end HTTP tests for the Dashboard module — see
tests/test_patients_endpoints.py's identical module docstring."""

from app.modules.auth.models import User, UserStatus
from app.modules.auth.password_service import PasswordService
from app.modules.auth.repository import UserRepository
from app.modules.dashboard.constants import (
    PERMISSION_DASHBOARD_DOCTOR_READ,
    PERMISSION_DASHBOARD_RECEPTION_READ,
    PERMISSION_DASHBOARD_VITALS_READ,
)
from tests.conftest import make_test_email

_PASSWORD = "Str0ng!Passw0rd#2026"


async def _create_and_login(api_client, real_session, suffix: str) -> tuple[User, str]:
    password_hash = await PasswordService().hash(_PASSWORD)
    email = make_test_email(suffix)
    user = await UserRepository(real_session).add(
        User(
            email=email,
            password_hash=password_hash,
            full_name="Dashboard Endpoint Actor",
            status=UserStatus.ACTIVE,
            # See tests/test_user_endpoints.py's _create_and_login for
            # why this must be explicit (must_change_password
            # enforcement, 2026-08-19 audit fix pass).
            must_change_password=False,
        )
    )
    await real_session.commit()
    login_resp = await api_client.post(
        "/api/v1/auth/login", json={"email": email, "password": _PASSWORD}
    )
    access_token = login_resp.json()["data"]["access_token"]
    return user, access_token


def _auth_header(access_token: str) -> dict:
    return {"Authorization": f"Bearer {access_token}"}


async def test_reception_dashboard_requires_authentication(api_client):
    resp = await api_client.get("/api/v1/dashboard/reception")
    assert resp.status_code == 401


async def test_reception_dashboard_without_permission_is_forbidden(api_client, real_session):
    _actor, access_token = await _create_and_login(api_client, real_session, "no-perm-reception")

    resp = await api_client.get("/api/v1/dashboard/reception", headers=_auth_header(access_token))

    assert resp.status_code == 403


async def test_reception_dashboard_success(api_client, real_session, grant_permission):
    actor, access_token = await _create_and_login(api_client, real_session, "reception-success")
    await grant_permission(actor, PERMISSION_DASHBOARD_RECEPTION_READ)

    resp = await api_client.get("/api/v1/dashboard/reception", headers=_auth_header(access_token))

    assert resp.status_code == 200
    body = resp.json()["data"]
    assert "visits_by_status" in body
    assert "queue_waiting_by_destination" in body
    assert "revenue_collected_today" in body


async def test_doctor_dashboard_requires_own_permission(api_client, real_session, grant_permission):
    actor, access_token = await _create_and_login(api_client, real_session, "doctor-perm")
    await grant_permission(actor, PERMISSION_DASHBOARD_DOCTOR_READ)

    resp = await api_client.get("/api/v1/dashboard/doctor", headers=_auth_header(access_token))

    assert resp.status_code == 200
    body = resp.json()["data"]
    assert "waiting_count" in body
    assert "in_consultation_count" in body


async def test_vitals_dashboard_success(api_client, real_session, grant_permission):
    actor, access_token = await _create_and_login(api_client, real_session, "vitals-success")
    await grant_permission(actor, PERMISSION_DASHBOARD_VITALS_READ)

    resp = await api_client.get("/api/v1/dashboard/vitals", headers=_auth_header(access_token))

    assert resp.status_code == 200
    assert "waiting_count" in resp.json()["data"]


async def test_dashboards_are_independently_gated(api_client, real_session, grant_permission):
    """Holding one dashboard's permission must not grant access to
    another (Phase 6 §22: "each dashboard only displays data allowed by
    RBAC")."""
    actor, access_token = await _create_and_login(api_client, real_session, "cross-gate")
    await grant_permission(actor, PERMISSION_DASHBOARD_RECEPTION_READ)

    doctor_resp = await api_client.get(
        "/api/v1/dashboard/doctor", headers=_auth_header(access_token)
    )
    vitals_resp = await api_client.get(
        "/api/v1/dashboard/vitals", headers=_auth_header(access_token)
    )

    assert doctor_resp.status_code == 403
    assert vitals_resp.status_code == 403

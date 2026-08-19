"""Full end-to-end HTTP tests for the Search module — see
tests/test_patients_endpoints.py's identical module docstring."""

from app.modules.auth.models import User, UserStatus
from app.modules.auth.password_service import PasswordService
from app.modules.auth.repository import UserRepository
from app.modules.patients.models import PatientGender
from app.modules.search.constants import PERMISSION_SEARCH_READ
from tests.conftest import TEST_PATIENT_NAME_PREFIX, make_test_email

_PASSWORD = "Str0ng!Passw0rd#2026"


async def _create_and_login(api_client, real_session, suffix: str) -> tuple[User, str]:
    password_hash = await PasswordService().hash(_PASSWORD)
    email = make_test_email(suffix)
    user = await UserRepository(real_session).add(
        User(
            email=email,
            password_hash=password_hash,
            full_name="Search Endpoint Actor",
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


async def test_search_requires_authentication(api_client):
    resp = await api_client.get("/api/v1/search", params={"query": "x"})
    assert resp.status_code == 401


async def test_search_without_permission_is_forbidden(api_client, real_session):
    _actor, access_token = await _create_and_login(api_client, real_session, "no-perm-search")

    resp = await api_client.get(
        "/api/v1/search", params={"query": "x"}, headers=_auth_header(access_token)
    )

    assert resp.status_code == 403


async def test_search_success_finds_patient(
    api_client, real_session, grant_permission, patient_service
):
    actor, access_token = await _create_and_login(api_client, real_session, "search-success")
    await grant_permission(actor, PERMISSION_SEARCH_READ)
    unique_name = f"{TEST_PATIENT_NAME_PREFIX}SearchHttp"
    await patient_service.register_patient(
        actor=actor,
        full_name=unique_name,
        guardian_name=None,
        gender=PatientGender.FEMALE,
        age_years=27,
        phone_number="03001234567",
        cnic=None,
        address=None,
    )

    resp = await api_client.get(
        "/api/v1/search", params={"query": unique_name}, headers=_auth_header(access_token)
    )

    assert resp.status_code == 200
    body = resp.json()["data"]
    assert len(body["patients"]) == 1
    assert body["patients"][0]["full_name"] == unique_name
    assert body["visit"] is None

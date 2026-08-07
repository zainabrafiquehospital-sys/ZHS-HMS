"""Full end-to-end HTTP tests for the Patient module: real ASGI app, real
routing, real dependency-injection graph, real Postgres — same style as
tests/test_role_endpoints.py, using the `grant_permission` fixture for
genuine RBAC state rather than bypassing authorization."""

from uuid6 import uuid7

from app.modules.auth.models import User, UserStatus
from app.modules.auth.password_service import PasswordService
from app.modules.auth.repository import UserRepository
from app.modules.patients.constants import (
    PERMISSION_PATIENTS_CREATE,
    PERMISSION_PATIENTS_READ,
    PERMISSION_PATIENTS_UPDATE,
)
from tests.conftest import TEST_PATIENT_NAME_PREFIX, make_test_email

_PASSWORD = "Str0ng!Passw0rd#2026"


async def _create_and_login(api_client, real_session, suffix: str) -> tuple[User, str]:
    password_hash = await PasswordService().hash(_PASSWORD)
    email = make_test_email(suffix)
    user = await UserRepository(real_session).add(
        User(
            email=email,
            password_hash=password_hash,
            full_name="Patient Endpoint Actor",
            status=UserStatus.ACTIVE,
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


def _valid_payload(name: str, **overrides) -> dict:
    payload = {
        "full_name": name,
        "guardian_name": "Father Name",
        "gender": "female",
        "age_years": 30,
        "phone_number": "03001234567",
        "cnic": None,
        "address": "Test Street",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------


async def test_register_patient_requires_authentication(api_client):
    resp = await api_client.post(
        "/api/v1/patients", json=_valid_payload(f"{TEST_PATIENT_NAME_PREFIX}NoAuth")
    )

    assert resp.status_code == 401


async def test_register_patient_without_permission_is_forbidden(api_client, real_session):
    _actor, access_token = await _create_and_login(api_client, real_session, "no-perm-patient")

    resp = await api_client.post(
        "/api/v1/patients",
        json=_valid_payload(f"{TEST_PATIENT_NAME_PREFIX}NoPerm"),
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "PERMISSION_DENIED"


# ---------------------------------------------------------------------
# Register / Get / List / Update
# ---------------------------------------------------------------------


async def test_register_patient_success(api_client, real_session, grant_permission):
    actor, access_token = await _create_and_login(api_client, real_session, "register-patient")
    await grant_permission(actor, PERMISSION_PATIENTS_CREATE)

    resp = await api_client.post(
        "/api/v1/patients",
        json=_valid_payload(f"{TEST_PATIENT_NAME_PREFIX}Register"),
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 201
    body = resp.json()["data"]
    assert body["full_name"] == f"{TEST_PATIENT_NAME_PREFIX}Register"
    assert body["mr_number"].startswith("MR-")


async def test_register_patient_missing_age_years_returns_422(
    api_client, real_session, grant_permission
):
    actor, access_token = await _create_and_login(api_client, real_session, "missing-age")
    await grant_permission(actor, PERMISSION_PATIENTS_CREATE)
    payload = _valid_payload(f"{TEST_PATIENT_NAME_PREFIX}MissingAge")
    del payload["age_years"]

    resp = await api_client.post(
        "/api/v1/patients",
        json=payload,
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 422


async def test_register_patient_age_out_of_range_returns_422(
    api_client, real_session, grant_permission
):
    actor, access_token = await _create_and_login(api_client, real_session, "age-out-of-range")
    await grant_permission(actor, PERMISSION_PATIENTS_CREATE)

    resp = await api_client.post(
        "/api/v1/patients",
        json=_valid_payload(f"{TEST_PATIENT_NAME_PREFIX}AgeOutOfRange", age_years=200),
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 422


async def test_list_patients_returns_pagination_meta(api_client, real_session, grant_permission):
    actor, access_token = await _create_and_login(api_client, real_session, "list-patients")
    await grant_permission(actor, PERMISSION_PATIENTS_READ)
    await grant_permission(actor, PERMISSION_PATIENTS_CREATE)
    name = f"{TEST_PATIENT_NAME_PREFIX}List"
    await api_client.post(
        "/api/v1/patients", json=_valid_payload(name), headers=_auth_header(access_token)
    )

    resp = await api_client.get(
        "/api/v1/patients",
        params={"page": 1, "page_size": 5, "search": name},
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["meta"]["page"] == 1
    assert body["meta"]["total"] == 1
    assert body["data"][0]["full_name"] == name


async def test_get_patient_returns_404_for_unknown_id(api_client, real_session, grant_permission):
    actor, access_token = await _create_and_login(api_client, real_session, "get-patient-404")
    await grant_permission(actor, PERMISSION_PATIENTS_READ)

    resp = await api_client.get(f"/api/v1/patients/{uuid7()}", headers=_auth_header(access_token))

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "PATIENT_NOT_FOUND"


async def test_update_patient_changes_address(api_client, real_session, grant_permission):
    actor, access_token = await _create_and_login(api_client, real_session, "update-patient")
    await grant_permission(actor, PERMISSION_PATIENTS_CREATE)
    await grant_permission(actor, PERMISSION_PATIENTS_UPDATE)
    create_resp = await api_client.post(
        "/api/v1/patients",
        json=_valid_payload(f"{TEST_PATIENT_NAME_PREFIX}UpdateAddr"),
        headers=_auth_header(access_token),
    )
    patient_id = create_resp.json()["data"]["id"]

    resp = await api_client.patch(
        f"/api/v1/patients/{patient_id}",
        json={"address": "New Address"},
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 200
    assert resp.json()["data"]["address"] == "New Address"

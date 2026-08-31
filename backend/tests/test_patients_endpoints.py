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


# ---------------------------------------------------------------------
# Exact phone-number lookup (2026-08-31 addition, Feature 2's
# returning-patient detection) — GET /patients/lookup/by-phone
# ---------------------------------------------------------------------


async def test_find_by_phone_requires_authentication(api_client):
    resp = await api_client.get(
        "/api/v1/patients/lookup/by-phone", params={"phone_number": "03001234567"}
    )

    assert resp.status_code == 401


async def test_find_by_phone_without_permission_is_forbidden(api_client, real_session):
    _actor, access_token = await _create_and_login(api_client, real_session, "no-perm-phone")

    resp = await api_client.get(
        "/api/v1/patients/lookup/by-phone",
        params={"phone_number": "03001234567"},
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 403


async def test_find_by_phone_returns_empty_list_for_no_match(
    api_client, real_session, grant_permission
):
    actor, access_token = await _create_and_login(api_client, real_session, "phone-no-match")
    await grant_permission(actor, PERMISSION_PATIENTS_READ)

    resp = await api_client.get(
        "/api/v1/patients/lookup/by-phone",
        params={"phone_number": "03009999999"},
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 200
    assert resp.json()["data"] == []


async def test_find_by_phone_exact_match_only_not_partial(
    api_client, real_session, grant_permission
):
    """A number that merely *contains* the typed digits as a substring
    must never match — this is the whole reason this endpoint exists
    separately from `search`'s own fuzzy ILIKE (see PatientRepository.
    list_by_phone_number's own docstring)."""
    actor, access_token = await _create_and_login(api_client, real_session, "phone-exact-only")
    await grant_permission(actor, PERMISSION_PATIENTS_CREATE)
    await grant_permission(actor, PERMISSION_PATIENTS_READ)
    # A number unique to this test run, not a fixed literal — this
    # suite runs against a real, persistent, shared dev database (see
    # tests/conftest.py's own module docstring on `real_session`), so a
    # hardcoded phone number risks colliding with genuinely unrelated
    # rows already on file from other tests/manual use.
    full_number = f"03{uuid7().hex[:9]}"
    await api_client.post(
        "/api/v1/patients",
        json=_valid_payload(f"{TEST_PATIENT_NAME_PREFIX}PhoneExact", phone_number=full_number),
        headers=_auth_header(access_token),
    )

    exact_resp = await api_client.get(
        "/api/v1/patients/lookup/by-phone",
        params={"phone_number": full_number},
        headers=_auth_header(access_token),
    )
    partial_resp = await api_client.get(
        "/api/v1/patients/lookup/by-phone",
        params={"phone_number": full_number[:-1]},
        headers=_auth_header(access_token),
    )

    assert len(exact_resp.json()["data"]) == 1
    assert exact_resp.json()["data"][0]["phone_number"] == full_number
    assert partial_resp.json()["data"] == []


async def test_find_by_phone_returns_every_match_for_a_shared_number(
    api_client, real_session, grant_permission
):
    """Family members sharing a household number — the multi-match case
    ReturningPatientDialog.jsx's own list rendering exists for."""
    actor, access_token = await _create_and_login(api_client, real_session, "phone-shared")
    await grant_permission(actor, PERMISSION_PATIENTS_CREATE)
    await grant_permission(actor, PERMISSION_PATIENTS_READ)
    # Unique to this test run — see test_find_by_phone_exact_match_only_not_partial's
    # identical comment above on why a fixed literal is unsafe here.
    shared_number = f"03{uuid7().hex[:9]}"
    for name_suffix in ("SharedOne", "SharedTwo"):
        await api_client.post(
            "/api/v1/patients",
            json=_valid_payload(
                f"{TEST_PATIENT_NAME_PREFIX}{name_suffix}", phone_number=shared_number
            ),
            headers=_auth_header(access_token),
        )

    resp = await api_client.get(
        "/api/v1/patients/lookup/by-phone",
        params={"phone_number": shared_number},
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 200
    names = {row["full_name"] for row in resp.json()["data"]}
    assert names == {
        f"{TEST_PATIENT_NAME_PREFIX}SharedOne",
        f"{TEST_PATIENT_NAME_PREFIX}SharedTwo",
    }


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

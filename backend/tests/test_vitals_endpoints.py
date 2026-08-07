"""Full end-to-end HTTP tests for the Vitals module — see
tests/test_patients_endpoints.py's identical module docstring."""

from decimal import Decimal

from app.modules.auth.models import User, UserStatus
from app.modules.auth.password_service import PasswordService
from app.modules.auth.repository import UserRepository
from app.modules.patients.models import PatientGender
from app.modules.vitals.constants import PERMISSION_VITALS_READ, PERMISSION_VITALS_RECORD
from tests.conftest import TEST_PATIENT_NAME_PREFIX, make_test_email

_PASSWORD = "Str0ng!Passw0rd#2026"


async def _create_and_login(api_client, real_session, suffix: str) -> tuple[User, str]:
    password_hash = await PasswordService().hash(_PASSWORD)
    email = make_test_email(suffix)
    user = await UserRepository(real_session).add(
        User(
            email=email,
            password_hash=password_hash,
            full_name="Vitals Endpoint Actor",
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


async def _make_visit(reception_service, doctor, suffix: str, vitals_required: bool):
    _patient, visit, _entry = await reception_service.register_visit(
        actor=doctor,
        patient_id=None,
        new_patient={
            "full_name": f"{TEST_PATIENT_NAME_PREFIX}VitalsHttp{suffix}",
            "guardian_name": None,
            "gender": PatientGender.FEMALE,
            "age_years": 31,
            "phone_number": "03001234567",
            "cnic": None,
            "address": None,
        },
        doctor_user_id=doctor.id,
        procedure="Consultation",
        amount=Decimal("1500.00"),
        vitals_required=vitals_required,
    )
    return visit


async def test_record_vitals_requires_authentication(api_client):
    resp = await api_client.post("/api/v1/vitals", json={"visit_id": None})
    assert resp.status_code in (401, 422)


async def test_record_vitals_without_permission_is_forbidden(
    api_client, real_session, reception_service
):
    doctor, access_token = await _create_and_login(api_client, real_session, "no-perm-record")
    visit = await _make_visit(reception_service, doctor, "A", vitals_required=True)

    resp = await api_client.post(
        "/api/v1/vitals",
        json={"visit_id": str(visit.id), "systolic_bp": 120, "diastolic_bp": 80},
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 403


async def test_record_vitals_success_routes_to_doctor(
    api_client, real_session, grant_permission, reception_service
):
    doctor, access_token = await _create_and_login(api_client, real_session, "record-success")
    await grant_permission(doctor, PERMISSION_VITALS_RECORD)
    visit = await _make_visit(reception_service, doctor, "Success", vitals_required=True)

    resp = await api_client.post(
        "/api/v1/vitals",
        json={
            "visit_id": str(visit.id),
            "systolic_bp": 118,
            "diastolic_bp": 76,
            "pulse_rate": 70,
            "temperature_celsius": 36.9,
            "spo2_percent": 99,
        },
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 201
    body = resp.json()["data"]
    assert body["systolic_bp"] == 118
    assert body["consultation_id"] is None

    visit_resp = await api_client.get(
        f"/api/v1/visits/{visit.id}", headers=_auth_header(access_token)
    )
    assert visit_resp.status_code == 403  # no visits:read granted — proves RBAC isolation


async def test_record_vitals_out_of_range_returns_422(
    api_client, real_session, grant_permission, reception_service
):
    doctor, access_token = await _create_and_login(api_client, real_session, "out-of-range")
    await grant_permission(doctor, PERMISSION_VITALS_RECORD)
    visit = await _make_visit(reception_service, doctor, "Range", vitals_required=True)

    resp = await api_client.post(
        "/api/v1/vitals",
        json={"visit_id": str(visit.id), "spo2_percent": 150},
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 422


async def test_list_for_visit_returns_recorded_entries(
    api_client, real_session, grant_permission, reception_service
):
    doctor, access_token = await _create_and_login(api_client, real_session, "list-vitals")
    await grant_permission(doctor, PERMISSION_VITALS_RECORD)
    await grant_permission(doctor, PERMISSION_VITALS_READ)
    visit = await _make_visit(reception_service, doctor, "List", vitals_required=True)
    await api_client.post(
        "/api/v1/vitals",
        json={"visit_id": str(visit.id), "systolic_bp": 115, "diastolic_bp": 75},
        headers=_auth_header(access_token),
    )

    resp = await api_client.get(
        f"/api/v1/vitals/visits/{visit.id}", headers=_auth_header(access_token)
    )

    assert resp.status_code == 200
    assert len(resp.json()["data"]) == 1
    assert resp.json()["data"][0]["systolic_bp"] == 115

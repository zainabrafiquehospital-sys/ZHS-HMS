"""Full end-to-end HTTP tests for the Consultation module — see
tests/test_patients_endpoints.py's identical module docstring."""

from decimal import Decimal

from app.modules.auth.models import User, UserStatus
from app.modules.auth.password_service import PasswordService
from app.modules.auth.repository import UserRepository
from app.modules.consultation.constants import (
    PERMISSION_CONSULTATION_MANAGE,
    PERMISSION_CONSULTATION_READ,
    PERMISSION_CONSULTATION_START,
)
from app.modules.patients.models import PatientGender
from tests.conftest import TEST_PATIENT_NAME_PREFIX, make_test_email

_PASSWORD = "Str0ng!Passw0rd#2026"


async def _create_and_login(api_client, real_session, suffix: str) -> tuple[User, str]:
    password_hash = await PasswordService().hash(_PASSWORD)
    email = make_test_email(suffix)
    user = await UserRepository(real_session).add(
        User(
            email=email,
            password_hash=password_hash,
            full_name="Consultation Endpoint Actor",
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


async def _make_visit(reception_service, doctor, suffix: str):
    """Goes through ReceptionService — see
    tests/test_consultation_service.py's identical helper docstring for
    why VisitService.register_visit alone is not enough (no QueueEntry
    would ever be created)."""
    _patient, visit, _entry = await reception_service.register_visit(
        actor=doctor,
        patient_id=None,
        new_patient={
            "full_name": f"{TEST_PATIENT_NAME_PREFIX}ConsultationHttp{suffix}",
            "guardian_name": None,
            "gender": PatientGender.FEMALE,
            "age_years": 33,
            "phone_number": "03001234567",
            "cnic": None,
            "address": None,
        },
        doctor_user_id=doctor.id,
        procedures=[(None, "Consultation", Decimal("1500.00"))],
        vitals_required=False,
    )
    return visit


async def test_start_consultation_requires_authentication(api_client):
    resp = await api_client.post("/api/v1/consultations", json={"visit_id": None})
    assert resp.status_code in (401, 422)


async def test_start_consultation_without_permission_is_forbidden(
    api_client, real_session, reception_service
):
    doctor, access_token = await _create_and_login(api_client, real_session, "no-perm-start")
    visit = await _make_visit(reception_service, doctor, "A")

    resp = await api_client.post(
        "/api/v1/consultations",
        json={"visit_id": str(visit.id)},
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 403


async def test_full_consultation_lifecycle_via_http(
    api_client, real_session, grant_permission, reception_service
):
    doctor, access_token = await _create_and_login(api_client, real_session, "full-lifecycle")
    await grant_permission(doctor, PERMISSION_CONSULTATION_START)
    await grant_permission(doctor, PERMISSION_CONSULTATION_MANAGE)
    await grant_permission(doctor, PERMISSION_CONSULTATION_READ)
    visit = await _make_visit(reception_service, doctor, "Full")

    start_resp = await api_client.post(
        "/api/v1/consultations",
        json={"visit_id": str(visit.id)},
        headers=_auth_header(access_token),
    )
    assert start_resp.status_code == 201
    consultation_id = start_resp.json()["data"]["id"]
    assert start_resp.json()["data"]["status"] == "in_progress"

    send_resp = await api_client.post(
        f"/api/v1/consultations/{consultation_id}/send-to-vitals",
        json={"reason": "BP check"},
        headers=_auth_header(access_token),
    )
    assert send_resp.status_code == 200
    assert send_resp.json()["data"]["status"] == "awaiting_vitals"

    complete_while_awaiting = await api_client.post(
        f"/api/v1/consultations/{consultation_id}/complete",
        json={},
        headers=_auth_header(access_token),
    )
    assert complete_while_awaiting.status_code == 422

    active_resp = await api_client.get(
        f"/api/v1/consultations/visits/{visit.id}/active", headers=_auth_header(access_token)
    )
    assert active_resp.status_code == 200
    assert active_resp.json()["data"]["status"] == "awaiting_vitals"


async def test_get_consultation_stats_by_doctor_requires_permission(api_client, real_session):
    _actor, access_token = await _create_and_login(api_client, real_session, "stats-no-perm")

    resp = await api_client.get(
        "/api/v1/consultations/stats/by-doctor", headers=_auth_header(access_token)
    )

    assert resp.status_code == 403


async def test_get_consultation_stats_by_doctor_returns_accurate_counts(
    api_client, real_session, grant_permission, reception_service
):
    doctor, access_token = await _create_and_login(api_client, real_session, "stats-correctness")
    await grant_permission(doctor, PERMISSION_CONSULTATION_START)
    await grant_permission(doctor, PERMISSION_CONSULTATION_MANAGE)
    await grant_permission(doctor, PERMISSION_CONSULTATION_READ)
    visit = await _make_visit(reception_service, doctor, "StatsCorrectness")
    start_resp = await api_client.post(
        "/api/v1/consultations",
        json={"visit_id": str(visit.id)},
        headers=_auth_header(access_token),
    )
    consultation_id = start_resp.json()["data"]["id"]
    complete_resp = await api_client.post(
        f"/api/v1/consultations/{consultation_id}/complete",
        json={"diagnosis": "Healthy", "prescription": "None"},
        headers=_auth_header(access_token),
    )
    assert complete_resp.status_code == 200

    resp = await api_client.get(
        "/api/v1/consultations/stats/by-doctor", headers=_auth_header(access_token)
    )

    assert resp.status_code == 200
    rows = {row["user_id"]: row["count"] for row in resp.json()["data"]}
    assert rows[str(doctor.id)] == 1


async def test_complete_consultation_success_via_http(
    api_client, real_session, grant_permission, reception_service
):
    doctor, access_token = await _create_and_login(api_client, real_session, "complete-http")
    await grant_permission(doctor, PERMISSION_CONSULTATION_START)
    await grant_permission(doctor, PERMISSION_CONSULTATION_MANAGE)
    visit = await _make_visit(reception_service, doctor, "Complete")
    start_resp = await api_client.post(
        "/api/v1/consultations",
        json={"visit_id": str(visit.id)},
        headers=_auth_header(access_token),
    )
    consultation_id = start_resp.json()["data"]["id"]

    resp = await api_client.post(
        f"/api/v1/consultations/{consultation_id}/complete",
        json={"diagnosis": "Healthy", "prescription": "None"},
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "completed"

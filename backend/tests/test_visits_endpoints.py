"""Full end-to-end HTTP tests for the Visit module's read-only endpoints
— see tests/test_patients_endpoints.py's identical module docstring."""

from decimal import Decimal

from uuid6 import uuid7

from app.modules.auth.models import User, UserStatus
from app.modules.auth.password_service import PasswordService
from app.modules.auth.repository import UserRepository
from app.modules.patients.models import PatientGender
from app.modules.visits.constants import PERMISSION_VISITS_READ
from tests.conftest import TEST_PATIENT_NAME_PREFIX, make_test_email

_PASSWORD = "Str0ng!Passw0rd#2026"


async def _create_and_login(api_client, real_session, suffix: str) -> tuple[User, str]:
    password_hash = await PasswordService().hash(_PASSWORD)
    email = make_test_email(suffix)
    user = await UserRepository(real_session).add(
        User(
            email=email,
            password_hash=password_hash,
            full_name="Visit Endpoint Actor",
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


async def test_list_visits_requires_authentication(api_client):
    resp = await api_client.get("/api/v1/visits")
    assert resp.status_code == 401


async def test_get_visit_returns_404_for_unknown_id(api_client, real_session, grant_permission):
    actor, access_token = await _create_and_login(api_client, real_session, "get-visit-404")
    await grant_permission(actor, PERMISSION_VISITS_READ)

    resp = await api_client.get(f"/api/v1/visits/{uuid7()}", headers=_auth_header(access_token))

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "VISIT_NOT_FOUND"


async def test_get_visit_returns_registered_visit(
    api_client, real_session, grant_permission, patient_service, visit_service
):
    actor, access_token = await _create_and_login(api_client, real_session, "get-visit-success")
    await grant_permission(actor, PERMISSION_VISITS_READ)
    patient = await patient_service.register_patient(
        actor=actor,
        full_name=f"{TEST_PATIENT_NAME_PREFIX}VisitEndpoint",
        guardian_name=None,
        gender=PatientGender.FEMALE,
        age_years=25,
        phone_number="03001234567",
        cnic=None,
        address=None,
    )
    visit = await visit_service.register_visit(
        actor=actor,
        patient_id=patient.id,
        doctor_user_id=actor.id,
        procedure="Consultation",
        amount=Decimal("1500.00"),
        vitals_required=False,
    )

    resp = await api_client.get(f"/api/v1/visits/{visit.id}", headers=_auth_header(access_token))

    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["queue_token"] == visit.queue_token
    assert body["status"] == "waiting_doctor"


async def test_get_visit_stats_by_creator_requires_permission(api_client, real_session):
    _actor, access_token = await _create_and_login(api_client, real_session, "stats-no-perm")

    resp = await api_client.get(
        "/api/v1/visits/stats/by-creator", headers=_auth_header(access_token)
    )

    assert resp.status_code == 403


async def test_get_visit_stats_by_creator_returns_accurate_counts(
    api_client, real_session, grant_permission, patient_service, visit_service
):
    actor, access_token = await _create_and_login(api_client, real_session, "stats-correctness")
    await grant_permission(actor, PERMISSION_VISITS_READ)
    patient = await patient_service.register_patient(
        actor=actor,
        full_name=f"{TEST_PATIENT_NAME_PREFIX}VisitStats",
        guardian_name=None,
        gender=PatientGender.FEMALE,
        age_years=28,
        phone_number="03001234567",
        cnic=None,
        address=None,
    )
    for _ in range(3):
        await visit_service.register_visit(
            actor=actor,
            patient_id=patient.id,
            doctor_user_id=actor.id,
            procedure="Consultation",
            amount=Decimal("1500.00"),
            vitals_required=False,
        )

    resp = await api_client.get(
        "/api/v1/visits/stats/by-creator", headers=_auth_header(access_token)
    )

    assert resp.status_code == 200
    rows = {row["user_id"]: row["count"] for row in resp.json()["data"]}
    assert rows[str(actor.id)] == 3


async def test_list_visits_filters_by_patient_id_and_returns_pagination_meta(
    api_client, real_session, grant_permission, patient_service, visit_service
):
    actor, access_token = await _create_and_login(api_client, real_session, "list-visits")
    await grant_permission(actor, PERMISSION_VISITS_READ)
    patient = await patient_service.register_patient(
        actor=actor,
        full_name=f"{TEST_PATIENT_NAME_PREFIX}VisitList",
        guardian_name=None,
        gender=PatientGender.FEMALE,
        age_years=31,
        phone_number="03001234567",
        cnic=None,
        address=None,
    )
    other_patient = await patient_service.register_patient(
        actor=actor,
        full_name=f"{TEST_PATIENT_NAME_PREFIX}VisitListOther",
        guardian_name=None,
        gender=PatientGender.FEMALE,
        age_years=31,
        phone_number="03001234567",
        cnic=None,
        address=None,
    )
    visit = await visit_service.register_visit(
        actor=actor,
        patient_id=patient.id,
        doctor_user_id=actor.id,
        procedure="Consultation",
        amount=Decimal("1500.00"),
        vitals_required=False,
    )
    await visit_service.register_visit(
        actor=actor,
        patient_id=other_patient.id,
        doctor_user_id=actor.id,
        procedure="Consultation",
        amount=Decimal("1500.00"),
        vitals_required=False,
    )

    resp = await api_client.get(
        "/api/v1/visits",
        params={"page": 1, "page_size": 10, "patient_id": str(patient.id)},
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["meta"]["total"] == 1
    assert body["data"][0]["id"] == str(visit.id)

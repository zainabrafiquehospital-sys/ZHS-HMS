"""Full end-to-end HTTP tests for the Queue module — see
tests/test_patients_endpoints.py's identical module docstring."""

from decimal import Decimal

from uuid6 import uuid7

from app.modules.auth.models import User, UserStatus
from app.modules.auth.password_service import PasswordService
from app.modules.auth.repository import UserRepository
from app.modules.patients.models import PatientGender
from app.modules.queue.constants import PERMISSION_QUEUE_MANAGE, PERMISSION_QUEUE_READ
from app.modules.queue.models import QueueDestination
from app.shared.payment_method import PaymentMethod
from tests.conftest import TEST_PATIENT_NAME_PREFIX, make_test_email

_PASSWORD = "Str0ng!Passw0rd#2026"


async def _create_and_login(api_client, real_session, suffix: str) -> tuple[User, str]:
    password_hash = await PasswordService().hash(_PASSWORD)
    email = make_test_email(suffix)
    user = await UserRepository(real_session).add(
        User(
            email=email,
            password_hash=password_hash,
            full_name="Queue Endpoint Actor",
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


async def _make_visit(patient_service, visit_service, actor, suffix: str):
    patient = await patient_service.register_patient(
        actor=actor,
        full_name=f"{TEST_PATIENT_NAME_PREFIX}QueueEndpoint{suffix}",
        guardian_name=None,
        gender=PatientGender.FEMALE,
        age_years=29,
        phone_number="03001234567",
        cnic=None,
        address=None,
    )
    return await visit_service.register_visit(
        actor=actor,
        patient_id=patient.id,
        doctor_user_id=actor.id,
        procedures=[(None, "Consultation", Decimal("1500.00"))],
        vitals_required=False,
        initial_payment_amount=Decimal("0.01"),
        initial_payment_method=PaymentMethod.CASH,
    )


async def test_worklist_requires_authentication(api_client):
    resp = await api_client.get("/api/v1/queue/worklist", params={"destination": "doctor"})
    assert resp.status_code == 401


async def test_worklist_without_permission_is_forbidden(api_client, real_session):
    _actor, access_token = await _create_and_login(api_client, real_session, "no-perm-worklist")

    resp = await api_client.get(
        "/api/v1/queue/worklist",
        params={"destination": "doctor"},
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 403


async def test_worklist_returns_routed_visit(
    api_client, real_session, grant_permission, patient_service, visit_service, queue_service
):
    actor, access_token = await _create_and_login(api_client, real_session, "worklist-success")
    await grant_permission(actor, PERMISSION_QUEUE_READ)
    visit = await _make_visit(patient_service, visit_service, actor, "A")
    entry = await queue_service.route_to(
        actor=actor, visit_id=visit.id, destination=QueueDestination.DOCTOR
    )

    resp = await api_client.get(
        "/api/v1/queue/worklist",
        params={"destination": "doctor", "status": "waiting"},
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 200
    body = resp.json()
    ids = [row["id"] for row in body["data"]]
    assert str(entry.id) in ids


async def test_get_active_entry_returns_null_when_none(api_client, real_session, grant_permission):
    actor, access_token = await _create_and_login(api_client, real_session, "active-null")
    await grant_permission(actor, PERMISSION_QUEUE_READ)

    resp = await api_client.get(
        f"/api/v1/queue/visits/{uuid7()}/active", headers=_auth_header(access_token)
    )

    assert resp.status_code == 200
    assert resp.json()["data"] is None


async def test_start_serving_requires_manage_permission(
    api_client, real_session, grant_permission, patient_service, visit_service, queue_service
):
    actor, access_token = await _create_and_login(api_client, real_session, "start-serving-403")
    await grant_permission(actor, PERMISSION_QUEUE_READ)
    visit = await _make_visit(patient_service, visit_service, actor, "B")
    entry = await queue_service.route_to(
        actor=actor, visit_id=visit.id, destination=QueueDestination.DOCTOR
    )

    resp = await api_client.post(
        f"/api/v1/queue/entries/{entry.id}/start", headers=_auth_header(access_token)
    )

    assert resp.status_code == 403


async def test_start_serving_success(
    api_client, real_session, grant_permission, patient_service, visit_service, queue_service
):
    actor, access_token = await _create_and_login(api_client, real_session, "start-serving-200")
    await grant_permission(actor, PERMISSION_QUEUE_MANAGE)
    visit = await _make_visit(patient_service, visit_service, actor, "C")
    entry = await queue_service.route_to(
        actor=actor, visit_id=visit.id, destination=QueueDestination.DOCTOR
    )

    resp = await api_client.post(
        f"/api/v1/queue/entries/{entry.id}/start", headers=_auth_header(access_token)
    )

    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "in_progress"

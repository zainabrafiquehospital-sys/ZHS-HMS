"""Full end-to-end HTTP tests for the Reception module — see
tests/test_patients_endpoints.py's identical module docstring."""

from app.modules.auth.models import User, UserStatus
from app.modules.auth.password_service import PasswordService
from app.modules.auth.repository import UserRepository
from app.modules.consultation.constants import PERMISSION_CONSULTATION_START
from app.modules.reception.constants import (
    PERMISSION_RECEPTION_CANCEL_VISIT,
    PERMISSION_RECEPTION_REGISTER_VISIT,
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
            full_name="Reception Endpoint Actor",
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


def _new_patient_body(suffix: str) -> dict:
    return {
        "full_name": f"{TEST_PATIENT_NAME_PREFIX}ReceptionHttp{suffix}",
        "guardian_name": None,
        "gender": "female",
        "age_years": 36,
        "phone_number": "03001234567",
        "cnic": None,
        "address": None,
    }


async def test_register_visit_requires_authentication(api_client):
    resp = await api_client.post("/api/v1/reception/visits", json={})
    assert resp.status_code == 401


async def test_register_visit_without_permission_is_forbidden(api_client, real_session):
    actor, access_token = await _create_and_login(api_client, real_session, "no-perm-register")

    resp = await api_client.post(
        "/api/v1/reception/visits",
        json={
            "new_patient": _new_patient_body("NoPerm"),
            "procedure": "Consultation",
            "amount": "1500.00",
            "vitals_required": True,
        },
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 403


async def test_register_visit_both_patient_id_and_new_patient_returns_422(
    api_client, real_session, grant_permission
):
    actor, access_token = await _create_and_login(api_client, real_session, "both-sources")
    await grant_permission(actor, PERMISSION_RECEPTION_REGISTER_VISIT)

    resp = await api_client.post(
        "/api/v1/reception/visits",
        json={
            "patient_id": str(actor.id),
            "new_patient": _new_patient_body("Both"),
            "procedure": "Consultation",
            "amount": "1500.00",
            "vitals_required": True,
        },
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 422


async def test_register_visit_success_with_new_patient(api_client, real_session, grant_permission):
    actor, access_token = await _create_and_login(api_client, real_session, "register-success")
    await grant_permission(actor, PERMISSION_RECEPTION_REGISTER_VISIT)

    resp = await api_client.post(
        "/api/v1/reception/visits",
        json={
            "new_patient": _new_patient_body("Success"),
            "procedure": "Consultation",
            "amount": "1500.00",
            "vitals_required": True,
        },
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 201
    body = resp.json()["data"]
    assert body["patient"]["mr_number"].startswith("MR-")
    assert body["visit"]["status"] == "waiting_vitals"
    assert body["queue_entry"]["destination"] == "vitals"
    assert body["queue_entry"]["status"] == "waiting"


async def test_register_visit_auto_assigns_online_doctor(
    api_client, real_session, grant_permission
):
    """Phase 6 fast-registration §4 over real HTTP: no `doctor_user_id`
    field exists in the request at all — a currently logged-in,
    `consultation:start`-holding doctor must be auto-assigned."""
    receptionist, receptionist_token = await _create_and_login(
        api_client, real_session, "auto-assign-receptionist"
    )
    await grant_permission(receptionist, PERMISSION_RECEPTION_REGISTER_VISIT)
    doctor, _doctor_token = await _create_and_login(api_client, real_session, "auto-assign-doctor")
    await grant_permission(doctor, PERMISSION_CONSULTATION_START)

    resp = await api_client.post(
        "/api/v1/reception/visits",
        json={
            "new_patient": _new_patient_body("AutoAssign"),
            "procedure": "Consultation",
            "amount": "1500.00",
            "vitals_required": False,
        },
        headers=_auth_header(receptionist_token),
    )

    assert resp.status_code == 201
    assert resp.json()["data"]["visit"]["doctor_user_id"] == str(doctor.id)


async def test_register_visit_leaves_unassigned_without_online_doctor(
    api_client, real_session, grant_permission
):
    """The other half of Phase 6 fast-registration §4: with no eligible
    online doctor, registration still succeeds and the Visit is simply
    unassigned rather than the request being blocked or erroring."""
    receptionist, access_token = await _create_and_login(
        api_client, real_session, "no-doctor-receptionist"
    )
    await grant_permission(receptionist, PERMISSION_RECEPTION_REGISTER_VISIT)

    resp = await api_client.post(
        "/api/v1/reception/visits",
        json={
            "new_patient": _new_patient_body("NoDoctorOnline"),
            "procedure": "Consultation",
            "amount": "1500.00",
            "vitals_required": False,
        },
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 201
    assert resp.json()["data"]["visit"]["doctor_user_id"] is None


async def test_print_registration_slip_success(api_client, real_session, grant_permission):
    actor, access_token = await _create_and_login(api_client, real_session, "print-slip-success")
    await grant_permission(actor, PERMISSION_RECEPTION_REGISTER_VISIT)
    register_resp = await api_client.post(
        "/api/v1/reception/visits",
        json={
            "new_patient": _new_patient_body("PrintSlip"),
            "procedure": "Consultation",
            "amount": "1500.00",
            "vitals_required": False,
        },
        headers=_auth_header(access_token),
    )
    visit_id = register_resp.json()["data"]["visit"]["id"]
    mr_number = register_resp.json()["data"]["patient"]["mr_number"]

    resp = await api_client.get(
        f"/api/v1/reception/visits/{visit_id}/slip/print", headers=_auth_header(access_token)
    )

    assert resp.status_code == 200
    assert mr_number in resp.text
    assert "Consultation" in resp.text
    # The attending doctor is intentionally omitted from this slip design
    # (see app/shared/printing/service.py's render_registration_slip
    # docstring) — assert its absence rather than presence.
    assert "Doctor" not in resp.text


async def test_print_registration_slip_requires_permission(api_client, real_session):
    _actor, access_token = await _create_and_login(api_client, real_session, "print-slip-no-perm")

    resp = await api_client.get(
        "/api/v1/reception/visits/00000000-0000-0000-0000-000000000000/slip/print",
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 403


async def test_cancel_visit_requires_permission(api_client, real_session, grant_permission):
    actor, access_token = await _create_and_login(api_client, real_session, "cancel-no-perm")
    await grant_permission(actor, PERMISSION_RECEPTION_REGISTER_VISIT)
    register_resp = await api_client.post(
        "/api/v1/reception/visits",
        json={
            "new_patient": _new_patient_body("CancelNoPerm"),
            "procedure": "Consultation",
            "amount": "1500.00",
            "vitals_required": False,
        },
        headers=_auth_header(access_token),
    )
    visit_id = register_resp.json()["data"]["visit"]["id"]

    resp = await api_client.post(
        f"/api/v1/reception/visits/{visit_id}/cancel",
        json={},
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 403


async def test_cancel_visit_success(api_client, real_session, grant_permission):
    actor, access_token = await _create_and_login(api_client, real_session, "cancel-success")
    await grant_permission(actor, PERMISSION_RECEPTION_REGISTER_VISIT)
    await grant_permission(actor, PERMISSION_RECEPTION_CANCEL_VISIT)
    register_resp = await api_client.post(
        "/api/v1/reception/visits",
        json={
            "new_patient": _new_patient_body("CancelSuccess"),
            "procedure": "Consultation",
            "amount": "1500.00",
            "vitals_required": False,
        },
        headers=_auth_header(access_token),
    )
    visit_id = register_resp.json()["data"]["visit"]["id"]

    resp = await api_client.post(
        f"/api/v1/reception/visits/{visit_id}/cancel",
        json={"reason": "Patient left"},
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "cancelled"

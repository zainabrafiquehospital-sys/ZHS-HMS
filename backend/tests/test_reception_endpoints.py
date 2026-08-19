"""Full end-to-end HTTP tests for the Reception module — see
tests/test_patients_endpoints.py's identical module docstring."""

from app.modules.auth.models import User, UserStatus
from app.modules.auth.password_service import PasswordService
from app.modules.auth.repository import UserRepository
from app.modules.consultation.constants import PERMISSION_CONSULTATION_START
from app.modules.reception.constants import (
    PERMISSION_RECEPTION_CANCEL_VISIT,
    PERMISSION_RECEPTION_CLEAR_OWN_REVENUE,
    PERMISSION_RECEPTION_DELETE_VISIT,
    PERMISSION_RECEPTION_REGISTER_VISIT,
    PERMISSION_RECEPTION_UPDATE_VISIT,
)
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


# ---------------------------------------------------------------------
# Admin data correction (2026-08-19 addition) —
# reception:update_visit / reception:delete_visit, never granted via
# reception:register_visit or reception:cancel_visit alone.
# ---------------------------------------------------------------------


async def _register_visit_http(api_client, access_token, suffix: str) -> str:
    resp = await api_client.post(
        "/api/v1/reception/visits",
        json={
            "new_patient": _new_patient_body(suffix),
            "procedure": "Consultation",
            "amount": "1500.00",
            "vitals_required": False,
        },
        headers=_auth_header(access_token),
    )
    return resp.json()["data"]["visit"]["id"]


async def test_update_visit_requires_permission(api_client, real_session, grant_permission):
    actor, access_token = await _create_and_login(api_client, real_session, "update-no-perm")
    await grant_permission(actor, PERMISSION_RECEPTION_REGISTER_VISIT)
    visit_id = await _register_visit_http(api_client, access_token, "UpdateNoPerm")

    resp = await api_client.patch(
        f"/api/v1/reception/visits/{visit_id}",
        json={"procedure": "Ultrasound"},
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "PERMISSION_DENIED"


async def test_update_visit_cancel_permission_alone_is_not_sufficient(
    api_client, real_session, grant_permission
):
    """Explicitly proves holding reception:cancel_visit (what
    Receptionists already have) does not implicitly widen into
    reception:update_visit — the two are unrelated, separately-granted
    permissions."""
    actor, access_token = await _create_and_login(api_client, real_session, "update-cancel-only")
    await grant_permission(actor, PERMISSION_RECEPTION_REGISTER_VISIT)
    await grant_permission(actor, PERMISSION_RECEPTION_CANCEL_VISIT)
    visit_id = await _register_visit_http(api_client, access_token, "UpdateCancelOnly")

    resp = await api_client.patch(
        f"/api/v1/reception/visits/{visit_id}",
        json={"procedure": "Ultrasound"},
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 403


async def test_update_visit_admin_can_correct_a_different_receptionists_slip(
    api_client, real_session, grant_permission
):
    """Ownership never matters for this permission — an admin corrects
    any receptionist's slip, not only their own."""
    receptionist, receptionist_token = await _create_and_login(
        api_client, real_session, "update-owner-receptionist"
    )
    await grant_permission(receptionist, PERMISSION_RECEPTION_REGISTER_VISIT)
    visit_id = await _register_visit_http(api_client, receptionist_token, "UpdateOwnership")

    admin, admin_token = await _create_and_login(api_client, real_session, "update-admin")
    await grant_permission(admin, PERMISSION_RECEPTION_UPDATE_VISIT)

    resp = await api_client.patch(
        f"/api/v1/reception/visits/{visit_id}",
        json={
            "full_name": f"{TEST_PATIENT_NAME_PREFIX}CorrectedByAdmin",
            "procedure": "Ultrasound",
            "amount": "2500.00",
        },
        headers=_auth_header(admin_token),
    )

    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["patient"]["full_name"] == f"{TEST_PATIENT_NAME_PREFIX}CorrectedByAdmin"
    assert body["visit"]["procedure"] == "Ultrasound"
    assert body["visit"]["amount"] == "2500.00"


async def test_delete_visit_requires_permission(api_client, real_session, grant_permission):
    actor, access_token = await _create_and_login(api_client, real_session, "delete-no-perm")
    await grant_permission(actor, PERMISSION_RECEPTION_REGISTER_VISIT)
    visit_id = await _register_visit_http(api_client, access_token, "DeleteNoPerm")

    resp = await api_client.delete(
        f"/api/v1/reception/visits/{visit_id}", headers=_auth_header(access_token)
    )

    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "PERMISSION_DENIED"


async def test_delete_visit_cancel_permission_alone_is_not_sufficient(
    api_client, real_session, grant_permission
):
    """The requirement this guards: Receptionists must never gain
    delete access, including implicitly through the cancel permission
    they already hold."""
    actor, access_token = await _create_and_login(api_client, real_session, "delete-cancel-only")
    await grant_permission(actor, PERMISSION_RECEPTION_REGISTER_VISIT)
    await grant_permission(actor, PERMISSION_RECEPTION_CANCEL_VISIT)
    visit_id = await _register_visit_http(api_client, access_token, "DeleteCancelOnly")

    resp = await api_client.delete(
        f"/api/v1/reception/visits/{visit_id}", headers=_auth_header(access_token)
    )

    assert resp.status_code == 403


async def test_delete_visit_success_removes_it_from_get(api_client, real_session, grant_permission):
    receptionist, receptionist_token = await _create_and_login(
        api_client, real_session, "delete-owner-receptionist"
    )
    await grant_permission(receptionist, PERMISSION_RECEPTION_REGISTER_VISIT)
    visit_id = await _register_visit_http(api_client, receptionist_token, "DeleteSuccess")

    admin, admin_token = await _create_and_login(api_client, real_session, "delete-admin")
    await grant_permission(admin, PERMISSION_RECEPTION_DELETE_VISIT)
    await grant_permission(admin, PERMISSION_VISITS_READ)

    delete_resp = await api_client.delete(
        f"/api/v1/reception/visits/{visit_id}", headers=_auth_header(admin_token)
    )
    assert delete_resp.status_code == 200

    get_resp = await api_client.get(
        f"/api/v1/visits/{visit_id}", headers=_auth_header(admin_token)
    )
    assert get_resp.status_code == 404


# The invoice-paid delete block itself (VISIT_HAS_SETTLED_INVOICE) is
# deliberately proven at the service layer instead of here — see
# tests/test_reception_service.py's test_admin_delete_visit_blocked_
# when_invoice_paid/_partially_paid. Driving a visit to WAITING_BILLING
# purely over HTTP requires POST /consultations to auto-assign *this*
# test's own actor as the visit's doctor, which is exactly the
# pre-existing, already-diagnosed shared-dev-DB flakiness documented
# elsewhere in this session (a stale logged-in account from a prior
# session can win the auto-assignment instead) — unrelated to this
# feature, but it would make this specific HTTP-level test spuriously
# fail for a reason that has nothing to do with what it's meant to
# verify. The service-layer test pins the doctor explicitly at
# registration and is fully deterministic.


# ---------------------------------------------------------------------
# "My Revenue" (2026-08-19 addition) — RBAC over HTTP: reading requires
# the base reception:register_visit permission every receptionist
# already holds; clearing requires the new, separately-grantable
# reception:clear_own_revenue. Own-only scoping itself is proven at the
# service layer (test_reception_service.py) — these confirm the HTTP
# permission gates are wired correctly.
# ---------------------------------------------------------------------


async def test_get_own_revenue_requires_permission(api_client, real_session):
    _actor, access_token = await _create_and_login(api_client, real_session, "revenue-read-no-perm")

    resp = await api_client.get("/api/v1/reception/revenue", headers=_auth_header(access_token))

    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "PERMISSION_DENIED"


async def test_get_own_revenue_success_via_http(api_client, real_session, grant_permission):
    actor, access_token = await _create_and_login(api_client, real_session, "revenue-read-success")
    await grant_permission(actor, PERMISSION_RECEPTION_REGISTER_VISIT)
    await _register_visit_http(api_client, access_token, "RevenueHttpRead")

    resp = await api_client.get("/api/v1/reception/revenue", headers=_auth_header(access_token))

    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["visits_count"] == 1
    assert body["visits_revenue"] == "1500.00"
    assert body["total_revenue"] == "1500.00"
    # Never cleared, so this is the 24h auto-window's own timestamp — a
    # real, recent value, never null/all-time (2026-08-19 fix).
    assert body["cleared_at"]


async def test_clear_own_revenue_requires_permission(api_client, real_session, grant_permission):
    """Holding reception:register_visit alone (every receptionist's
    baseline) must not be enough to clear — clearing needs its own,
    separately-grantable permission."""
    actor, access_token = await _create_and_login(api_client, real_session, "revenue-clear-no-perm")
    await grant_permission(actor, PERMISSION_RECEPTION_REGISTER_VISIT)

    resp = await api_client.post(
        "/api/v1/reception/revenue/clear", headers=_auth_header(access_token)
    )

    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "PERMISSION_DENIED"


async def test_clear_own_revenue_success_via_http(api_client, real_session, grant_permission):
    actor, access_token = await _create_and_login(api_client, real_session, "revenue-clear-success")
    await grant_permission(actor, PERMISSION_RECEPTION_REGISTER_VISIT)
    await grant_permission(actor, PERMISSION_RECEPTION_CLEAR_OWN_REVENUE)
    await _register_visit_http(api_client, access_token, "RevenueHttpClear")

    clear_resp = await api_client.post(
        "/api/v1/reception/revenue/clear", headers=_auth_header(access_token)
    )
    assert clear_resp.status_code == 200
    assert clear_resp.json()["data"]["cleared_at"]

    after_resp = await api_client.get("/api/v1/reception/revenue", headers=_auth_header(access_token))
    body = after_resp.json()["data"]
    assert body["visits_count"] == 0
    assert body["total_revenue"] == "0.00"
    assert body["cleared_at"]


async def test_get_own_revenue_never_reflects_another_receptionists_visits(
    api_client, real_session, grant_permission
):
    """There is no user-id parameter on this endpoint at all — this
    confirms two different receptionists calling it get two different,
    correctly-isolated answers, the way the endpoint's own hard-scoping
    to the caller is meant to guarantee."""
    receptionist_a, token_a = await _create_and_login(api_client, real_session, "revenue-http-a")
    await grant_permission(receptionist_a, PERMISSION_RECEPTION_REGISTER_VISIT)
    await _register_visit_http(api_client, token_a, "RevenueHttpIsolationA")

    receptionist_b, token_b = await _create_and_login(api_client, real_session, "revenue-http-b")
    await grant_permission(receptionist_b, PERMISSION_RECEPTION_REGISTER_VISIT)

    resp_b = await api_client.get("/api/v1/reception/revenue", headers=_auth_header(token_b))

    assert resp_b.status_code == 200
    assert resp_b.json()["data"]["visits_count"] == 0
    assert resp_b.json()["data"]["total_revenue"] == "0.00"

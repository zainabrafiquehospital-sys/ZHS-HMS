"""Full OPD (Outpatient Department) integration test suite.

Exercises the complete Reception -> Doctor Queue -> Consultation ->
Vitals -> Billing -> Invoice Printing pipeline end to end, over the
real HTTP API (`api_client`) wherever the scenario calls for it — real
ASGI routing, real dependency-injection graph, real Postgres, real RBAC.
Every scenario the module-level test suites already covered in
isolation is exercised again here specifically for *integration*: do
these already-verified pieces correctly compose across module
boundaries, under real concurrent load where relevant.

Numbered to match the ten required scenarios exactly."""

import asyncio

from app.modules.auth.models import User, UserStatus
from app.modules.auth.password_service import PasswordService
from app.modules.auth.repository import UserRepository
from app.modules.billing.constants import (
    PERMISSION_BILLING_MANAGE,
    PERMISSION_BILLING_READ,
    PERMISSION_BILLING_SUBMIT_CHARGE,
)
from app.modules.consultation.constants import (
    PERMISSION_CONSULTATION_MANAGE,
    PERMISSION_CONSULTATION_READ,
    PERMISSION_CONSULTATION_START,
)
from app.modules.dashboard.constants import PERMISSION_DASHBOARD_DOCTOR_READ
from app.modules.patients.models import PatientGender
from app.modules.queue.constants import PERMISSION_QUEUE_READ
from app.modules.reception.constants import (
    PERMISSION_RECEPTION_CANCEL_VISIT,
    PERMISSION_RECEPTION_REGISTER_VISIT,
)
from app.modules.visits.constants import PERMISSION_VISITS_READ
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
            full_name="OPD Integration Actor",
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
        "full_name": f"{TEST_PATIENT_NAME_PREFIX}OPD{suffix}",
        "guardian_name": None,
        "gender": "female",
        "age_years": 36,
        "phone_number": "03001234567",
        "cnic": None,
        "address": None,
    }


async def _grant_full_opd_permissions(grant_permission, actor: User) -> None:
    for permission in (
        PERMISSION_RECEPTION_REGISTER_VISIT,
        PERMISSION_RECEPTION_CANCEL_VISIT,
        PERMISSION_CONSULTATION_START,
        PERMISSION_CONSULTATION_MANAGE,
        PERMISSION_CONSULTATION_READ,
        PERMISSION_VITALS_RECORD,
        PERMISSION_VITALS_READ,
        PERMISSION_BILLING_SUBMIT_CHARGE,
        PERMISSION_BILLING_MANAGE,
        PERMISSION_BILLING_READ,
        PERMISSION_QUEUE_READ,
        PERMISSION_DASHBOARD_DOCTOR_READ,
        PERMISSION_VISITS_READ,
    ):
        await grant_permission(actor, permission)


# ---------------------------------------------------------------------
# 1. New patient registration -> consultation -> billing -> printed invoice
# ---------------------------------------------------------------------


async def test_scenario_1_new_patient_full_flow_with_printed_invoice(
    api_client, real_session, grant_permission
):
    doctor, access_token = await _create_and_login(api_client, real_session, "s1-doctor")
    await _grant_full_opd_permissions(grant_permission, doctor)
    headers = _auth_header(access_token)

    register_resp = await api_client.post(
        "/api/v1/reception/visits",
        json={
            "new_patient": _new_patient_body("Scenario1"),
            "procedures": [{"name": "Consultation", "amount": "1500.00"}],
            "vitals_required": False,
        },
        headers=headers,
    )
    assert register_resp.status_code == 201
    body = register_resp.json()["data"]
    assert body["visit"]["status"] == "waiting_doctor"
    assert body["patient"]["mr_number"].startswith("MR-")
    visit_id = body["visit"]["id"]

    start_resp = await api_client.post(
        "/api/v1/consultations", json={"visit_id": visit_id}, headers=headers
    )
    consultation_id = start_resp.json()["data"]["id"]
    complete_resp = await api_client.post(
        f"/api/v1/consultations/{consultation_id}/complete",
        json={"diagnosis": "Routine checkup"},
        headers=headers,
    )
    assert complete_resp.status_code == 200

    generate_resp = await api_client.post(
        "/api/v1/billing/invoices",
        json={
            "visit_id": visit_id,
            "base_description": "Consultation Fee",
            "base_amount": "1000.00",
        },
        headers=headers,
    )
    invoice_id = generate_resp.json()["data"]["id"]
    pay_resp = await api_client.post(
        f"/api/v1/billing/invoices/{invoice_id}/pay",
        json={"amount": "1000.00", "payment_method": "cash"},
        headers=headers,
    )
    assert pay_resp.json()["data"]["status"] == "paid"

    print_resp = await api_client.get(
        f"/api/v1/billing/invoices/{invoice_id}/print", headers=headers
    )
    assert print_resp.status_code == 200
    assert "1,000.00" in print_resp.text


# ---------------------------------------------------------------------
# 2. Existing patient registration -> consultation -> billing
# ---------------------------------------------------------------------


async def test_scenario_2_existing_patient_registration_through_billing(
    api_client, real_session, grant_permission, patient_service
):
    doctor, access_token = await _create_and_login(api_client, real_session, "s2-doctor")
    await _grant_full_opd_permissions(grant_permission, doctor)
    headers = _auth_header(access_token)
    existing_patient = await patient_service.register_patient(
        actor=doctor,
        full_name=f"{TEST_PATIENT_NAME_PREFIX}OPDExisting",
        guardian_name=None,
        gender=PatientGender.FEMALE,
        age_years=40,
        phone_number="03001234567",
        cnic=None,
        address=None,
    )

    register_resp = await api_client.post(
        "/api/v1/reception/visits",
        json={
            "patient_id": str(existing_patient.id),
            "procedures": [{"name": "Follow-up", "amount": "1500.00"}],
            "vitals_required": False,
        },
        headers=headers,
    )
    assert register_resp.status_code == 201
    body = register_resp.json()["data"]
    assert body["patient"]["id"] == str(existing_patient.id)
    visit_id = body["visit"]["id"]

    start_resp = await api_client.post(
        "/api/v1/consultations", json={"visit_id": visit_id}, headers=headers
    )
    consultation_id = start_resp.json()["data"]["id"]
    await api_client.post(
        f"/api/v1/consultations/{consultation_id}/complete", json={}, headers=headers
    )

    generate_resp = await api_client.post(
        "/api/v1/billing/invoices",
        json={"visit_id": visit_id, "base_description": "Follow-up Fee", "base_amount": "500.00"},
        headers=headers,
    )
    assert generate_resp.status_code == 201
    assert generate_resp.json()["data"]["total_amount"] == "500.00"


# ---------------------------------------------------------------------
# 3. Consultation requiring vitals — both the initial-intake path
#    (Workflow A) and the mid-consultation doctor-requested detour
# ---------------------------------------------------------------------


async def test_scenario_3a_workflow_a_vitals_required_intake(
    api_client, real_session, grant_permission
):
    doctor, access_token = await _create_and_login(api_client, real_session, "s3a-doctor")
    await _grant_full_opd_permissions(grant_permission, doctor)
    headers = _auth_header(access_token)

    register_resp = await api_client.post(
        "/api/v1/reception/visits",
        json={
            "new_patient": _new_patient_body("Scenario3a"),
            "procedures": [{"name": "Consultation", "amount": "1500.00"}],
            "vitals_required": True,
        },
        headers=headers,
    )
    body = register_resp.json()["data"]
    assert body["visit"]["status"] == "waiting_vitals"
    assert body["queue_entry"]["destination"] == "vitals"
    visit_id = body["visit"]["id"]

    vitals_resp = await api_client.post(
        "/api/v1/vitals",
        json={
            "visit_id": visit_id,
            "systolic_bp": 118,
            "diastolic_bp": 76,
            "pulse_rate": 72,
            "spo2_percent": 98,
        },
        headers=headers,
    )
    assert vitals_resp.status_code == 201
    assert vitals_resp.json()["data"]["consultation_id"] is None

    visit_resp = await api_client.get(f"/api/v1/visits/{visit_id}", headers=headers)
    assert visit_resp.json()["data"]["status"] == "waiting_doctor"

    start_resp = await api_client.post(
        "/api/v1/consultations", json={"visit_id": visit_id}, headers=headers
    )
    assert start_resp.status_code == 201


async def test_scenario_3b_doctor_requested_mid_consultation_vitals_detour(
    api_client, real_session, grant_permission
):
    doctor, access_token = await _create_and_login(api_client, real_session, "s3b-doctor")
    await _grant_full_opd_permissions(grant_permission, doctor)
    headers = _auth_header(access_token)

    register_resp = await api_client.post(
        "/api/v1/reception/visits",
        json={
            "new_patient": _new_patient_body("Scenario3b"),
            "procedures": [{"name": "Consultation", "amount": "1500.00"}],
            "vitals_required": False,
        },
        headers=headers,
    )
    visit_id = register_resp.json()["data"]["visit"]["id"]
    start_resp = await api_client.post(
        "/api/v1/consultations", json={"visit_id": visit_id}, headers=headers
    )
    consultation_id = start_resp.json()["data"]["id"]

    send_resp = await api_client.post(
        f"/api/v1/consultations/{consultation_id}/send-to-vitals",
        json={"reason": "Recheck BP"},
        headers=headers,
    )
    assert send_resp.json()["data"]["status"] == "awaiting_vitals"
    # §4.1: the Visit itself never leaves IN_CONSULTATION for a detour.
    mid_detour_visit = await api_client.get(f"/api/v1/visits/{visit_id}", headers=headers)
    assert mid_detour_visit.json()["data"]["status"] == "in_consultation"

    vitals_resp = await api_client.post(
        "/api/v1/vitals",
        json={"visit_id": visit_id, "systolic_bp": 130, "diastolic_bp": 85},
        headers=headers,
    )
    assert vitals_resp.json()["data"]["consultation_id"] == consultation_id

    resumed_consultation = await api_client.get(
        f"/api/v1/consultations/{consultation_id}", headers=headers
    )
    assert resumed_consultation.json()["data"]["status"] == "in_progress"
    complete_resp = await api_client.post(
        f"/api/v1/consultations/{consultation_id}/complete", json={}, headers=headers
    )
    assert complete_resp.status_code == 200


# ---------------------------------------------------------------------
# 4. Multiple patients in queue
# ---------------------------------------------------------------------


async def test_scenario_4_multiple_patients_in_queue_fifo_order(
    api_client, real_session, grant_permission
):
    doctor, access_token = await _create_and_login(api_client, real_session, "s4-doctor")
    await _grant_full_opd_permissions(grant_permission, doctor)
    headers = _auth_header(access_token)

    visit_ids = []
    for suffix in ("First", "Second", "Third"):
        resp = await api_client.post(
            "/api/v1/reception/visits",
            json={
                "new_patient": _new_patient_body(f"Scenario4{suffix}"),
                "procedures": [{"name": "Consultation", "amount": "1500.00"}],
                "vitals_required": False,
            },
            headers=headers,
        )
        visit_ids.append(resp.json()["data"]["visit"]["id"])

    dashboard_resp = await api_client.get("/api/v1/dashboard/doctor", headers=headers)
    assert dashboard_resp.json()["data"]["waiting_count"] == 3

    worklist_resp = await api_client.get(
        "/api/v1/queue/worklist",
        params={"destination": "doctor", "status": "waiting", "page_size": 100},
        headers=headers,
    )
    worklist_visit_ids = [row["visit_id"] for row in worklist_resp.json()["data"]]
    positions = [worklist_visit_ids.index(vid) for vid in visit_ids]
    assert positions == sorted(positions)  # FIFO — registration order preserved


# ---------------------------------------------------------------------
# 5. Visit cancellation
# ---------------------------------------------------------------------


async def test_scenario_5_visit_cancellation(api_client, real_session, grant_permission):
    doctor, access_token = await _create_and_login(api_client, real_session, "s5-doctor")
    await _grant_full_opd_permissions(grant_permission, doctor)
    headers = _auth_header(access_token)

    register_resp = await api_client.post(
        "/api/v1/reception/visits",
        json={
            "new_patient": _new_patient_body("Scenario5"),
            "procedures": [{"name": "Consultation", "amount": "1500.00"}],
            "vitals_required": False,
        },
        headers=headers,
    )
    visit_id = register_resp.json()["data"]["visit"]["id"]

    cancel_resp = await api_client.post(
        f"/api/v1/reception/visits/{visit_id}/cancel",
        json={"reason": "Patient left before being seen"},
        headers=headers,
    )
    assert cancel_resp.status_code == 200
    assert cancel_resp.json()["data"]["status"] == "cancelled"

    active_entry_resp = await api_client.get(
        f"/api/v1/queue/visits/{visit_id}/active", headers=headers
    )
    assert active_entry_resp.json()["data"] is None

    # A cancelled Visit has no valid outgoing transition — starting a
    # consultation on it must fail, not silently succeed.
    start_resp = await api_client.post(
        "/api/v1/consultations", json={"visit_id": visit_id}, headers=headers
    )
    assert start_resp.status_code == 422


# ---------------------------------------------------------------------
# 6. Billing authorization (Reception only)
# ---------------------------------------------------------------------


async def test_scenario_6_billing_authorization_reception_only(
    api_client, real_session, grant_permission
):
    doctor, access_token = await _create_and_login(api_client, real_session, "s6-doctor")
    # Doctor role: registration + consultation + billing SUBMIT only —
    # never billing:manage, matching Phase 6 §7's segregation of duties.
    for permission in (
        PERMISSION_RECEPTION_REGISTER_VISIT,
        PERMISSION_CONSULTATION_START,
        PERMISSION_CONSULTATION_MANAGE,
        PERMISSION_BILLING_SUBMIT_CHARGE,
    ):
        await grant_permission(doctor, permission)
    headers = _auth_header(access_token)

    register_resp = await api_client.post(
        "/api/v1/reception/visits",
        json={
            "new_patient": _new_patient_body("Scenario6"),
            "procedures": [{"name": "Consultation", "amount": "1500.00"}],
            "vitals_required": False,
        },
        headers=headers,
    )
    visit_id = register_resp.json()["data"]["visit"]["id"]
    start_resp = await api_client.post(
        "/api/v1/consultations", json={"visit_id": visit_id}, headers=headers
    )
    consultation_id = start_resp.json()["data"]["id"]
    await api_client.post(
        f"/api/v1/consultations/{consultation_id}/complete", json={}, headers=headers
    )

    submit_resp = await api_client.post(
        "/api/v1/billing/pending-items",
        json={"visit_id": visit_id, "description": "Injection", "amount": "500"},
        headers=headers,
    )
    assert submit_resp.status_code == 201  # doctor CAN submit a charge request

    item_id = submit_resp.json()["data"]["id"]
    approve_resp = await api_client.post(
        f"/api/v1/billing/pending-items/{item_id}/approve", headers=headers
    )
    generate_resp = await api_client.post(
        "/api/v1/billing/invoices",
        json={"visit_id": visit_id, "base_description": "Fee", "base_amount": "1000"},
        headers=headers,
    )
    pay_resp = await api_client.post(
        "/api/v1/billing/invoices/00000000-0000-0000-0000-000000000000/pay",
        json={"amount": "1", "payment_method": "cash"},
        headers=headers,
    )
    assert approve_resp.status_code == 403  # doctor CANNOT approve
    assert generate_resp.status_code == 403  # doctor CANNOT generate an invoice
    assert pay_resp.status_code == 403  # doctor CANNOT record a payment


# ---------------------------------------------------------------------
# 7. Unauthorized RBAC access attempts
# ---------------------------------------------------------------------


async def test_scenario_7_unauthorized_access_attempts(api_client, real_session):
    _actor, access_token = await _create_and_login(api_client, real_session, "s7-no-perms")
    headers = _auth_header(access_token)
    no_auth_headers: dict = {}

    checks = [
        ("POST", "/api/v1/reception/visits", {"vitals_required": False}),
        ("POST", "/api/v1/consultations", {"visit_id": "00000000-0000-0000-0000-000000000000"}),
        ("POST", "/api/v1/vitals", {"visit_id": "00000000-0000-0000-0000-000000000000"}),
        (
            "POST",
            "/api/v1/billing/pending-items",
            {"visit_id": "00000000-0000-0000-0000-000000000000", "description": "x", "amount": "1"},
        ),
        ("GET", "/api/v1/dashboard/reception", None),
    ]
    for method, path, json_body in checks:
        no_token_resp = await api_client.request(
            method, path, json=json_body, headers=no_auth_headers
        )
        assert no_token_resp.status_code == 401, f"{method} {path} without a token"

        no_permission_resp = await api_client.request(method, path, json=json_body, headers=headers)
        assert no_permission_resp.status_code == 403, f"{method} {path} without permission"


# ---------------------------------------------------------------------
# 8. Concurrent receptionist activity
# ---------------------------------------------------------------------


async def test_scenario_8_concurrent_receptionist_registration(
    api_client, real_session, grant_permission
):
    """Two "receptionists" (in practice the same actor, since RBAC
    identity isn't what's under test here) registering different
    patients at the same instant — proves the race-safe MR-number and
    Queue-Token sequence generation actually holds under real
    concurrent load, not just sequential calls."""
    doctor, access_token = await _create_and_login(api_client, real_session, "s8-receptionist")
    await _grant_full_opd_permissions(grant_permission, doctor)
    headers = _auth_header(access_token)

    async def _register(suffix: str):
        return await api_client.post(
            "/api/v1/reception/visits",
            json={
                "new_patient": _new_patient_body(f"Scenario8-{suffix}"),
                "procedures": [{"name": "Consultation", "amount": "1500.00"}],
                "vitals_required": False,
            },
            headers=headers,
        )

    responses = await asyncio.gather(*[_register(str(i)) for i in range(5)])

    assert all(resp.status_code == 201 for resp in responses)
    mr_numbers = [resp.json()["data"]["patient"]["mr_number"] for resp in responses]
    queue_tokens = [resp.json()["data"]["visit"]["queue_token"] for resp in responses]
    assert len(set(mr_numbers)) == 5  # no collisions
    assert len(set(queue_tokens)) == 5  # no collisions


# ---------------------------------------------------------------------
# 9. Concurrent doctor activity
# ---------------------------------------------------------------------


async def test_scenario_9_concurrent_doctors_independent_visits(
    api_client, real_session, grant_permission
):
    """Doctor B deliberately logs in (and registers their Visit) only
    *after* Visit A is registered — with no manual doctor-selection
    field left in the API (Phase 6 fast-registration §4), the only way
    to deterministically land each Visit on a *different* doctor is to
    ensure only Doctor A is online for the first auto-assignment, then
    let least-busy tie-breaking naturally hand the second Visit to
    Doctor B (who has zero busy Visits vs. Doctor A's one)."""
    doctor_a, token_a = await _create_and_login(api_client, real_session, "s9-doctor-a")
    await _grant_full_opd_permissions(grant_permission, doctor_a)

    visit_a_resp = await api_client.post(
        "/api/v1/reception/visits",
        json={
            "new_patient": _new_patient_body("Scenario9A"),
            "procedures": [{"name": "Consultation", "amount": "1500.00"}],
            "vitals_required": False,
        },
        headers=_auth_header(token_a),
    )
    assert visit_a_resp.json()["data"]["visit"]["doctor_user_id"] == str(doctor_a.id)

    doctor_b, token_b = await _create_and_login(api_client, real_session, "s9-doctor-b")
    await _grant_full_opd_permissions(grant_permission, doctor_b)

    visit_b_resp = await api_client.post(
        "/api/v1/reception/visits",
        json={
            "new_patient": _new_patient_body("Scenario9B"),
            "procedures": [{"name": "Consultation", "amount": "1500.00"}],
            "vitals_required": False,
        },
        headers=_auth_header(token_b),
    )
    assert visit_b_resp.json()["data"]["visit"]["doctor_user_id"] == str(doctor_b.id)
    visit_a_id = visit_a_resp.json()["data"]["visit"]["id"]
    visit_b_id = visit_b_resp.json()["data"]["visit"]["id"]

    start_a, start_b = await asyncio.gather(
        api_client.post(
            "/api/v1/consultations", json={"visit_id": visit_a_id}, headers=_auth_header(token_a)
        ),
        api_client.post(
            "/api/v1/consultations", json={"visit_id": visit_b_id}, headers=_auth_header(token_b)
        ),
    )
    assert start_a.status_code == 201
    assert start_b.status_code == 201


async def test_scenario_9b_concurrent_start_on_same_visit_only_one_wins(
    api_client, real_session, grant_permission
):
    """Two concurrent attempts to start a consultation on the *same*
    Visit — the database's partial unique index on an active
    Consultation per Visit (app/modules/consultation/models.py) must
    let exactly one through, proving this is a real, DB-enforced
    invariant, not just an application-level check that a race could
    slip past."""
    doctor, access_token = await _create_and_login(api_client, real_session, "s9b-doctor")
    await _grant_full_opd_permissions(grant_permission, doctor)
    headers = _auth_header(access_token)
    register_resp = await api_client.post(
        "/api/v1/reception/visits",
        json={
            "new_patient": _new_patient_body("Scenario9B2"),
            "procedures": [{"name": "Consultation", "amount": "1500.00"}],
            "vitals_required": False,
        },
        headers=headers,
    )
    visit_id = register_resp.json()["data"]["visit"]["id"]

    async def _start():
        return await api_client.post(
            "/api/v1/consultations", json={"visit_id": visit_id}, headers=headers
        )

    responses = await asyncio.gather(*[_start() for _ in range(3)], return_exceptions=True)
    status_codes = [r.status_code for r in responses if not isinstance(r, Exception)]

    assert status_codes.count(201) == 1
    assert all(code in (201, 409, 422) for code in status_codes)


# ---------------------------------------------------------------------
# 10. Concurrent billing activity
# ---------------------------------------------------------------------


async def test_scenario_10_concurrent_payment_attempts_only_one_succeeds(
    api_client, real_session, grant_permission
):
    """Two concurrent attempts to pay the full remaining balance of the
    same Invoice — exactly one must succeed; the other must be rejected
    (never a double-payment, never an overpaid invoice) — proving
    Phase 6 §7.4's "paid invoices are immutable" invariant holds under
    real concurrent load, not just sequential calls."""
    doctor, access_token = await _create_and_login(api_client, real_session, "s10-doctor")
    await _grant_full_opd_permissions(grant_permission, doctor)
    headers = _auth_header(access_token)
    register_resp = await api_client.post(
        "/api/v1/reception/visits",
        json={
            "new_patient": _new_patient_body("Scenario10"),
            "procedures": [{"name": "Consultation", "amount": "1500.00"}],
            "vitals_required": False,
        },
        headers=headers,
    )
    visit_id = register_resp.json()["data"]["visit"]["id"]
    start_resp = await api_client.post(
        "/api/v1/consultations", json={"visit_id": visit_id}, headers=headers
    )
    consultation_id = start_resp.json()["data"]["id"]
    await api_client.post(
        f"/api/v1/consultations/{consultation_id}/complete", json={}, headers=headers
    )
    generate_resp = await api_client.post(
        "/api/v1/billing/invoices",
        json={"visit_id": visit_id, "base_description": "Fee", "base_amount": "1000.00"},
        headers=headers,
    )
    invoice_id = generate_resp.json()["data"]["id"]

    async def _pay():
        return await api_client.post(
            f"/api/v1/billing/invoices/{invoice_id}/pay",
            json={"amount": "1000.00", "payment_method": "cash"},
            headers=headers,
        )

    responses = await asyncio.gather(*[_pay() for _ in range(2)])
    status_codes = [resp.status_code for resp in responses]

    assert status_codes.count(200) == 1  # exactly one payment succeeds
    assert sum(1 for code in status_codes if code in (409, 422)) == 1  # the loser is rejected

    final_invoice_resp = await api_client.get(
        f"/api/v1/billing/invoices/{invoice_id}", headers=headers
    )
    final_body = final_invoice_resp.json()["data"]
    assert final_body["status"] == "paid"
    assert final_body["amount_paid"] == "1000.00"  # never double-paid to 2000.00

"""Full end-to-end HTTP tests for the Vitals module — see
tests/test_patients_endpoints.py's identical module docstring."""

from datetime import date
from decimal import Decimal

from app.modules.auth.models import User, UserStatus
from app.modules.auth.password_service import PasswordService
from app.modules.auth.repository import UserRepository
from app.modules.inventory.constants import (
    PERMISSION_INVENTORY_MANAGE,
    PERMISSION_INVENTORY_RECORD_USAGE,
)
from app.modules.patients.models import PatientGender
from app.modules.vitals.constants import PERMISSION_VITALS_READ, PERMISSION_VITALS_RECORD
from app.shared.payment_method import PaymentMethod
from tests.conftest import TEST_INVENTORY_ITEM_NAME_PREFIX, TEST_PATIENT_NAME_PREFIX, make_test_email

_TODAY = date.today().isoformat()

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


async def _make_visit(reception_service, doctor, suffix: str, vitals_required: bool):
    """`doctor` is only ever the registering *actor* here, not a real
    doctor account (nothing in this file grants it `consultation:start`)
    — so the Visit is left unassigned (`doctor_user_id=None`) rather
    than explicitly assigned to it: an explicit assignment is now
    validated server-side (ReceptionRepository.get_doctor_by_id) and
    would correctly reject a non-doctor id. No test in this file
    depends on the Visit's own `doctor_user_id`."""
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
        doctor_user_id=None,
        procedures=[(None, "Consultation", Decimal("1500.00"))],
        vitals_required=vitals_required,
        initial_payment_amount=Decimal("0.01"),
        initial_payment_method=PaymentMethod.CASH,
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


async def test_get_vitals_stats_by_creator_requires_permission(api_client, real_session):
    _actor, access_token = await _create_and_login(api_client, real_session, "stats-no-perm")

    resp = await api_client.get(
        "/api/v1/vitals/stats/by-creator", headers=_auth_header(access_token)
    )

    assert resp.status_code == 403


async def test_get_vitals_stats_by_creator_returns_accurate_counts(
    api_client, real_session, grant_permission, reception_service
):
    staff, access_token = await _create_and_login(api_client, real_session, "stats-correctness")
    await grant_permission(staff, PERMISSION_VITALS_RECORD)
    await grant_permission(staff, PERMISSION_VITALS_READ)
    visit = await _make_visit(reception_service, staff, "StatsCorrectness", vitals_required=True)

    resp = await api_client.post(
        "/api/v1/vitals",
        json={"visit_id": str(visit.id), "systolic_bp": 118, "diastolic_bp": 76},
        headers=_auth_header(access_token),
    )
    assert resp.status_code == 201

    stats_resp = await api_client.get(
        "/api/v1/vitals/stats/by-creator", headers=_auth_header(access_token)
    )

    assert stats_resp.status_code == 200
    rows = {row["user_id"]: row["count"] for row in stats_resp.json()["data"]}
    assert rows[str(staff.id)] == 1


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
            "temperature": 98.6,
            "spo2_percent": 99,
        },
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 201
    body = resp.json()["data"]
    assert body["systolic_bp"] == 118
    assert body["consultation_id"] is None
    # 2026-08-28 change, going-forward only — every new record is
    # unambiguously Fahrenheit, server-stamped.
    assert body["temperature"] == 98.6
    assert body["temperature_unit"] == "fahrenheit"

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


async def test_record_vitals_temperature_out_of_fahrenheit_range_returns_422(
    api_client, real_session, grant_permission, reception_service
):
    """`68.0-113.0` is the going-forward Fahrenheit sanity range (2026-
    08-28 change) — a value that would have been a perfectly plausible
    Celsius reading under the old `20.0-45.0` range (e.g. 37.0, a normal
    body temperature) must now be rejected, since every new record is
    unambiguously Fahrenheit."""
    doctor, access_token = await _create_and_login(api_client, real_session, "temp-range")
    await grant_permission(doctor, PERMISSION_VITALS_RECORD)
    visit = await _make_visit(reception_service, doctor, "TempRange", vitals_required=True)

    resp = await api_client.post(
        "/api/v1/vitals",
        json={"visit_id": str(visit.id), "temperature": 37.0},
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


async def test_get_patient_vitals_history_requires_permission(
    api_client, real_session, reception_service
):
    doctor, access_token = await _create_and_login(api_client, real_session, "history-no-perm")
    visit = await _make_visit(reception_service, doctor, "HistoryNoPerm", vitals_required=False)

    resp = await api_client.get(
        f"/api/v1/vitals/patients/{visit.patient_id}/history", headers=_auth_header(access_token)
    )

    assert resp.status_code == 403


async def test_get_patient_vitals_history_returns_records_across_visits(
    api_client, real_session, grant_permission, reception_service
):
    """"Show Details" cross-visit vitals history (2026-08-28 addition)
    — a patient with vitals recorded on two separate visits must see
    both records, newest first, each correctly carrying its own
    `temperature_unit`."""
    doctor, access_token = await _create_and_login(api_client, real_session, "history-http")
    await grant_permission(doctor, PERMISSION_VITALS_RECORD)
    await grant_permission(doctor, PERMISSION_VITALS_READ)
    first_visit = await _make_visit(reception_service, doctor, "HistoryHttpA", vitals_required=True)
    first_resp = await api_client.post(
        "/api/v1/vitals",
        json={"visit_id": str(first_visit.id), "systolic_bp": 100, "temperature": 97.0},
        headers=_auth_header(access_token),
    )
    assert first_resp.status_code == 201

    _second_patient, second_visit, _entry = await reception_service.register_visit(
        actor=doctor,
        patient_id=first_visit.patient_id,
        new_patient=None,
        doctor_user_id=None,
        procedures=[(None, "Follow-up", Decimal("500.00"))],
        vitals_required=True,
        initial_payment_amount=Decimal("0.01"),
        initial_payment_method=PaymentMethod.CASH,
    )
    second_resp = await api_client.post(
        "/api/v1/vitals",
        json={"visit_id": str(second_visit.id), "systolic_bp": 140, "temperature": 101.0},
        headers=_auth_header(access_token),
    )
    assert second_resp.status_code == 201

    resp = await api_client.get(
        f"/api/v1/vitals/patients/{first_visit.patient_id}/history",
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 200
    body = resp.json()["data"]
    assert len(body) == 2
    # Newest first.
    assert body[0]["visit_id"] == str(second_visit.id)
    assert body[0]["systolic_bp"] == 140
    assert body[0]["temperature_unit"] == "fahrenheit"
    assert body[1]["visit_id"] == str(first_visit.id)
    assert body[1]["systolic_bp"] == 100


async def test_get_patient_vitals_history_returns_empty_list_when_none_recorded(
    api_client, real_session, grant_permission, reception_service
):
    doctor, access_token = await _create_and_login(api_client, real_session, "history-empty-http")
    await grant_permission(doctor, PERMISSION_VITALS_READ)
    visit = await _make_visit(reception_service, doctor, "HistoryEmptyHttp", vitals_required=False)

    resp = await api_client.get(
        f"/api/v1/vitals/patients/{visit.patient_id}/history", headers=_auth_header(access_token)
    )

    assert resp.status_code == 200
    assert resp.json()["data"] == []


async def test_print_daily_summary_requires_permission(api_client, real_session):
    _actor, access_token = await _create_and_login(api_client, real_session, "daily-summary-no-perm")

    resp = await api_client.get(
        "/api/v1/vitals/daily-summary/print",
        params={"date": _TODAY},
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 403


async def test_print_daily_summary_shows_both_sections_scoped_to_actor(
    api_client, real_session, grant_permission, reception_service
):
    """Step 5's combined daily PDF — one document, two sections, both
    scoped to the calling actor's own day only (the same hard
    actor-scoping `GET /inventory/usage/mine/print` already
    established). A second staff member's inventory usage on the same
    item/day must never leak into this actor's printed summary."""
    manager, manager_token = await _create_and_login(api_client, real_session, "daily-summary-mgr")
    await grant_permission(manager, PERMISSION_INVENTORY_MANAGE)
    item_resp = await api_client.post(
        "/api/v1/inventory/items",
        json={
            "name": f"{TEST_INVENTORY_ITEM_NAME_PREFIX}DailySummary",
            "category": "medicine",
            "unit": "piece",
        },
        headers=_auth_header(manager_token),
    )
    assert item_resp.status_code == 201, item_resp.text
    item_id = item_resp.json()["data"]["id"]
    # Usage can only be recorded against Emergency Stock, which starts
    # at zero for a freshly created item — receive into Main Stock, then
    # transfer to Emergency Stock, same two-step flow
    # test_print_daily_usage_slip_is_scoped_to_the_calling_actor
    # (test_inventory_endpoints.py) already establishes.
    await api_client.post(
        f"/api/v1/inventory/items/{item_id}/receive",
        json={"quantity": "20", "received_on": _TODAY},
        headers=_auth_header(manager_token),
    )
    await api_client.post(
        "/api/v1/inventory/transfers",
        json={
            "items": [{"item_id": item_id, "quantity": "20"}],
            "transferred_on": _TODAY,
            "carried_by_name": "Daily Summary Porter",
        },
        headers=_auth_header(manager_token),
    )

    actor, access_token = await _create_and_login(api_client, real_session, "daily-summary-actor")
    await grant_permission(actor, PERMISSION_INVENTORY_RECORD_USAGE)
    await grant_permission(actor, PERMISSION_VITALS_RECORD)
    other_staff, other_token = await _create_and_login(api_client, real_session, "daily-summary-other")
    await grant_permission(other_staff, PERMISSION_INVENTORY_RECORD_USAGE)

    # This actor's own inventory usage — must appear.
    usage_resp = await api_client.post(
        "/api/v1/inventory/usage",
        json={
            "items": [{"item_id": item_id, "quantity": "3"}],
            "used_on": _TODAY,
            "manual_patient_name": "Daily Summary Usage Patient",
            "manual_patient_age": 28,
            "manual_patient_phone": "03001234567",
        },
        headers=_auth_header(access_token),
    )
    assert usage_resp.status_code == 201, usage_resp.text

    # A DIFFERENT staff member's usage on the same item/day — must NOT
    # leak into this actor's printed summary.
    other_usage_resp = await api_client.post(
        "/api/v1/inventory/usage",
        json={
            "items": [{"item_id": item_id, "quantity": "9"}],
            "used_on": _TODAY,
            "manual_patient_name": "Other Staff Usage Patient",
            "manual_patient_age": 40,
            "manual_patient_phone": "03009998888",
        },
        headers=_auth_header(other_token),
    )
    assert other_usage_resp.status_code == 201, other_usage_resp.text

    # This actor's own vitals recording — must appear, correctly
    # labeled Fahrenheit (every new record is, since Step 1).
    visit = await _make_visit(reception_service, actor, "DailySummary", vitals_required=True)
    record_resp = await api_client.post(
        "/api/v1/vitals",
        json={"visit_id": str(visit.id), "systolic_bp": 118, "diastolic_bp": 76, "temperature": 99.1},
        headers=_auth_header(access_token),
    )
    assert record_resp.status_code == 201, record_resp.text

    resp = await api_client.get(
        "/api/v1/vitals/daily-summary/print",
        params={"date": _TODAY},
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 200, resp.text
    body = resp.text
    assert "Inventory Items Used" in body
    assert "Vitals Recorded" in body
    assert "Daily Summary Usage Patient" in body
    assert "Other Staff Usage Patient" not in body  # scoped to this actor only
    assert visit.queue_token in body
    assert "99.1 °F" in body
    assert actor.full_name in body  # "Vitals Staff:" header line, both sections


async def test_list_my_vitals_records_requires_permission(api_client, real_session):
    _actor, access_token = await _create_and_login(api_client, real_session, "my-records-no-perm")

    resp = await api_client.get("/api/v1/vitals/records/mine", headers=_auth_header(access_token))

    assert resp.status_code == 403


async def test_list_my_vitals_records_returns_only_own_records(
    api_client, real_session, grant_permission, reception_service
):
    """The core requirement: staff member A's "My Vitals Records" must
    never include staff member B's records, even though both recorded
    vitals in the same database at the same time — the Vitals sibling
    of test_list_my_bills_returns_only_own_bills
    (test_pharmacy_endpoints.py)."""
    actor_a, token_a = await _create_and_login(api_client, real_session, "my-records-a")
    await grant_permission(actor_a, PERMISSION_VITALS_RECORD)
    actor_b, token_b = await _create_and_login(api_client, real_session, "my-records-b")
    await grant_permission(actor_b, PERMISSION_VITALS_RECORD)

    visit_a = await _make_visit(reception_service, actor_a, "MyRecordsA", vitals_required=True)
    record_a_resp = await api_client.post(
        "/api/v1/vitals",
        json={"visit_id": str(visit_a.id), "systolic_bp": 110, "temperature": 98.0},
        headers=_auth_header(token_a),
    )
    assert record_a_resp.status_code == 201, record_a_resp.text
    record_a_id = record_a_resp.json()["data"]["id"]

    visit_b = await _make_visit(reception_service, actor_b, "MyRecordsB", vitals_required=True)
    record_b_resp = await api_client.post(
        "/api/v1/vitals",
        json={"visit_id": str(visit_b.id), "systolic_bp": 130, "temperature": 100.0},
        headers=_auth_header(token_b),
    )
    assert record_b_resp.status_code == 201, record_b_resp.text
    record_b_id = record_b_resp.json()["data"]["id"]

    resp_a = await api_client.get("/api/v1/vitals/records/mine", headers=_auth_header(token_a))
    assert resp_a.status_code == 200
    ids_a = [row["id"] for row in resp_a.json()["data"]]
    assert record_a_id in ids_a
    assert record_b_id not in ids_a

    resp_b = await api_client.get("/api/v1/vitals/records/mine", headers=_auth_header(token_b))
    assert resp_b.status_code == 200
    ids_b = [row["id"] for row in resp_b.json()["data"]]
    assert record_b_id in ids_b
    assert record_a_id not in ids_b


async def test_list_my_vitals_records_newest_first_with_pagination_meta(
    api_client, real_session, grant_permission, reception_service
):
    actor, access_token = await _create_and_login(api_client, real_session, "my-records-order")
    await grant_permission(actor, PERMISSION_VITALS_RECORD)

    visit_1 = await _make_visit(reception_service, actor, "MyRecordsOrder1", vitals_required=True)
    resp_1 = await api_client.post(
        "/api/v1/vitals",
        json={"visit_id": str(visit_1.id), "systolic_bp": 100, "temperature": 97.0},
        headers=_auth_header(access_token),
    )
    assert resp_1.status_code == 201
    first_id = resp_1.json()["data"]["id"]

    visit_2 = await _make_visit(reception_service, actor, "MyRecordsOrder2", vitals_required=True)
    resp_2 = await api_client.post(
        "/api/v1/vitals",
        json={"visit_id": str(visit_2.id), "systolic_bp": 140, "temperature": 101.0},
        headers=_auth_header(access_token),
    )
    assert resp_2.status_code == 201
    second_id = resp_2.json()["data"]["id"]

    resp = await api_client.get(
        "/api/v1/vitals/records/mine",
        params={"page": 1, "page_size": 20},
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 200
    body = resp.json()
    ids = [row["id"] for row in body["data"]]
    # Newest first — the second-recorded entry appears before the first.
    assert ids.index(second_id) < ids.index(first_id)
    assert body["meta"]["page"] == 1
    assert body["meta"]["page_size"] == 20
    assert body["meta"]["total"] >= 2

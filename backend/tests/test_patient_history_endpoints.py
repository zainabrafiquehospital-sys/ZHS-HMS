"""Full end-to-end HTTP tests for the Patient History module — see
tests/test_patients_endpoints.py's identical module docstring.

The permission-composition tests below are this module's real point:
`patients:history:read` alone gates reaching the endpoint at all, but
each section of the response is independently re-checked against the
actor's own other permissions (visits:read/vitals:read/
consultation:read/billing:read/lab:read/pharmacy:read) — see
app/modules/patient_history/router.py's own docstring."""

from app.modules.auth.models import User, UserStatus
from app.modules.auth.password_service import PasswordService
from app.modules.auth.repository import UserRepository
from app.modules.billing.constants import PERMISSION_BILLING_READ
from app.modules.consultation.constants import PERMISSION_CONSULTATION_READ
from app.modules.lab.constants import (
    PERMISSION_LAB_BILL,
    PERMISSION_LAB_MANAGE,
    PERMISSION_LAB_READ,
)
from app.modules.patients.constants import PERMISSION_PATIENTS_CREATE, PERMISSION_PATIENTS_HISTORY_READ
from app.modules.pharmacy.constants import (
    PERMISSION_PHARMACY_BILL,
    PERMISSION_PHARMACY_MANAGE,
    PERMISSION_PHARMACY_READ,
)
from app.modules.reception.constants import PERMISSION_RECEPTION_REGISTER_VISIT
from app.modules.visits.constants import PERMISSION_VISITS_READ
from app.modules.vitals.constants import PERMISSION_VITALS_READ
from tests.conftest import (
    TEST_LAB_TEST_NAME_PREFIX,
    TEST_MEDICINE_NAME_PREFIX,
    TEST_PATIENT_NAME_PREFIX,
    make_test_email,
)

_PASSWORD = "Str0ng!Passw0rd#2026"


async def _create_and_login(api_client, real_session, suffix: str) -> tuple[User, str]:
    password_hash = await PasswordService().hash(_PASSWORD)
    email = make_test_email(suffix)
    user = await UserRepository(real_session).add(
        User(
            email=email,
            password_hash=password_hash,
            full_name="Patient History Endpoint Actor",
            status=UserStatus.ACTIVE,
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


async def _register_visit(api_client, access_token: str, suffix: str) -> str:
    """Registers one visit (with a fresh Patient) via the real
    registration endpoint and returns the new Patient's id — the
    caller needs `reception:register_visit` for this to succeed."""
    resp = await api_client.post(
        "/api/v1/reception/visits",
        json={
            "new_patient": {
                "full_name": f"{TEST_PATIENT_NAME_PREFIX}History{suffix}",
                "guardian_name": None,
                "gender": "female",
                "age_years": 29,
                "phone_number": "03001234567",
                "cnic": None,
                "address": None,
            },
            "procedures": [{"name": "Consultation", "amount": "1500.00"}],
            "vitals_required": False,
            "initial_payment_amount": "1500.00",
            "initial_payment_method": "cash",
        },
        headers=_auth_header(access_token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]["patient"]["id"]


# ---------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------


async def test_get_history_requires_authentication(api_client):
    resp = await api_client.get("/api/v1/patients/00000000-0000-0000-0000-000000000000/history")

    assert resp.status_code == 401


async def test_get_history_without_permission_is_forbidden(api_client, real_session):
    _actor, access_token = await _create_and_login(api_client, real_session, "no-perm-history")

    resp = await api_client.get(
        "/api/v1/patients/00000000-0000-0000-0000-000000000000/history",
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 403


async def test_get_history_unknown_patient_returns_404(api_client, real_session, grant_permission):
    actor, access_token = await _create_and_login(api_client, real_session, "history-404")
    await grant_permission(actor, PERMISSION_PATIENTS_HISTORY_READ)

    resp = await api_client.get(
        "/api/v1/patients/00000000-0000-0000-0000-000000000000/history",
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "PATIENT_NOT_FOUND"


# ---------------------------------------------------------------------
# Per-section permission composition — the real point of this module
# ---------------------------------------------------------------------


async def test_get_history_with_only_visits_read_shows_visits_and_hides_everything_else(
    api_client, real_session, grant_permission
):
    """Mirrors Reception's actual real-world grant set for this
    endpoint minus lab:read/pharmacy:read, isolating `visits:read`
    alone — every other section must come back `null`, never `[]`,
    and never cause the whole request to fail."""
    actor, access_token = await _create_and_login(api_client, real_session, "history-visits-only")
    await grant_permission(actor, PERMISSION_RECEPTION_REGISTER_VISIT)
    await grant_permission(actor, PERMISSION_PATIENTS_HISTORY_READ)
    await grant_permission(actor, PERMISSION_VISITS_READ)
    patient_id = await _register_visit(api_client, access_token, "VisitsOnly")

    resp = await api_client.get(
        f"/api/v1/patients/{patient_id}/history", headers=_auth_header(access_token)
    )

    assert resp.status_code == 200
    body = resp.json()["data"]
    assert len(body["visits"]) == 1
    assert body["vitals"] is None
    assert body["consultations"] is None
    assert body["invoices"] is None
    assert body["lab_bills"] is None
    assert body["pharmacy_bills"] is None


async def test_get_history_without_visits_read_hides_visits_too(
    api_client, real_session, grant_permission
):
    """`patients:history:read` alone, deliberately withholding
    `visits:read` — confirms the visits section is genuinely re-checked
    like every other section, not hardcoded to always show (see
    app/modules/patient_history/schemas.py's own docstring on this)."""
    setup_actor, setup_token = await _create_and_login(api_client, real_session, "history-setup")
    await grant_permission(setup_actor, PERMISSION_RECEPTION_REGISTER_VISIT)
    patient_id = await _register_visit(api_client, setup_token, "NoVisitsRead")

    actor, access_token = await _create_and_login(api_client, real_session, "history-no-visits")
    await grant_permission(actor, PERMISSION_PATIENTS_HISTORY_READ)

    resp = await api_client.get(
        f"/api/v1/patients/{patient_id}/history", headers=_auth_header(access_token)
    )

    assert resp.status_code == 200
    assert resp.json()["data"]["visits"] is None


async def test_get_history_with_every_section_permission_shows_every_section(
    api_client, real_session, grant_permission
):
    """The `admin`-shaped case — every relevant read permission granted
    at once, every section comes back a real (here, empty) list rather
    than `null`."""
    actor, access_token = await _create_and_login(api_client, real_session, "history-full")
    await grant_permission(actor, PERMISSION_RECEPTION_REGISTER_VISIT)
    await grant_permission(actor, PERMISSION_PATIENTS_HISTORY_READ)
    await grant_permission(actor, PERMISSION_VISITS_READ)
    await grant_permission(actor, PERMISSION_VITALS_READ)
    await grant_permission(actor, PERMISSION_CONSULTATION_READ)
    await grant_permission(actor, PERMISSION_BILLING_READ)
    await grant_permission(actor, PERMISSION_LAB_READ)
    await grant_permission(actor, PERMISSION_PHARMACY_READ)
    patient_id = await _register_visit(api_client, access_token, "FullAccess")

    resp = await api_client.get(
        f"/api/v1/patients/{patient_id}/history", headers=_auth_header(access_token)
    )

    assert resp.status_code == 200
    body = resp.json()["data"]
    assert len(body["visits"]) == 1
    assert body["vitals"] == []
    assert body["consultations"] == []
    assert body["invoices"] == []
    assert body["lab_bills"] == []
    assert body["pharmacy_bills"] == []


# ---------------------------------------------------------------------
# GET /patients/history/visits — the Patient History page's own
# always-visible, hospital-wide visit list
# ---------------------------------------------------------------------


async def test_list_history_visits_requires_authentication(api_client):
    resp = await api_client.get("/api/v1/patients/history/visits")

    assert resp.status_code == 401


async def test_list_history_visits_without_permission_is_forbidden(api_client, real_session):
    _actor, access_token = await _create_and_login(api_client, real_session, "no-perm-list")

    resp = await api_client.get(
        "/api/v1/patients/history/visits", headers=_auth_header(access_token)
    )

    assert resp.status_code == 403


async def test_list_history_visits_search_isolates_a_matching_patient(
    api_client, real_session, grant_permission
):
    """The default (unfiltered) list is genuinely hospital-wide, so
    this test isolates its assertion via a unique search term instead
    of asserting an exact total — the same reasoning
    test_get_history_with_only_visits_read_shows_visits_and_hides_everything_else
    already uses one row at a time for."""
    actor, access_token = await _create_and_login(api_client, real_session, "history-list-search")
    await grant_permission(actor, PERMISSION_RECEPTION_REGISTER_VISIT)
    await grant_permission(actor, PERMISSION_PATIENTS_HISTORY_READ)
    await grant_permission(actor, PERMISSION_VISITS_READ)
    patient_id = await _register_visit(api_client, access_token, "ListSearchMatch")

    resp = await api_client.get(
        "/api/v1/patients/history/visits",
        params={"search": f"{TEST_PATIENT_NAME_PREFIX}HistoryListSearchMatch"},
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["data"][0]["patient_id"] == patient_id
    assert body["meta"]["total"] == 1
    assert len(body["data"]) == 1


async def test_list_history_visits_search_with_no_match_returns_empty(
    api_client, real_session, grant_permission
):
    """A search term matching no patient resolves to an empty
    `patient_ids` list, not `None` — this must yield zero visits, not
    silently fall back to the full hospital-wide list (see
    VisitRepository.search's own `IN ()` docstring)."""
    actor, access_token = await _create_and_login(api_client, real_session, "history-list-nomatch")
    await grant_permission(actor, PERMISSION_PATIENTS_HISTORY_READ)

    resp = await api_client.get(
        "/api/v1/patients/history/visits",
        params={"search": "NoSuchPatientNameAtAllXyz123"},
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["data"] == []
    assert body["meta"]["total"] == 0


async def test_list_history_visits_date_range_narrows_results(
    api_client, real_session, grant_permission
):
    actor, access_token = await _create_and_login(api_client, real_session, "history-list-range")
    await grant_permission(actor, PERMISSION_RECEPTION_REGISTER_VISIT)
    await grant_permission(actor, PERMISSION_PATIENTS_HISTORY_READ)
    await grant_permission(actor, PERMISSION_VISITS_READ)
    patient_id = await _register_visit(api_client, access_token, "ListDateRange")

    far_past_resp = await api_client.get(
        "/api/v1/patients/history/visits",
        params={
            "search": f"{TEST_PATIENT_NAME_PREFIX}HistoryListDateRange",
            "start_date": "2000-01-01",
            "end_date": "2000-01-02",
        },
        headers=_auth_header(access_token),
    )
    assert far_past_resp.status_code == 200
    assert far_past_resp.json()["data"] == []

    unfiltered_resp = await api_client.get(
        "/api/v1/patients/history/visits",
        params={"search": f"{TEST_PATIENT_NAME_PREFIX}HistoryListDateRange"},
        headers=_auth_header(access_token),
    )
    assert unfiltered_resp.status_code == 200
    assert unfiltered_resp.json()["data"][0]["patient_id"] == patient_id


async def test_list_history_visits_pagination_meta_reflects_page_and_page_size(
    api_client, real_session, grant_permission
):
    actor, access_token = await _create_and_login(api_client, real_session, "history-list-page")
    await grant_permission(actor, PERMISSION_PATIENTS_HISTORY_READ)

    resp = await api_client.get(
        "/api/v1/patients/history/visits",
        params={"page": 2, "page_size": 5},
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 200
    meta = resp.json()["meta"]
    assert meta["page"] == 2
    assert meta["page_size"] == 5


# ---------------------------------------------------------------------
# Unified feed — Visit/MedicineBill/LabBill in one list
# ---------------------------------------------------------------------


async def _create_medicine(api_client, access_token: str, name: str) -> str:
    resp = await api_client.post(
        "/api/v1/pharmacy/medicines",
        json={"name": name, "category": "tablet", "unit_price": "50.00"},
        headers=_auth_header(access_token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]["id"]


async def _create_standalone_medicine_bill(api_client, access_token: str, medicine_id: str) -> dict:
    """A walk-in medicine bill with no `visit_id` — the exact real-
    world shape confirmed against production Token #802 (see the
    investigation this feature was built from)."""
    resp = await api_client.post(
        "/api/v1/pharmacy/bills",
        json={"visit_id": None, "items": [{"medicine_id": medicine_id, "quantity": 1}]},
        headers=_auth_header(access_token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]


async def _create_patient(api_client, access_token: str, full_name: str) -> str:
    resp = await api_client.post(
        "/api/v1/patients",
        json={
            "full_name": full_name,
            "guardian_name": None,
            "gender": "female",
            "age_years": 31,
            "phone_number": "03001234567",
            "cnic": None,
            "address": None,
        },
        headers=_auth_header(access_token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]["id"]


async def _create_lab_test(api_client, access_token: str, name: str) -> str:
    resp = await api_client.post(
        "/api/v1/lab/tests",
        json={"name": name, "category": "pathology", "price": "500.00"},
        headers=_auth_header(access_token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]["id"]


async def _create_lab_bill(api_client, access_token: str, patient_id: str, lab_test_id: str) -> dict:
    resp = await api_client.post(
        "/api/v1/lab/bills",
        json={"patient_id": patient_id, "items": [{"lab_test_id": lab_test_id}]},
        headers=_auth_header(access_token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]


async def test_list_history_records_finds_standalone_medicine_bill_by_token(
    api_client, real_session, grant_permission
):
    """The exact bug this redesign fixes: a standalone (no visit_id)
    medicine bill, findable only by its own Token #, now appears in
    the feed at all — the old Visit-only list could never show it
    regardless of any patient search."""
    actor, access_token = await _create_and_login(api_client, real_session, "history-medbill-token")
    await grant_permission(actor, PERMISSION_PHARMACY_MANAGE)
    await grant_permission(actor, PERMISSION_PHARMACY_BILL)
    await grant_permission(actor, PERMISSION_PATIENTS_HISTORY_READ)
    await grant_permission(actor, PERMISSION_PHARMACY_READ)
    medicine_id = await _create_medicine(
        api_client, access_token, f"{TEST_MEDICINE_NAME_PREFIX}HistoryMedBillToken"
    )
    bill = await _create_standalone_medicine_bill(api_client, access_token, medicine_id)
    token_digits = bill["queue_token"].replace("Token #", "")

    resp = await api_client.get(
        "/api/v1/patients/history/visits",
        params={"search": token_digits},
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["meta"]["total"] == 1
    row = body["data"][0]
    assert row["record_type"] == "medicine_bill"
    assert row["queue_token"] == bill["queue_token"]
    assert row["patient_id"] is None
    assert row["medicine_bill"]["id"] == bill["id"]
    assert row["visit"] is None
    assert row["lab_bill"] is None


async def test_list_history_records_finds_patient_linked_lab_bill(
    api_client, real_session, grant_permission
):
    """A LabBill linked directly to a real Patient (no Visit involved
    at all — LabBill has no visit_id column) is now reachable from the
    always-visible list by that patient's own name, not just from a
    drill-down the receptionist would have had no way to reach."""
    actor, access_token = await _create_and_login(api_client, real_session, "history-labbill-patient")
    await grant_permission(actor, PERMISSION_PATIENTS_CREATE)
    await grant_permission(actor, PERMISSION_LAB_MANAGE)
    await grant_permission(actor, PERMISSION_LAB_BILL)
    await grant_permission(actor, PERMISSION_PATIENTS_HISTORY_READ)
    await grant_permission(actor, PERMISSION_LAB_READ)
    patient_id = await _create_patient(
        api_client, access_token, f"{TEST_PATIENT_NAME_PREFIX}HistoryLabBillPatient"
    )
    lab_test_id = await _create_lab_test(
        api_client, access_token, f"{TEST_LAB_TEST_NAME_PREFIX}HistoryLabBillPatientTest"
    )
    bill = await _create_lab_bill(api_client, access_token, patient_id, lab_test_id)

    resp = await api_client.get(
        "/api/v1/patients/history/visits",
        params={"search": f"{TEST_PATIENT_NAME_PREFIX}HistoryLabBillPatient"},
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["meta"]["total"] == 1
    row = body["data"][0]
    assert row["record_type"] == "lab_bill"
    assert row["patient_id"] == patient_id
    assert row["lab_bill"]["id"] == bill["id"]


async def test_list_history_records_hides_medicine_bill_without_pharmacy_permission(
    api_client, real_session, grant_permission
):
    """Per-record-type permission gating — an actor holding
    `patients:history:read` but not `pharmacy:read` never sees a
    medicine bill row in the feed at all, even one that genuinely
    matches their search, the same "dropped from the query entirely,
    not fetched-then-filtered" behavior the drill-down's own per-
    section gating already establishes."""
    setup_actor, setup_token = await _create_and_login(api_client, real_session, "history-hide-setup")
    await grant_permission(setup_actor, PERMISSION_PHARMACY_MANAGE)
    await grant_permission(setup_actor, PERMISSION_PHARMACY_BILL)
    medicine_id = await _create_medicine(
        api_client, setup_token, f"{TEST_MEDICINE_NAME_PREFIX}HistoryHideMedBill"
    )
    bill = await _create_standalone_medicine_bill(api_client, setup_token, medicine_id)
    token_digits = bill["queue_token"].replace("Token #", "")

    actor, access_token = await _create_and_login(api_client, real_session, "history-hide-actor")
    await grant_permission(actor, PERMISSION_PATIENTS_HISTORY_READ)
    await grant_permission(actor, PERMISSION_VISITS_READ)
    # Deliberately NOT PERMISSION_PHARMACY_READ.

    resp = await api_client.get(
        "/api/v1/patients/history/visits",
        params={"search": token_digits},
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["data"] == []
    assert body["meta"]["total"] == 0

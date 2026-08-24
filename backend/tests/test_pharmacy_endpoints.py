"""Full end-to-end HTTP tests for the Pharmacy / Medicine Billing module
— see tests/test_billing_endpoints.py's identical module docstring."""

from datetime import UTC, datetime
from decimal import Decimal

from app.modules.auth.models import User, UserStatus
from app.modules.auth.password_service import PasswordService
from app.modules.auth.repository import UserRepository
from app.modules.pharmacy.constants import (
    PERMISSION_PHARMACY_BILL,
    PERMISSION_PHARMACY_DELETE_BILL,
    PERMISSION_PHARMACY_MANAGE,
    PERMISSION_PHARMACY_READ,
    PERMISSION_PHARMACY_UPDATE_BILL,
)
from app.modules.reception.constants import PERMISSION_RECEPTION_REGISTER_VISIT
from tests.conftest import TEST_MEDICINE_NAME_PREFIX, TEST_PATIENT_NAME_PREFIX, make_test_email

_PASSWORD = "Str0ng!Passw0rd#2026"


async def _create_and_login(api_client, real_session, suffix: str) -> tuple[User, str]:
    password_hash = await PasswordService().hash(_PASSWORD)
    email = make_test_email(suffix)
    user = await UserRepository(real_session).add(
        User(
            email=email,
            password_hash=password_hash,
            full_name="Pharmacy Endpoint Actor",
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


async def _register_visit(api_client, access_token, suffix: str) -> str:
    resp = await api_client.post(
        "/api/v1/reception/visits",
        json={
            "new_patient": {
                "full_name": f"{TEST_PATIENT_NAME_PREFIX}PharmacyHttp{suffix}",
                "guardian_name": None,
                "gender": "female",
                "age_years": 29,
                "phone_number": "03001234567",
                "cnic": None,
                "address": None,
            },
            "procedures": [{"name": "Consultation", "amount": "1000.00"}],
            "vitals_required": False,
            "initial_payment_amount": "0.01",
            "initial_payment_method": "cash",
        },
        headers=_auth_header(access_token),
    )
    return resp.json()["data"]["visit"]["id"]


async def _create_medicine(api_client, access_token, name: str, *, price: str = "50.00") -> str:
    resp = await api_client.post(
        "/api/v1/pharmacy/medicines",
        json={"name": name, "category": "tablet", "unit_price": price},
        headers=_auth_header(access_token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]["id"]


async def test_search_medicines_requires_permission(api_client, real_session):
    _actor, access_token = await _create_and_login(api_client, real_session, "no-perm-search")

    resp = await api_client.get(
        "/api/v1/pharmacy/medicines/search",
        params={"search": "para"},
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 403


async def test_create_medicine_requires_manage_permission(
    api_client, real_session, grant_permission
):
    """Structural proof of the segregation of duties: a role holding only
    `pharmacy:bill`/`pharmacy:read` cannot create or edit the price
    list — that requires the separate `pharmacy:manage` code."""
    actor, access_token = await _create_and_login(api_client, real_session, "no-manage")
    await grant_permission(actor, PERMISSION_PHARMACY_BILL)
    await grant_permission(actor, PERMISSION_PHARMACY_READ)

    resp = await api_client.post(
        "/api/v1/pharmacy/medicines",
        json={
            "name": f"{TEST_MEDICINE_NAME_PREFIX}NoManage",
            "category": "tablet",
            "unit_price": "10.00",
        },
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 403


async def test_create_bill_requires_permission(api_client, real_session, grant_permission):
    actor, access_token = await _create_and_login(api_client, real_session, "no-perm-bill")
    await grant_permission(actor, PERMISSION_PHARMACY_MANAGE)
    medicine_id = await _create_medicine(
        api_client, access_token, f"{TEST_MEDICINE_NAME_PREFIX}NoBillPerm"
    )

    resp = await api_client.post(
        "/api/v1/pharmacy/bills",
        json={"visit_id": None, "items": [{"medicine_id": medicine_id, "quantity": 2}]},
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 403


async def test_get_bill_stats_by_creator_requires_permission(api_client, real_session):
    _actor, access_token = await _create_and_login(api_client, real_session, "stats-no-perm")

    resp = await api_client.get(
        "/api/v1/pharmacy/bills/stats/by-creator", headers=_auth_header(access_token)
    )

    assert resp.status_code == 403


async def test_get_bill_stats_by_creator_returns_accurate_counts_and_revenue(
    api_client, real_session, grant_permission
):
    actor, access_token = await _create_and_login(api_client, real_session, "stats-correctness")
    await grant_permission(actor, PERMISSION_PHARMACY_MANAGE)
    await grant_permission(actor, PERMISSION_PHARMACY_BILL)
    await grant_permission(actor, PERMISSION_PHARMACY_READ)
    await grant_permission(actor, PERMISSION_RECEPTION_REGISTER_VISIT)
    medicine_id = await _create_medicine(
        api_client, access_token, f"{TEST_MEDICINE_NAME_PREFIX}StatsCorrectness", price="25.00"
    )
    visit_id = await _register_visit(api_client, access_token, "StatsCorrectness")

    bill_resp = await api_client.post(
        "/api/v1/pharmacy/bills",
        json={"visit_id": visit_id, "items": [{"medicine_id": medicine_id, "quantity": 4}]},
        headers=_auth_header(access_token),
    )
    assert bill_resp.status_code == 201, bill_resp.text

    resp = await api_client.get(
        "/api/v1/pharmacy/bills/stats/by-creator", headers=_auth_header(access_token)
    )

    assert resp.status_code == 200
    rows = {row["user_id"]: row for row in resp.json()["data"]}
    assert rows[str(actor.id)]["count"] == 1
    assert rows[str(actor.id)]["revenue"] == "100.00"


async def test_full_pharmacy_lifecycle_via_http(api_client, real_session, grant_permission):
    admin, admin_token = await _create_and_login(api_client, real_session, "admin-lifecycle")
    await grant_permission(admin, PERMISSION_PHARMACY_MANAGE)
    await grant_permission(admin, PERMISSION_PHARMACY_READ)

    receptionist, reception_token = await _create_and_login(
        api_client, real_session, "reception-lifecycle"
    )
    await grant_permission(receptionist, PERMISSION_PHARMACY_BILL)
    await grant_permission(receptionist, PERMISSION_PHARMACY_READ)
    await grant_permission(receptionist, PERMISSION_RECEPTION_REGISTER_VISIT)

    med_a = await _create_medicine(
        api_client, admin_token, f"{TEST_MEDICINE_NAME_PREFIX}Paracetamol", price="20.00"
    )
    med_b = await _create_medicine(
        api_client, admin_token, f"{TEST_MEDICINE_NAME_PREFIX}Ibuprofen", price="35.50"
    )

    # Case-insensitive (search term lowercase, stored name capitalized)
    # partial-name search, active medicines only.
    search_resp = await api_client.get(
        "/api/v1/pharmacy/medicines/search",
        params={"search": "paracetamol"},
        headers=_auth_header(reception_token),
    )
    assert search_resp.status_code == 200
    names = [item["name"] for item in search_resp.json()["data"]]
    assert f"{TEST_MEDICINE_NAME_PREFIX}Paracetamol" in names

    visit_id = await _register_visit(api_client, reception_token, "Lifecycle")

    bill_resp = await api_client.post(
        "/api/v1/pharmacy/bills",
        json={
            "visit_id": visit_id,
            "items": [
                {"medicine_id": med_a, "quantity": 3},
                {"medicine_id": med_b, "quantity": 2},
            ],
        },
        headers=_auth_header(reception_token),
    )
    assert bill_resp.status_code == 201, bill_resp.text
    bill_body = bill_resp.json()["data"]
    # 3 * 20.00 + 2 * 35.50 = 60.00 + 71.00 = 131.00
    assert bill_body["total_amount"] == "131.00"
    assert bill_body["visit_id"] == visit_id
    assert len(bill_body["items"]) == 2
    bill_id = bill_body["id"]

    get_resp = await api_client.get(
        f"/api/v1/pharmacy/bills/{bill_id}", headers=_auth_header(reception_token)
    )
    assert get_resp.status_code == 200
    assert get_resp.json()["data"]["total_amount"] == "131.00"

    print_resp = await api_client.get(
        f"/api/v1/pharmacy/bills/{bill_id}/print", headers=_auth_header(reception_token)
    )
    assert print_resp.status_code == 200
    assert print_resp.headers["content-type"].startswith("text/html")
    assert "131.00" in print_resp.text
    assert "Paracetamol" in print_resp.text
    assert "03001234567" in print_resp.text

    today = datetime.now(UTC).date().isoformat()
    list_resp = await api_client.get(
        "/api/v1/pharmacy/bills",
        params={"date": today},
        headers=_auth_header(reception_token),
    )
    assert list_resp.status_code == 200
    listed = list_resp.json()["data"]
    matching = [row for row in listed if row["id"] == bill_id]
    assert len(matching) == 1
    assert matching[0]["item_count"] == 2
    assert matching[0]["total_amount"] == "131.00"


# ---------------------------------------------------------------------
# Unified token sequence (2026-08-20 addition) — a MedicineBill draws
# its own queue_token from the exact same Postgres sequence Visit uses,
# so numbers interleave in true chronological order across both entity
# types. See app/modules/pharmacy/models.py's MedicineBill.queue_token
# docstring for the full mechanism.
# ---------------------------------------------------------------------


def _token_value(token: str) -> int:
    """"Token #000295" -> 295, for numeric comparison in the tests
    below — the exact format both VisitService._generate_queue_token
    and PharmacyService._generate_queue_token produce."""
    return int(token.removeprefix("Token #"))


async def test_new_bill_has_a_queue_token_in_the_standard_format(
    api_client, real_session, grant_permission
):
    actor, access_token = await _create_and_login(api_client, real_session, "bill-has-token")
    await grant_permission(actor, PERMISSION_PHARMACY_MANAGE)
    await grant_permission(actor, PERMISSION_PHARMACY_BILL)
    medicine_id = await _create_medicine(
        api_client, access_token, f"{TEST_MEDICINE_NAME_PREFIX}HasToken"
    )

    resp = await api_client.post(
        "/api/v1/pharmacy/bills",
        json={"visit_id": None, "items": [{"medicine_id": medicine_id, "quantity": 1}]},
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 201, resp.text
    token = resp.json()["data"]["queue_token"]
    assert token is not None
    assert token.startswith("Token #")
    assert _token_value(token) > 0


async def test_two_bills_created_in_a_row_get_consecutive_tokens(
    api_client, real_session, grant_permission
):
    actor, access_token = await _create_and_login(api_client, real_session, "bill-consecutive")
    await grant_permission(actor, PERMISSION_PHARMACY_MANAGE)
    await grant_permission(actor, PERMISSION_PHARMACY_BILL)
    medicine_id = await _create_medicine(
        api_client, access_token, f"{TEST_MEDICINE_NAME_PREFIX}Consecutive"
    )

    first_resp = await api_client.post(
        "/api/v1/pharmacy/bills",
        json={"visit_id": None, "items": [{"medicine_id": medicine_id, "quantity": 1}]},
        headers=_auth_header(access_token),
    )
    second_resp = await api_client.post(
        "/api/v1/pharmacy/bills",
        json={"visit_id": None, "items": [{"medicine_id": medicine_id, "quantity": 1}]},
        headers=_auth_header(access_token),
    )

    first_value = _token_value(first_resp.json()["data"]["queue_token"])
    second_value = _token_value(second_resp.json()["data"]["queue_token"])
    assert second_value == first_value + 1


async def test_visit_and_medicine_bill_tokens_interleave_chronologically(
    api_client, real_session, grant_permission
):
    """The core requirement, tested directly: registering a Visit, then
    creating a MedicineBill, then registering a second Visit must
    produce three strictly consecutive numbers (N, N+1, N+2) — never
    two rows (of either type) sharing a number, never an unexplained
    gap that "went to the other type" instead."""
    actor, access_token = await _create_and_login(api_client, real_session, "interleave")
    await grant_permission(actor, PERMISSION_RECEPTION_REGISTER_VISIT)
    await grant_permission(actor, PERMISSION_PHARMACY_MANAGE)
    await grant_permission(actor, PERMISSION_PHARMACY_BILL)
    medicine_id = await _create_medicine(
        api_client, access_token, f"{TEST_MEDICINE_NAME_PREFIX}Interleave"
    )

    def _register_visit_resp():
        return api_client.post(
            "/api/v1/reception/visits",
            json={
                "new_patient": {
                    "full_name": f"{TEST_PATIENT_NAME_PREFIX}Interleave",
                    "guardian_name": None,
                    "gender": "female",
                    "age_years": 29,
                    "phone_number": "03001234567",
                    "cnic": None,
                    "address": None,
                },
                "procedures": [{"name": "Consultation", "amount": "1000.00"}],
                "vitals_required": False,
                "initial_payment_amount": "0.01",
                "initial_payment_method": "cash",
            },
            headers=_auth_header(access_token),
        )

    visit_1_resp = await _register_visit_resp()
    bill_resp = await api_client.post(
        "/api/v1/pharmacy/bills",
        json={"visit_id": None, "items": [{"medicine_id": medicine_id, "quantity": 1}]},
        headers=_auth_header(access_token),
    )
    visit_2_resp = await _register_visit_resp()

    visit_1_value = _token_value(visit_1_resp.json()["data"]["visit"]["queue_token"])
    bill_value = _token_value(bill_resp.json()["data"]["queue_token"])
    visit_2_value = _token_value(visit_2_resp.json()["data"]["visit"]["queue_token"])

    assert bill_value == visit_1_value + 1
    assert visit_2_value == bill_value + 1


async def test_standalone_walk_in_bill_has_no_visit(api_client, real_session, grant_permission):
    actor, access_token = await _create_and_login(api_client, real_session, "walk-in")
    await grant_permission(actor, PERMISSION_PHARMACY_MANAGE)
    await grant_permission(actor, PERMISSION_PHARMACY_BILL)
    medicine_id = await _create_medicine(
        api_client, access_token, f"{TEST_MEDICINE_NAME_PREFIX}WalkIn"
    )

    resp = await api_client.post(
        "/api/v1/pharmacy/bills",
        json={"visit_id": None, "items": [{"medicine_id": medicine_id, "quantity": 1}]},
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 201, resp.text
    assert resp.json()["data"]["visit_id"] is None


async def test_print_bill_shows_its_own_queue_token_not_uuid_fragment(
    api_client, real_session, grant_permission
):
    """The 2026-08-20 print redesign: a bill created after the unified
    sequence exists shows its own real token in the title box, never
    the old `MED-<uuid fragment>` placeholder."""
    actor, access_token = await _create_and_login(api_client, real_session, "print-own-token")
    await grant_permission(actor, PERMISSION_PHARMACY_MANAGE)
    await grant_permission(actor, PERMISSION_PHARMACY_BILL)
    await grant_permission(actor, PERMISSION_PHARMACY_READ)
    medicine_id = await _create_medicine(
        api_client, access_token, f"{TEST_MEDICINE_NAME_PREFIX}PrintOwnToken"
    )

    bill_resp = await api_client.post(
        "/api/v1/pharmacy/bills",
        json={"visit_id": None, "items": [{"medicine_id": medicine_id, "quantity": 1}]},
        headers=_auth_header(access_token),
    )
    bill_id = bill_resp.json()["data"]["id"]
    token = bill_resp.json()["data"]["queue_token"]

    print_resp = await api_client.get(
        f"/api/v1/pharmacy/bills/{bill_id}/print", headers=_auth_header(access_token)
    )
    assert print_resp.status_code == 200
    assert token in print_resp.text
    assert "MED-" not in print_resp.text


async def test_print_bill_omits_mr_number_and_queue_token_rows(
    api_client, real_session, grant_permission
):
    """The Patient/Visit Reference section no longer shows MR Number or
    a separate Queue Token row at all (2026-08-20) — this bill's own
    number in the title box is the slip's one and only number."""
    actor, access_token = await _create_and_login(api_client, real_session, "print-no-mr-row")
    await grant_permission(actor, PERMISSION_RECEPTION_REGISTER_VISIT)
    await grant_permission(actor, PERMISSION_PHARMACY_MANAGE)
    await grant_permission(actor, PERMISSION_PHARMACY_BILL)
    await grant_permission(actor, PERMISSION_PHARMACY_READ)
    visit_id = await _register_visit(api_client, access_token, "NoMrRow")
    medicine_id = await _create_medicine(
        api_client, access_token, f"{TEST_MEDICINE_NAME_PREFIX}NoMrRow"
    )

    bill_resp = await api_client.post(
        "/api/v1/pharmacy/bills",
        json={"visit_id": visit_id, "items": [{"medicine_id": medicine_id, "quantity": 1}]},
        headers=_auth_header(access_token),
    )
    bill_id = bill_resp.json()["data"]["id"]

    print_resp = await api_client.get(
        f"/api/v1/pharmacy/bills/{bill_id}/print", headers=_auth_header(access_token)
    )
    assert print_resp.status_code == 200
    assert "MR Number" not in print_resp.text
    assert "Queue Token" not in print_resp.text
    # The reference section's rows are still there, just fewer — and,
    # since the 2026-08-24 80mm-receipt redesign, stacked in a single
    # column (class="section") rather than the old 2-column body-grid.
    assert "Patient Name" in print_resp.text
    assert "Contact Number" in print_resp.text
    assert 'class="section"' in print_resp.text


async def test_create_bill_with_manual_patient_details_prints_correctly(
    api_client, real_session, grant_permission
):
    """Manual Entry mode: no Patient/Visit lookup or creation, purely
    display data — but it must show up on the printed slip in the same
    reference-section spot a linked visit's real Patient would (Age/
    Contact Number rendering added earlier for that case, reused as-is
    — see app/modules/pharmacy/router.py's `print_bill` docstring)."""
    actor, access_token = await _create_and_login(api_client, real_session, "manual-entry")
    await grant_permission(actor, PERMISSION_PHARMACY_MANAGE)
    await grant_permission(actor, PERMISSION_PHARMACY_BILL)
    await grant_permission(actor, PERMISSION_PHARMACY_READ)
    medicine_id = await _create_medicine(
        api_client, access_token, f"{TEST_MEDICINE_NAME_PREFIX}ManualEntry", price="40.00"
    )

    bill_resp = await api_client.post(
        "/api/v1/pharmacy/bills",
        json={
            "visit_id": None,
            "items": [{"medicine_id": medicine_id, "quantity": 1}],
            "manual_patient_name": "Zainab Rafique",
            "manual_patient_age": 34,
            "manual_patient_phone": "03211234567",
        },
        headers=_auth_header(access_token),
    )
    assert bill_resp.status_code == 201, bill_resp.text
    body = bill_resp.json()["data"]
    assert body["visit_id"] is None
    assert body["manual_patient_name"] == "Zainab Rafique"
    assert body["manual_patient_age"] == 34
    assert body["manual_patient_phone"] == "03211234567"
    bill_id = body["id"]

    print_resp = await api_client.get(
        f"/api/v1/pharmacy/bills/{bill_id}/print", headers=_auth_header(access_token)
    )
    assert print_resp.status_code == 200
    assert "Zainab Rafique" in print_resp.text
    assert "34 years" in print_resp.text
    assert "03211234567" in print_resp.text
    # Manual Entry still renders the Patient/Visit Reference section
    # (Name/Age/Contact), just never the walk-in-only "Sale Type" branch
    # — MR Number is gone from this document entirely regardless of
    # which of the three reference states a bill is in (2026-08-20).
    assert "Sale Type" not in print_resp.text  # not the walk-in-only branch

    list_resp = await api_client.get(
        "/api/v1/pharmacy/bills",
        params={"date": datetime.now(UTC).date().isoformat()},
        headers=_auth_header(access_token),
    )
    assert list_resp.status_code == 200
    matching = [row for row in list_resp.json()["data"] if row["id"] == bill_id]
    assert len(matching) == 1
    assert matching[0]["manual_patient_name"] == "Zainab Rafique"


async def test_create_bill_manual_patient_and_visit_id_together_rejected(
    api_client, real_session, grant_permission
):
    actor, access_token = await _create_and_login(api_client, real_session, "manual-plus-visit")
    await grant_permission(actor, PERMISSION_PHARMACY_MANAGE)
    await grant_permission(actor, PERMISSION_PHARMACY_BILL)
    await grant_permission(actor, PERMISSION_RECEPTION_REGISTER_VISIT)
    medicine_id = await _create_medicine(
        api_client, access_token, f"{TEST_MEDICINE_NAME_PREFIX}ManualPlusVisit", price="15.00"
    )
    visit_id = await _register_visit(api_client, access_token, "ManualPlusVisit")

    resp = await api_client.post(
        "/api/v1/pharmacy/bills",
        json={
            "visit_id": visit_id,
            "items": [{"medicine_id": medicine_id, "quantity": 1}],
            "manual_patient_name": "Should Be Rejected",
            "manual_patient_age": 40,
            "manual_patient_phone": "03000000000",
        },
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "MEDICINE_BILL_MANUAL_PATIENT_CONFLICTS_WITH_VISIT"


async def test_create_bill_partial_manual_patient_fields_rejected(
    api_client, real_session, grant_permission
):
    actor, access_token = await _create_and_login(api_client, real_session, "manual-partial")
    await grant_permission(actor, PERMISSION_PHARMACY_MANAGE)
    await grant_permission(actor, PERMISSION_PHARMACY_BILL)
    medicine_id = await _create_medicine(
        api_client, access_token, f"{TEST_MEDICINE_NAME_PREFIX}ManualPartial", price="15.00"
    )

    resp = await api_client.post(
        "/api/v1/pharmacy/bills",
        json={
            "visit_id": None,
            "items": [{"medicine_id": medicine_id, "quantity": 1}],
            "manual_patient_name": "Only Name Given",
        },
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "MEDICINE_BILL_MANUAL_PATIENT_FIELDS_INCOMPLETE"


async def test_create_bill_walk_in_unaffected_by_manual_patient_feature(
    api_client, real_session, grant_permission
):
    """A pure walk-in (neither visit_id nor manual patient fields)
    still works exactly as before — the third, unchanged state."""
    actor, access_token = await _create_and_login(api_client, real_session, "walk-in-unaffected")
    await grant_permission(actor, PERMISSION_PHARMACY_MANAGE)
    await grant_permission(actor, PERMISSION_PHARMACY_BILL)
    await grant_permission(actor, PERMISSION_PHARMACY_READ)
    medicine_id = await _create_medicine(
        api_client, access_token, f"{TEST_MEDICINE_NAME_PREFIX}WalkInUnaffected", price="22.00"
    )

    bill_resp = await api_client.post(
        "/api/v1/pharmacy/bills",
        json={"visit_id": None, "items": [{"medicine_id": medicine_id, "quantity": 1}]},
        headers=_auth_header(access_token),
    )
    assert bill_resp.status_code == 201, bill_resp.text
    body = bill_resp.json()["data"]
    assert body["visit_id"] is None
    assert body["manual_patient_name"] is None
    assert body["manual_patient_age"] is None
    assert body["manual_patient_phone"] is None
    bill_id = body["id"]

    print_resp = await api_client.get(
        f"/api/v1/pharmacy/bills/{bill_id}/print", headers=_auth_header(access_token)
    )
    assert print_resp.status_code == 200
    assert "Sale Type" in print_resp.text
    assert "Walk-in (no visit on file)" in print_resp.text


async def test_create_bill_rejects_inactive_medicine(api_client, real_session, grant_permission):
    actor, access_token = await _create_and_login(api_client, real_session, "inactive-med")
    await grant_permission(actor, PERMISSION_PHARMACY_MANAGE)
    await grant_permission(actor, PERMISSION_PHARMACY_BILL)
    await grant_permission(actor, PERMISSION_PHARMACY_READ)
    medicine_id = await _create_medicine(
        api_client, access_token, f"{TEST_MEDICINE_NAME_PREFIX}Deactivated"
    )

    patch_resp = await api_client.patch(
        f"/api/v1/pharmacy/medicines/{medicine_id}",
        json={"is_active": False},
        headers=_auth_header(access_token),
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["data"]["is_active"] is False

    search_resp = await api_client.get(
        "/api/v1/pharmacy/medicines/search",
        params={"search": TEST_MEDICINE_NAME_PREFIX.strip()},
        headers=_auth_header(access_token),
    )
    assert all(item["id"] != medicine_id for item in search_resp.json()["data"])

    bill_resp = await api_client.post(
        "/api/v1/pharmacy/bills",
        json={"visit_id": None, "items": [{"medicine_id": medicine_id, "quantity": 1}]},
        headers=_auth_header(access_token),
    )
    assert bill_resp.status_code == 422
    assert bill_resp.json()["error"]["code"] == "MEDICINE_INACTIVE"


async def test_create_bill_rejects_unknown_medicine(api_client, real_session, grant_permission):
    actor, access_token = await _create_and_login(api_client, real_session, "unknown-med")
    await grant_permission(actor, PERMISSION_PHARMACY_BILL)

    resp = await api_client.post(
        "/api/v1/pharmacy/bills",
        json={
            "visit_id": None,
            "items": [{"medicine_id": "019fd77d-8445-74c6-be04-b855f517f6fe", "quantity": 1}],
        },
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "MEDICINE_NOT_FOUND"


async def test_new_bill_starts_unpaid_with_zero_paid(api_client, real_session, grant_permission):
    actor, access_token = await _create_and_login(api_client, real_session, "new-bill-unpaid")
    await grant_permission(actor, PERMISSION_PHARMACY_MANAGE)
    await grant_permission(actor, PERMISSION_PHARMACY_BILL)
    medicine_id = await _create_medicine(
        api_client, access_token, f"{TEST_MEDICINE_NAME_PREFIX}Fresh", price="75.00"
    )

    bill_resp = await api_client.post(
        "/api/v1/pharmacy/bills",
        json={"visit_id": None, "items": [{"medicine_id": medicine_id, "quantity": 1}]},
        headers=_auth_header(access_token),
    )

    assert bill_resp.status_code == 201, bill_resp.text
    body = bill_resp.json()["data"]
    assert body["status"] == "unpaid"
    assert body["amount_paid"] == "0.00"
    assert body["payments"] == []


async def test_create_bill_with_initial_payment_records_it_atomically(
    api_client, real_session, grant_permission
):
    """The merged single-step counter flow: create_bill's optional
    initial_payment_amount ("Advance Received" on Finalize & Print)
    records a payment in the same request/commit as creation — same
    MedicineBillPayment audit-row mechanism record_payment uses, never
    a second, separately-failing request."""
    actor, access_token = await _create_and_login(api_client, real_session, "initial-payment-partial")
    await grant_permission(actor, PERMISSION_PHARMACY_MANAGE)
    await grant_permission(actor, PERMISSION_PHARMACY_BILL)
    medicine_id = await _create_medicine(
        api_client, access_token, f"{TEST_MEDICINE_NAME_PREFIX}InitialPartial", price="100.00"
    )

    bill_resp = await api_client.post(
        "/api/v1/pharmacy/bills",
        json={
            "visit_id": None,
            "items": [{"medicine_id": medicine_id, "quantity": 2}],
            "initial_payment_amount": "80.00",
            "initial_payment_method": "cash",
        },
        headers=_auth_header(access_token),
    )

    assert bill_resp.status_code == 201, bill_resp.text
    body = bill_resp.json()["data"]
    assert body["total_amount"] == "200.00"
    assert body["status"] == "partially_paid"
    assert body["amount_paid"] == "80.00"
    assert len(body["payments"]) == 1
    assert body["payments"][0]["amount"] == "80.00"
    assert body["payments"][0]["payment_method"] == "cash"
    pending = float(body["total_amount"]) - float(body["amount_paid"])
    assert pending == 120.00


async def test_create_bill_initial_payment_without_method_rejected(
    api_client, real_session, grant_permission
):
    actor, access_token = await _create_and_login(api_client, real_session, "bill-no-method")
    await grant_permission(actor, PERMISSION_PHARMACY_MANAGE)
    await grant_permission(actor, PERMISSION_PHARMACY_BILL)
    medicine_id = await _create_medicine(
        api_client, access_token, f"{TEST_MEDICINE_NAME_PREFIX}NoMethod", price="50.00"
    )

    resp = await api_client.post(
        "/api/v1/pharmacy/bills",
        json={
            "visit_id": None,
            "items": [{"medicine_id": medicine_id, "quantity": 1}],
            "initial_payment_amount": "50.00",
        },
        headers=_auth_header(access_token),
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "MEDICINE_BILL_PAYMENT_METHOD_REQUIRED"


async def test_record_bill_payment_without_method_rejected_at_schema_level(
    api_client, real_session, grant_permission
):
    actor, access_token = await _create_and_login(api_client, real_session, "bill-record-no-method")
    await grant_permission(actor, PERMISSION_PHARMACY_MANAGE)
    await grant_permission(actor, PERMISSION_PHARMACY_BILL)
    medicine_id = await _create_medicine(
        api_client, access_token, f"{TEST_MEDICINE_NAME_PREFIX}RecordNoMethod", price="50.00"
    )
    bill_resp = await api_client.post(
        "/api/v1/pharmacy/bills",
        json={"visit_id": None, "items": [{"medicine_id": medicine_id, "quantity": 1}]},
        headers=_auth_header(access_token),
    )
    bill_id = bill_resp.json()["data"]["id"]

    resp = await api_client.post(
        f"/api/v1/pharmacy/bills/{bill_id}/pay",
        json={"amount": "50.00"},
        headers=_auth_header(access_token),
    )
    assert resp.status_code == 422


async def test_create_bill_with_initial_payment_paying_in_full(
    api_client, real_session, grant_permission
):
    actor, access_token = await _create_and_login(api_client, real_session, "initial-payment-full")
    await grant_permission(actor, PERMISSION_PHARMACY_MANAGE)
    await grant_permission(actor, PERMISSION_PHARMACY_BILL)
    medicine_id = await _create_medicine(
        api_client, access_token, f"{TEST_MEDICINE_NAME_PREFIX}InitialFull", price="60.00"
    )

    bill_resp = await api_client.post(
        "/api/v1/pharmacy/bills",
        json={
            "visit_id": None,
            "items": [{"medicine_id": medicine_id, "quantity": 1}],
            "initial_payment_amount": "60.00",
            "initial_payment_method": "cash",
        },
        headers=_auth_header(access_token),
    )

    assert bill_resp.status_code == 201, bill_resp.text
    body = bill_resp.json()["data"]
    assert body["status"] == "paid"
    assert body["amount_paid"] == body["total_amount"]
    assert body["paid_at"] is not None


async def test_create_bill_without_initial_payment_then_paid_later_still_works(
    api_client, real_session, grant_permission
):
    """The "finalize now, pay later" path must still work unchanged:
    omitting initial_payment_amount still creates an UNPAID bill with
    amount_paid=0, and a later, separate record_payment call (the "top
    up" action, now surfaced in Admin Overview) still pays it off
    exactly as before."""
    actor, access_token = await _create_and_login(api_client, real_session, "no-initial-payment")
    await grant_permission(actor, PERMISSION_PHARMACY_MANAGE)
    await grant_permission(actor, PERMISSION_PHARMACY_BILL)
    medicine_id = await _create_medicine(
        api_client, access_token, f"{TEST_MEDICINE_NAME_PREFIX}NoInitial", price="45.00"
    )

    bill_resp = await api_client.post(
        "/api/v1/pharmacy/bills",
        json={"visit_id": None, "items": [{"medicine_id": medicine_id, "quantity": 1}]},
        headers=_auth_header(access_token),
    )
    assert bill_resp.status_code == 201, bill_resp.text
    bill_id = bill_resp.json()["data"]["id"]
    assert bill_resp.json()["data"]["status"] == "unpaid"
    assert bill_resp.json()["data"]["amount_paid"] == "0.00"

    pay_resp = await api_client.post(
        f"/api/v1/pharmacy/bills/{bill_id}/pay",
        json={"amount": "45.00", "payment_method": "cash"},
        headers=_auth_header(access_token),
    )
    assert pay_resp.status_code == 200, pay_resp.text
    assert pay_resp.json()["data"]["status"] == "paid"


async def test_create_bill_initial_payment_exceeding_balance_creates_no_bill(
    api_client, real_session, grant_permission
):
    """Atomicity across a real HTTP request boundary: an
    initial_payment_amount that exceeds the bill's total is rejected,
    and — verified via a separate, later request's own fresh DB
    session — no bill is left behind at all."""
    actor, access_token = await _create_and_login(api_client, real_session, "initial-payment-atomic")
    await grant_permission(actor, PERMISSION_PHARMACY_MANAGE)
    await grant_permission(actor, PERMISSION_PHARMACY_BILL)
    await grant_permission(actor, PERMISSION_PHARMACY_READ)
    medicine_id = await _create_medicine(
        api_client, access_token, f"{TEST_MEDICINE_NAME_PREFIX}InitialAtomic", price="30.00"
    )
    today = datetime.now(UTC).date().isoformat()

    baseline_resp = await api_client.get(
        "/api/v1/pharmacy/bills", params={"date": today}, headers=_auth_header(access_token)
    )
    baseline_count = len(baseline_resp.json()["data"])

    failed_resp = await api_client.post(
        "/api/v1/pharmacy/bills",
        json={
            "visit_id": None,
            "items": [{"medicine_id": medicine_id, "quantity": 1}],
            "initial_payment_amount": "30.01",
            "initial_payment_method": "cash",
        },
        headers=_auth_header(access_token),
    )
    assert failed_resp.status_code == 422
    assert failed_resp.json()["error"]["code"] == "MEDICINE_BILL_PAYMENT_EXCEEDS_BALANCE"

    after_resp = await api_client.get(
        "/api/v1/pharmacy/bills", params={"date": today}, headers=_auth_header(access_token)
    )
    assert len(after_resp.json()["data"]) == baseline_count


async def test_multiple_partial_bill_payments_sum_correctly_and_settle_status(
    api_client, real_session, grant_permission
):
    """single partial payment -> multiple partials summing correctly ->
    derived status correctness, all in one lifecycle, same shape as
    test_billing_service.py's partial-payment coverage but exercised
    over HTTP (Pharmacy has no dedicated service-level test file — see
    this module's docstring)."""
    actor, access_token = await _create_and_login(api_client, real_session, "multi-partial-bill")
    await grant_permission(actor, PERMISSION_PHARMACY_MANAGE)
    await grant_permission(actor, PERMISSION_PHARMACY_BILL)
    await grant_permission(actor, PERMISSION_PHARMACY_READ)
    medicine_id = await _create_medicine(
        api_client, access_token, f"{TEST_MEDICINE_NAME_PREFIX}MultiPartial", price="100.00"
    )
    bill_resp = await api_client.post(
        "/api/v1/pharmacy/bills",
        json={"visit_id": None, "items": [{"medicine_id": medicine_id, "quantity": 2}]},
        headers=_auth_header(access_token),
    )
    bill_id = bill_resp.json()["data"]["id"]
    assert bill_resp.json()["data"]["total_amount"] == "200.00"

    first_pay = await api_client.post(
        f"/api/v1/pharmacy/bills/{bill_id}/pay",
        json={"amount": "80.00", "payment_method": "cash"},
        headers=_auth_header(access_token),
    )
    assert first_pay.status_code == 200, first_pay.text
    first_body = first_pay.json()["data"]
    assert first_body["status"] == "partially_paid"
    assert first_body["amount_paid"] == "80.00"
    assert len(first_body["payments"]) == 1
    assert first_body["payments"][0]["amount"] == "80.00"

    second_pay = await api_client.post(
        f"/api/v1/pharmacy/bills/{bill_id}/pay",
        json={"amount": "50.00", "payment_method": "jazzcash"},
        headers=_auth_header(access_token),
    )
    assert second_pay.status_code == 200, second_pay.text
    second_body = second_pay.json()["data"]
    assert second_body["status"] == "partially_paid"
    assert second_body["amount_paid"] == "130.00"
    assert len(second_body["payments"]) == 2

    third_pay = await api_client.post(
        f"/api/v1/pharmacy/bills/{bill_id}/pay",
        json={"amount": "70.00", "payment_method": "card"},
        headers=_auth_header(access_token),
    )
    assert third_pay.status_code == 200, third_pay.text
    third_body = third_pay.json()["data"]
    assert third_body["status"] == "paid"
    assert third_body["amount_paid"] == "200.00"
    assert len(third_body["payments"]) == 3
    # amount_paid can never drift from SUM(payments) — both are written
    # in the same DB transaction (see MedicineBillPayment's docstring).
    assert sum(Decimal(p["amount"]) for p in third_body["payments"]) == Decimal("200.00")

    get_resp = await api_client.get(
        f"/api/v1/pharmacy/bills/{bill_id}", headers=_auth_header(access_token)
    )
    assert get_resp.json()["data"]["status"] == "paid"

    print_resp = await api_client.get(
        f"/api/v1/pharmacy/bills/{bill_id}/print", headers=_auth_header(access_token)
    )
    assert print_resp.status_code == 200
    assert "Total Amount" in print_resp.text
    assert "Received" in print_resp.text
    assert "Pending" in print_resp.text
    # Three payments, three distinct methods (2026-08-19 addition) — the
    # slip's "Paid via" line must name all of them, in payment order.
    assert "Paid via: Cash, JazzCash, Card" in print_resp.text


async def test_bill_payment_exceeding_balance_rejected(api_client, real_session, grant_permission):
    actor, access_token = await _create_and_login(api_client, real_session, "overpay-bill")
    await grant_permission(actor, PERMISSION_PHARMACY_MANAGE)
    await grant_permission(actor, PERMISSION_PHARMACY_BILL)
    await grant_permission(actor, PERMISSION_PHARMACY_READ)
    medicine_id = await _create_medicine(
        api_client, access_token, f"{TEST_MEDICINE_NAME_PREFIX}Overpay", price="50.00"
    )
    bill_resp = await api_client.post(
        "/api/v1/pharmacy/bills",
        json={"visit_id": None, "items": [{"medicine_id": medicine_id, "quantity": 1}]},
        headers=_auth_header(access_token),
    )
    bill_id = bill_resp.json()["data"]["id"]

    resp = await api_client.post(
        f"/api/v1/pharmacy/bills/{bill_id}/pay",
        json={"amount": "50.01", "payment_method": "cash"},
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "MEDICINE_BILL_PAYMENT_EXCEEDS_BALANCE"

    # Rejected attempt must not have mutated the bill at all.
    get_resp = await api_client.get(
        f"/api/v1/pharmacy/bills/{bill_id}", headers=_auth_header(access_token)
    )
    assert get_resp.json()["data"]["status"] == "unpaid"
    assert get_resp.json()["data"]["amount_paid"] == "0.00"


async def test_bill_payment_on_already_paid_bill_rejected(
    api_client, real_session, grant_permission
):
    actor, access_token = await _create_and_login(api_client, real_session, "pay-twice-bill")
    await grant_permission(actor, PERMISSION_PHARMACY_MANAGE)
    await grant_permission(actor, PERMISSION_PHARMACY_BILL)
    medicine_id = await _create_medicine(
        api_client, access_token, f"{TEST_MEDICINE_NAME_PREFIX}PayTwice", price="25.00"
    )
    bill_resp = await api_client.post(
        "/api/v1/pharmacy/bills",
        json={"visit_id": None, "items": [{"medicine_id": medicine_id, "quantity": 1}]},
        headers=_auth_header(access_token),
    )
    bill_id = bill_resp.json()["data"]["id"]
    first_pay = await api_client.post(
        f"/api/v1/pharmacy/bills/{bill_id}/pay",
        json={"amount": "25.00", "payment_method": "cash"},
        headers=_auth_header(access_token),
    )
    assert first_pay.json()["data"]["status"] == "paid"

    resp = await api_client.post(
        f"/api/v1/pharmacy/bills/{bill_id}/pay",
        json={"amount": "1.00", "payment_method": "cash"},
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "MEDICINE_BILL_NOT_PAYABLE"


async def test_bill_payment_zero_or_negative_rejected(api_client, real_session, grant_permission):
    actor, access_token = await _create_and_login(api_client, real_session, "zero-payment-bill")
    await grant_permission(actor, PERMISSION_PHARMACY_MANAGE)
    await grant_permission(actor, PERMISSION_PHARMACY_BILL)
    medicine_id = await _create_medicine(
        api_client, access_token, f"{TEST_MEDICINE_NAME_PREFIX}ZeroPay", price="10.00"
    )
    bill_resp = await api_client.post(
        "/api/v1/pharmacy/bills",
        json={"visit_id": None, "items": [{"medicine_id": medicine_id, "quantity": 1}]},
        headers=_auth_header(access_token),
    )
    bill_id = bill_resp.json()["data"]["id"]

    resp = await api_client.post(
        f"/api/v1/pharmacy/bills/{bill_id}/pay",
        json={"amount": "0", "payment_method": "cash"},
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 422


async def test_bill_payment_requires_permission(api_client, real_session, grant_permission):
    actor, access_token = await _create_and_login(api_client, real_session, "pay-no-perm-bill")
    await grant_permission(actor, PERMISSION_PHARMACY_MANAGE)
    await grant_permission(actor, PERMISSION_PHARMACY_BILL)
    medicine_id = await _create_medicine(
        api_client, access_token, f"{TEST_MEDICINE_NAME_PREFIX}PayNoPerm"
    )
    bill_resp = await api_client.post(
        "/api/v1/pharmacy/bills",
        json={"visit_id": None, "items": [{"medicine_id": medicine_id, "quantity": 1}]},
        headers=_auth_header(access_token),
    )
    bill_id = bill_resp.json()["data"]["id"]

    _other_actor, other_token = await _create_and_login(api_client, real_session, "pay-no-perm-2")

    resp = await api_client.post(
        f"/api/v1/pharmacy/bills/{bill_id}/pay",
        json={"amount": "10.00", "payment_method": "cash"},
        headers=_auth_header(other_token),
    )

    assert resp.status_code == 403


async def test_create_bill_with_discount_computes_correct_total(
    api_client, real_session, grant_permission
):
    actor, access_token = await _create_and_login(api_client, real_session, "discount-basic")
    await grant_permission(actor, PERMISSION_PHARMACY_MANAGE)
    await grant_permission(actor, PERMISSION_PHARMACY_BILL)
    medicine_id = await _create_medicine(
        api_client, access_token, f"{TEST_MEDICINE_NAME_PREFIX}DiscountBasic", price="100.00"
    )

    bill_resp = await api_client.post(
        "/api/v1/pharmacy/bills",
        json={
            "visit_id": None,
            "items": [{"medicine_id": medicine_id, "quantity": 3}],
            "discount_amount": "50.00",
            "discount_reason": "Bulk purchase",
        },
        headers=_auth_header(access_token),
    )

    assert bill_resp.status_code == 201, bill_resp.text
    body = bill_resp.json()["data"]
    # 3 x 100.00 = 300.00 subtotal, minus 50.00 discount = 250.00
    assert body["total_amount"] == "250.00"
    assert body["discount_amount"] == "50.00"
    assert body["discount_reason"] == "Bulk purchase"


async def test_create_bill_discount_reason_is_optional(api_client, real_session, grant_permission):
    """Deliberate difference from Invoice's discount, which requires a
    reason — a medicine-bill discount reason may be left blank."""
    actor, access_token = await _create_and_login(api_client, real_session, "discount-no-reason")
    await grant_permission(actor, PERMISSION_PHARMACY_MANAGE)
    await grant_permission(actor, PERMISSION_PHARMACY_BILL)
    medicine_id = await _create_medicine(
        api_client, access_token, f"{TEST_MEDICINE_NAME_PREFIX}DiscountNoReason", price="40.00"
    )

    bill_resp = await api_client.post(
        "/api/v1/pharmacy/bills",
        json={
            "visit_id": None,
            "items": [{"medicine_id": medicine_id, "quantity": 1}],
            "discount_amount": "10.00",
        },
        headers=_auth_header(access_token),
    )

    assert bill_resp.status_code == 201, bill_resp.text
    body = bill_resp.json()["data"]
    assert body["total_amount"] == "30.00"
    assert body["discount_amount"] == "10.00"
    assert body["discount_reason"] is None


async def test_create_bill_discount_exceeding_subtotal_rejected(
    api_client, real_session, grant_permission
):
    actor, access_token = await _create_and_login(api_client, real_session, "discount-exceeds")
    await grant_permission(actor, PERMISSION_PHARMACY_MANAGE)
    await grant_permission(actor, PERMISSION_PHARMACY_BILL)
    medicine_id = await _create_medicine(
        api_client, access_token, f"{TEST_MEDICINE_NAME_PREFIX}DiscountExceeds", price="20.00"
    )

    bill_resp = await api_client.post(
        "/api/v1/pharmacy/bills",
        json={
            "visit_id": None,
            "items": [{"medicine_id": medicine_id, "quantity": 1}],
            "discount_amount": "20.01",
        },
        headers=_auth_header(access_token),
    )

    assert bill_resp.status_code == 422
    assert bill_resp.json()["error"]["code"] == "MEDICINE_BILL_DISCOUNT_EXCEEDS_SUBTOTAL"


async def test_create_bill_negative_discount_rejected(api_client, real_session, grant_permission):
    actor, access_token = await _create_and_login(api_client, real_session, "discount-negative")
    await grant_permission(actor, PERMISSION_PHARMACY_MANAGE)
    await grant_permission(actor, PERMISSION_PHARMACY_BILL)
    medicine_id = await _create_medicine(
        api_client, access_token, f"{TEST_MEDICINE_NAME_PREFIX}DiscountNegative", price="20.00"
    )

    bill_resp = await api_client.post(
        "/api/v1/pharmacy/bills",
        json={
            "visit_id": None,
            "items": [{"medicine_id": medicine_id, "quantity": 1}],
            "discount_amount": "-5.00",
        },
        headers=_auth_header(access_token),
    )

    assert bill_resp.status_code == 422


async def test_print_bill_with_discount_shows_lines_in_correct_order(
    api_client, real_session, grant_permission
):
    """The printed slip must show, in order: the original (pre-discount)
    total, then the Discount line, then the final Net Amount — never
    the reverse, and never with the discount silently absorbed into a
    single opaque total."""
    actor, access_token = await _create_and_login(api_client, real_session, "discount-print-order")
    await grant_permission(actor, PERMISSION_PHARMACY_MANAGE)
    await grant_permission(actor, PERMISSION_PHARMACY_BILL)
    await grant_permission(actor, PERMISSION_PHARMACY_READ)
    medicine_id = await _create_medicine(
        api_client, access_token, f"{TEST_MEDICINE_NAME_PREFIX}DiscountPrintOrder", price="100.00"
    )

    bill_resp = await api_client.post(
        "/api/v1/pharmacy/bills",
        json={
            "visit_id": None,
            "items": [{"medicine_id": medicine_id, "quantity": 2}],
            "discount_amount": "30.00",
            "discount_reason": "Loyalty",
        },
        headers=_auth_header(access_token),
    )
    assert bill_resp.status_code == 201, bill_resp.text
    bill_id = bill_resp.json()["data"]["id"]

    print_resp = await api_client.get(
        f"/api/v1/pharmacy/bills/{bill_id}/print", headers=_auth_header(access_token)
    )
    assert print_resp.status_code == 200
    html = print_resp.text
    # 2 x 100.00 = 200.00 subtotal, -30.00 discount = 170.00 net.
    assert "200.00" in html
    assert "Discount (Loyalty)" in html
    assert "170.00" in html

    total_idx = html.index("Total Amount")
    discount_idx = html.index("Discount (Loyalty)")
    net_idx = html.index("Net Amount")
    assert total_idx < discount_idx < net_idx


async def test_print_bill_without_discount_omits_discount_line(
    api_client, real_session, grant_permission
):
    actor, access_token = await _create_and_login(api_client, real_session, "no-discount-print")
    await grant_permission(actor, PERMISSION_PHARMACY_MANAGE)
    await grant_permission(actor, PERMISSION_PHARMACY_BILL)
    await grant_permission(actor, PERMISSION_PHARMACY_READ)
    medicine_id = await _create_medicine(
        api_client, access_token, f"{TEST_MEDICINE_NAME_PREFIX}PlainPrint", price="15.00"
    )

    bill_resp = await api_client.post(
        "/api/v1/pharmacy/bills",
        json={"visit_id": None, "items": [{"medicine_id": medicine_id, "quantity": 1}]},
        headers=_auth_header(access_token),
    )
    assert bill_resp.status_code == 201, bill_resp.text
    bill_id = bill_resp.json()["data"]["id"]

    print_resp = await api_client.get(
        f"/api/v1/pharmacy/bills/{bill_id}/print", headers=_auth_header(access_token)
    )
    assert print_resp.status_code == 200
    assert "Discount" not in print_resp.text
    assert "Net Amount" in print_resp.text


# ---------------------------------------------------------------------
# "My Medicine Bills" (2026-08-19 addition) — GET /pharmacy/bills/mine,
# the medicine-bill sibling of Reception's own "My Registrations".
# ---------------------------------------------------------------------


async def test_list_my_bills_requires_permission(api_client, real_session):
    _actor, access_token = await _create_and_login(api_client, real_session, "my-bills-no-perm")

    resp = await api_client.get(
        "/api/v1/pharmacy/bills/mine", headers=_auth_header(access_token)
    )

    assert resp.status_code == 403


async def test_list_my_bills_returns_only_own_bills(api_client, real_session, grant_permission):
    """The core requirement: receptionist A's "My Medicine Bills" must
    never include receptionist B's bills, even though both are billed
    in the same database at the same time."""
    actor_a, token_a = await _create_and_login(api_client, real_session, "my-bills-a")
    await grant_permission(actor_a, PERMISSION_PHARMACY_MANAGE)
    await grant_permission(actor_a, PERMISSION_PHARMACY_BILL)
    await grant_permission(actor_a, PERMISSION_PHARMACY_READ)
    actor_b, token_b = await _create_and_login(api_client, real_session, "my-bills-b")
    await grant_permission(actor_b, PERMISSION_PHARMACY_BILL)
    await grant_permission(actor_b, PERMISSION_PHARMACY_READ)

    medicine_id = await _create_medicine(
        api_client, token_a, f"{TEST_MEDICINE_NAME_PREFIX}MyBillsShared", price="10.00"
    )

    bill_a_resp = await api_client.post(
        "/api/v1/pharmacy/bills",
        json={"visit_id": None, "items": [{"medicine_id": medicine_id, "quantity": 1}]},
        headers=_auth_header(token_a),
    )
    assert bill_a_resp.status_code == 201, bill_a_resp.text
    bill_a_id = bill_a_resp.json()["data"]["id"]

    bill_b_resp = await api_client.post(
        "/api/v1/pharmacy/bills",
        json={"visit_id": None, "items": [{"medicine_id": medicine_id, "quantity": 5}]},
        headers=_auth_header(token_b),
    )
    assert bill_b_resp.status_code == 201, bill_b_resp.text
    bill_b_id = bill_b_resp.json()["data"]["id"]

    resp_a = await api_client.get("/api/v1/pharmacy/bills/mine", headers=_auth_header(token_a))
    assert resp_a.status_code == 200
    ids_a = [row["id"] for row in resp_a.json()["data"]]
    assert bill_a_id in ids_a
    assert bill_b_id not in ids_a

    resp_b = await api_client.get("/api/v1/pharmacy/bills/mine", headers=_auth_header(token_b))
    assert resp_b.status_code == 200
    ids_b = [row["id"] for row in resp_b.json()["data"]]
    assert bill_b_id in ids_b
    assert bill_a_id not in ids_b


async def test_list_my_bills_includes_item_count_and_discount(
    api_client, real_session, grant_permission
):
    actor, access_token = await _create_and_login(api_client, real_session, "my-bills-fields")
    await grant_permission(actor, PERMISSION_PHARMACY_MANAGE)
    await grant_permission(actor, PERMISSION_PHARMACY_BILL)
    await grant_permission(actor, PERMISSION_PHARMACY_READ)
    medicine_id = await _create_medicine(
        api_client, access_token, f"{TEST_MEDICINE_NAME_PREFIX}MyBillsFields", price="50.00"
    )

    bill_resp = await api_client.post(
        "/api/v1/pharmacy/bills",
        json={
            "visit_id": None,
            "items": [{"medicine_id": medicine_id, "quantity": 2}],
            "discount_amount": "20.00",
        },
        headers=_auth_header(access_token),
    )
    assert bill_resp.status_code == 201, bill_resp.text
    bill_id = bill_resp.json()["data"]["id"]

    resp = await api_client.get("/api/v1/pharmacy/bills/mine", headers=_auth_header(access_token))
    assert resp.status_code == 200
    matching = [row for row in resp.json()["data"] if row["id"] == bill_id]
    assert len(matching) == 1
    assert matching[0]["item_count"] == 1
    assert matching[0]["total_amount"] == "80.00"
    assert matching[0]["discount_amount"] == "20.00"
    assert resp.json()["meta"]["total"] >= 1


async def test_print_bill_requires_permission(api_client, real_session, grant_permission):
    actor, access_token = await _create_and_login(api_client, real_session, "print-no-perm")
    await grant_permission(actor, PERMISSION_PHARMACY_MANAGE)
    await grant_permission(actor, PERMISSION_PHARMACY_BILL)
    medicine_id = await _create_medicine(
        api_client, access_token, f"{TEST_MEDICINE_NAME_PREFIX}PrintNoPerm"
    )
    bill_resp = await api_client.post(
        "/api/v1/pharmacy/bills",
        json={"visit_id": None, "items": [{"medicine_id": medicine_id, "quantity": 1}]},
        headers=_auth_header(access_token),
    )
    bill_id = bill_resp.json()["data"]["id"]

    other_actor, other_token = await _create_and_login(api_client, real_session, "print-no-perm-2")

    resp = await api_client.get(
        f"/api/v1/pharmacy/bills/{bill_id}/print", headers=_auth_header(other_token)
    )

    assert resp.status_code == 403


# ---------------------------------------------------------------------
# Admin Edit/Delete for Medicine Bills (2026-08-20 addition) — the
# medicine-bill sibling of tests/test_reception_endpoints.py's
# update_visit/delete_visit test block; see that file for the identical
# permission-gating shape this mirrors.
# ---------------------------------------------------------------------


async def test_update_bill_requires_permission(api_client, real_session, grant_permission):
    actor, access_token = await _create_and_login(api_client, real_session, "update-bill-no-perm")
    await grant_permission(actor, PERMISSION_PHARMACY_MANAGE)
    await grant_permission(actor, PERMISSION_PHARMACY_BILL)
    medicine_id = await _create_medicine(
        api_client, access_token, f"{TEST_MEDICINE_NAME_PREFIX}UpdateNoPerm"
    )
    bill_resp = await api_client.post(
        "/api/v1/pharmacy/bills",
        json={
            "visit_id": None,
            "items": [{"medicine_id": medicine_id, "quantity": 1}],
            "manual_patient_name": "Walk In",
            "manual_patient_age": 30,
            "manual_patient_phone": "03001234567",
        },
        headers=_auth_header(access_token),
    )
    bill_id = bill_resp.json()["data"]["id"]

    # Holding pharmacy:bill (what every receptionist already has) must
    # not implicitly grant pharmacy:update_bill — the two are unrelated,
    # separately-granted permissions, same requirement
    # test_update_visit_cancel_permission_alone_is_not_sufficient guards
    # for Visit.
    resp = await api_client.patch(
        f"/api/v1/pharmacy/bills/{bill_id}",
        json={"discount_amount": "0"},
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "PERMISSION_DENIED"


async def test_update_bill_admin_can_correct_a_walkin_bills_manual_patient_details(
    api_client, real_session, grant_permission
):
    """Ownership never matters for this permission — an admin corrects
    any receptionist's bill, not only their own."""
    receptionist, receptionist_token = await _create_and_login(
        api_client, real_session, "update-bill-owner"
    )
    await grant_permission(receptionist, PERMISSION_PHARMACY_MANAGE)
    await grant_permission(receptionist, PERMISSION_PHARMACY_BILL)
    medicine_id = await _create_medicine(
        api_client, receptionist_token, f"{TEST_MEDICINE_NAME_PREFIX}UpdateOwnership"
    )
    bill_resp = await api_client.post(
        "/api/v1/pharmacy/bills",
        json={
            "visit_id": None,
            "items": [{"medicine_id": medicine_id, "quantity": 1}],
            "manual_patient_name": "Original Name",
            "manual_patient_age": 25,
            "manual_patient_phone": "03001111111",
        },
        headers=_auth_header(receptionist_token),
    )
    bill_id = bill_resp.json()["data"]["id"]

    admin, admin_token = await _create_and_login(api_client, real_session, "update-bill-admin")
    await grant_permission(admin, PERMISSION_PHARMACY_UPDATE_BILL)

    resp = await api_client.patch(
        f"/api/v1/pharmacy/bills/{bill_id}",
        json={
            "manual_patient_name": "Corrected By Admin",
            "manual_patient_age": 26,
            "manual_patient_phone": "03002222222",
        },
        headers=_auth_header(admin_token),
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()["data"]
    assert body["manual_patient_name"] == "Corrected By Admin"
    assert body["manual_patient_age"] == 26
    assert body["manual_patient_phone"] == "03002222222"


async def test_update_bill_rejects_manual_patient_fields_on_visit_linked_bill(
    api_client, real_session, grant_permission
):
    """A visit-linked bill's patient identity belongs to that Visit's
    own Patient record — corrected through Reception's existing "Edit
    Slip" action, never duplicated here."""
    actor, access_token = await _create_and_login(api_client, real_session, "update-bill-linked")
    await grant_permission(actor, PERMISSION_PHARMACY_MANAGE)
    await grant_permission(actor, PERMISSION_PHARMACY_BILL)
    await grant_permission(actor, PERMISSION_RECEPTION_REGISTER_VISIT)
    await grant_permission(actor, PERMISSION_PHARMACY_UPDATE_BILL)
    medicine_id = await _create_medicine(
        api_client, access_token, f"{TEST_MEDICINE_NAME_PREFIX}UpdateLinked"
    )
    visit_id = await _register_visit(api_client, access_token, "UpdateLinked")
    bill_resp = await api_client.post(
        "/api/v1/pharmacy/bills",
        json={"visit_id": visit_id, "items": [{"medicine_id": medicine_id, "quantity": 1}]},
        headers=_auth_header(access_token),
    )
    bill_id = bill_resp.json()["data"]["id"]

    resp = await api_client.patch(
        f"/api/v1/pharmacy/bills/{bill_id}",
        json={"manual_patient_name": "Should Be Rejected"},
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "MEDICINE_BILL_MANUAL_PATIENT_CONFLICTS_WITH_VISIT"


async def test_update_bill_recomputes_total_amount_from_new_discount(
    api_client, real_session, grant_permission
):
    actor, access_token = await _create_and_login(api_client, real_session, "update-bill-discount")
    await grant_permission(actor, PERMISSION_PHARMACY_MANAGE)
    await grant_permission(actor, PERMISSION_PHARMACY_BILL)
    await grant_permission(actor, PERMISSION_PHARMACY_UPDATE_BILL)
    medicine_id = await _create_medicine(
        api_client, access_token, f"{TEST_MEDICINE_NAME_PREFIX}UpdateDiscount", price="100.00"
    )
    bill_resp = await api_client.post(
        "/api/v1/pharmacy/bills",
        json={"visit_id": None, "items": [{"medicine_id": medicine_id, "quantity": 3}]},
        headers=_auth_header(access_token),
    )
    bill_id = bill_resp.json()["data"]["id"]
    assert bill_resp.json()["data"]["total_amount"] == "300.00"  # no discount yet

    resp = await api_client.patch(
        f"/api/v1/pharmacy/bills/{bill_id}",
        json={"discount_amount": "50.00", "discount_reason": "Corrected discount"},
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()["data"]
    assert body["discount_amount"] == "50.00"
    assert body["discount_reason"] == "Corrected discount"
    # 300.00 subtotal, minus the newly-applied 50.00 discount = 250.00
    assert body["total_amount"] == "250.00"


async def test_update_bill_discount_exceeding_subtotal_rejected(
    api_client, real_session, grant_permission
):
    actor, access_token = await _create_and_login(api_client, real_session, "update-bill-exceeds")
    await grant_permission(actor, PERMISSION_PHARMACY_MANAGE)
    await grant_permission(actor, PERMISSION_PHARMACY_BILL)
    await grant_permission(actor, PERMISSION_PHARMACY_UPDATE_BILL)
    medicine_id = await _create_medicine(
        api_client, access_token, f"{TEST_MEDICINE_NAME_PREFIX}UpdateExceeds", price="20.00"
    )
    bill_resp = await api_client.post(
        "/api/v1/pharmacy/bills",
        json={"visit_id": None, "items": [{"medicine_id": medicine_id, "quantity": 1}]},
        headers=_auth_header(access_token),
    )
    bill_id = bill_resp.json()["data"]["id"]

    resp = await api_client.patch(
        f"/api/v1/pharmacy/bills/{bill_id}",
        json={"discount_amount": "20.01"},
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "MEDICINE_BILL_DISCOUNT_EXCEEDS_SUBTOTAL"


async def test_update_bill_blocked_once_bill_has_any_payment(
    api_client, real_session, grant_permission
):
    """The financial-integrity block: editing the discount on a bill
    that already has money collected against it would desynchronize
    `amount_paid`/`total_amount` on that same row — unlike Visit, a
    MedicineBill has no separate, decoupled Invoice entity, so this
    applies to *edit* here, not only delete."""
    actor, access_token = await _create_and_login(api_client, real_session, "update-bill-paid")
    await grant_permission(actor, PERMISSION_PHARMACY_MANAGE)
    await grant_permission(actor, PERMISSION_PHARMACY_BILL)
    await grant_permission(actor, PERMISSION_PHARMACY_UPDATE_BILL)
    medicine_id = await _create_medicine(
        api_client, access_token, f"{TEST_MEDICINE_NAME_PREFIX}UpdateBlockedPaid", price="40.00"
    )
    bill_resp = await api_client.post(
        "/api/v1/pharmacy/bills",
        json={
            "visit_id": None,
            "items": [{"medicine_id": medicine_id, "quantity": 1}],
            "initial_payment_amount": "20.00",  # partial — status becomes partially_paid
            "initial_payment_method": "cash",
        },
        headers=_auth_header(access_token),
    )
    bill_id = bill_resp.json()["data"]["id"]
    assert bill_resp.json()["data"]["status"] == "partially_paid"

    resp = await api_client.patch(
        f"/api/v1/pharmacy/bills/{bill_id}",
        json={"discount_amount": "5.00"},
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "MEDICINE_BILL_HAS_SETTLED_PAYMENT"


async def test_delete_bill_requires_permission(api_client, real_session, grant_permission):
    actor, access_token = await _create_and_login(api_client, real_session, "delete-bill-no-perm")
    await grant_permission(actor, PERMISSION_PHARMACY_MANAGE)
    await grant_permission(actor, PERMISSION_PHARMACY_BILL)
    medicine_id = await _create_medicine(
        api_client, access_token, f"{TEST_MEDICINE_NAME_PREFIX}DeleteNoPerm"
    )
    bill_resp = await api_client.post(
        "/api/v1/pharmacy/bills",
        json={"visit_id": None, "items": [{"medicine_id": medicine_id, "quantity": 1}]},
        headers=_auth_header(access_token),
    )
    bill_id = bill_resp.json()["data"]["id"]

    resp = await api_client.delete(
        f"/api/v1/pharmacy/bills/{bill_id}", headers=_auth_header(access_token)
    )

    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "PERMISSION_DENIED"


async def test_delete_bill_success_removes_it_from_get(api_client, real_session, grant_permission):
    receptionist, receptionist_token = await _create_and_login(
        api_client, real_session, "delete-bill-owner"
    )
    await grant_permission(receptionist, PERMISSION_PHARMACY_MANAGE)
    await grant_permission(receptionist, PERMISSION_PHARMACY_BILL)
    medicine_id = await _create_medicine(
        api_client, receptionist_token, f"{TEST_MEDICINE_NAME_PREFIX}DeleteSuccess"
    )
    bill_resp = await api_client.post(
        "/api/v1/pharmacy/bills",
        json={"visit_id": None, "items": [{"medicine_id": medicine_id, "quantity": 1}]},
        headers=_auth_header(receptionist_token),
    )
    bill_id = bill_resp.json()["data"]["id"]

    admin, admin_token = await _create_and_login(api_client, real_session, "delete-bill-admin")
    await grant_permission(admin, PERMISSION_PHARMACY_DELETE_BILL)
    await grant_permission(admin, PERMISSION_PHARMACY_READ)

    delete_resp = await api_client.delete(
        f"/api/v1/pharmacy/bills/{bill_id}", headers=_auth_header(admin_token)
    )
    assert delete_resp.status_code == 200

    get_resp = await api_client.get(
        f"/api/v1/pharmacy/bills/{bill_id}", headers=_auth_header(admin_token)
    )
    assert get_resp.status_code == 404


async def test_delete_bill_blocked_once_bill_has_any_payment(
    api_client, real_session, grant_permission
):
    actor, access_token = await _create_and_login(api_client, real_session, "delete-bill-paid")
    await grant_permission(actor, PERMISSION_PHARMACY_MANAGE)
    await grant_permission(actor, PERMISSION_PHARMACY_BILL)
    await grant_permission(actor, PERMISSION_PHARMACY_DELETE_BILL)
    medicine_id = await _create_medicine(
        api_client, access_token, f"{TEST_MEDICINE_NAME_PREFIX}DeleteBlockedPaid", price="60.00"
    )
    bill_resp = await api_client.post(
        "/api/v1/pharmacy/bills",
        json={
            "visit_id": None,
            "items": [{"medicine_id": medicine_id, "quantity": 1}],
            "initial_payment_amount": "60.00",  # paid in full
            "initial_payment_method": "cash",
        },
        headers=_auth_header(access_token),
    )
    bill_id = bill_resp.json()["data"]["id"]
    assert bill_resp.json()["data"]["status"] == "paid"

    resp = await api_client.delete(
        f"/api/v1/pharmacy/bills/{bill_id}", headers=_auth_header(access_token)
    )

    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "MEDICINE_BILL_HAS_SETTLED_PAYMENT"

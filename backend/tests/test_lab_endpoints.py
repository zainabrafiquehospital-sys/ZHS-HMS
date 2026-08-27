"""Full end-to-end HTTP tests for the Laboratory Billing module — see
tests/test_pharmacy_endpoints.py's identical module docstring. Lab
mirrors Pharmacy's own test shape closely, adjusted for its two
confirmed design differences: no per-line quantity, and a direct
Patient link (never Visit-mediated) — see app/modules/lab/models.py's
own module docstring for the full rationale."""

from datetime import date

from app.modules.auth.models import User, UserStatus
from app.modules.auth.password_service import PasswordService
from app.modules.auth.repository import UserRepository
from app.modules.lab.constants import (
    PERMISSION_LAB_BILL,
    PERMISSION_LAB_DELETE_BILL,
    PERMISSION_LAB_MANAGE,
    PERMISSION_LAB_READ,
    PERMISSION_LAB_UPDATE_BILL,
)
from app.modules.patients.constants import PERMISSION_PATIENTS_CREATE
from tests.conftest import TEST_LAB_TEST_NAME_PREFIX, TEST_PATIENT_NAME_PREFIX, make_test_email

_PASSWORD = "Str0ng!Passw0rd#2026"
_TODAY = date.today().isoformat()


async def _create_and_login(api_client, real_session, suffix: str) -> tuple[User, str]:
    password_hash = await PasswordService().hash(_PASSWORD)
    email = make_test_email(suffix)
    user = await UserRepository(real_session).add(
        User(
            email=email,
            password_hash=password_hash,
            full_name="Lab Endpoint Actor",
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


async def _create_test(
    api_client, access_token, name: str, *, category: str = "pathology", price: str = "500.00"
) -> str:
    resp = await api_client.post(
        "/api/v1/lab/tests",
        json={"name": name, "category": category, "price": price},
        headers=_auth_header(access_token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]["id"]


async def _create_patient(api_client, access_token, full_name: str) -> str:
    resp = await api_client.post(
        "/api/v1/patients",
        json={
            "full_name": full_name,
            "guardian_name": None,
            "gender": "female",
            "age_years": 30,
            "phone_number": "03001234567",
            "cnic": None,
            "address": None,
        },
        headers=_auth_header(access_token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]["id"]


# ----------------------------------------------------------------------
# Permission gating
# ----------------------------------------------------------------------


async def test_search_tests_requires_permission(api_client, real_session):
    _actor, access_token = await _create_and_login(api_client, real_session, "no-perm-search")

    resp = await api_client.get(
        "/api/v1/lab/tests/search", params={"search": "cbc"}, headers=_auth_header(access_token)
    )

    assert resp.status_code == 403


async def test_create_test_requires_manage_permission(api_client, real_session, grant_permission):
    """Structural proof of the segregation of duties: a role holding
    only `lab:bill`/`lab:read` cannot create or edit the price list —
    that requires the separate `lab:manage` code."""
    actor, access_token = await _create_and_login(api_client, real_session, "no-manage")
    await grant_permission(actor, PERMISSION_LAB_BILL)
    await grant_permission(actor, PERMISSION_LAB_READ)

    resp = await api_client.post(
        "/api/v1/lab/tests",
        json={
            "name": f"{TEST_LAB_TEST_NAME_PREFIX}NoManage",
            "category": "pathology",
            "price": "500.00",
        },
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 403


async def test_create_bill_requires_permission(api_client, real_session, grant_permission):
    actor, access_token = await _create_and_login(api_client, real_session, "no-perm-bill")
    await grant_permission(actor, PERMISSION_LAB_MANAGE)
    test_id = await _create_test(api_client, access_token, f"{TEST_LAB_TEST_NAME_PREFIX}NoBillPerm")

    resp = await api_client.post(
        "/api/v1/lab/bills",
        json={"patient_id": None, "items": [test_id]},
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 403


async def test_get_bill_stats_by_creator_requires_permission(api_client, real_session):
    _actor, access_token = await _create_and_login(api_client, real_session, "stats-no-perm")

    resp = await api_client.get(
        "/api/v1/lab/bills/stats/by-creator", headers=_auth_header(access_token)
    )

    assert resp.status_code == 403


async def test_update_bill_requires_correction_permission(
    api_client, real_session, grant_permission
):
    """`lab:bill` alone (the permission that creates a bill) must not be
    enough to correct one — that requires the separate `lab:update_bill`
    code, never granted to Receptionist."""
    actor, access_token = await _create_and_login(api_client, real_session, "no-update-perm")
    await grant_permission(actor, PERMISSION_LAB_MANAGE)
    await grant_permission(actor, PERMISSION_LAB_BILL)
    test_id = await _create_test(
        api_client, access_token, f"{TEST_LAB_TEST_NAME_PREFIX}NoUpdatePerm"
    )
    bill_resp = await api_client.post(
        "/api/v1/lab/bills",
        json={
            "patient_id": None,
            "items": [test_id],
            "manual_patient_name": "Walk-in",
            "manual_patient_age": 40,
            "manual_patient_phone": "03001112222",
        },
        headers=_auth_header(access_token),
    )
    bill_id = bill_resp.json()["data"]["id"]

    resp = await api_client.patch(
        f"/api/v1/lab/bills/{bill_id}",
        json={"discount_amount": "10.00"},
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 403


async def test_delete_bill_requires_delete_permission(api_client, real_session, grant_permission):
    actor, access_token = await _create_and_login(api_client, real_session, "no-delete-perm")
    await grant_permission(actor, PERMISSION_LAB_MANAGE)
    await grant_permission(actor, PERMISSION_LAB_BILL)
    test_id = await _create_test(
        api_client, access_token, f"{TEST_LAB_TEST_NAME_PREFIX}NoDeletePerm"
    )
    bill_resp = await api_client.post(
        "/api/v1/lab/bills",
        json={
            "patient_id": None,
            "items": [test_id],
            "manual_patient_name": "Walk-in",
            "manual_patient_age": 40,
            "manual_patient_phone": "03001112222",
        },
        headers=_auth_header(access_token),
    )
    bill_id = bill_resp.json()["data"]["id"]

    resp = await api_client.delete(
        f"/api/v1/lab/bills/{bill_id}", headers=_auth_header(access_token)
    )

    assert resp.status_code == 403


# ----------------------------------------------------------------------
# Full lifecycle
# ----------------------------------------------------------------------


async def test_full_lab_lifecycle_via_http(api_client, real_session, grant_permission):
    actor, access_token = await _create_and_login(api_client, real_session, "lifecycle")
    await grant_permission(actor, PERMISSION_LAB_MANAGE)
    await grant_permission(actor, PERMISSION_LAB_BILL)
    await grant_permission(actor, PERMISSION_LAB_READ)
    await grant_permission(actor, PERMISSION_PATIENTS_CREATE)

    test_a = await _create_test(
        api_client,
        access_token,
        f"{TEST_LAB_TEST_NAME_PREFIX}CBC",
        category="pathology",
        price="600.00",
    )
    test_b = await _create_test(
        api_client,
        access_token,
        f"{TEST_LAB_TEST_NAME_PREFIX}Scan",
        category="radiology",
        price="1500.00",
    )
    patient_id = await _create_patient(api_client, access_token, f"{TEST_PATIENT_NAME_PREFIX}Lab")

    create_resp = await api_client.post(
        "/api/v1/lab/bills",
        json={
            "patient_id": patient_id,
            "items": [test_a, test_b],
            "initial_payment_amount": "1000.00",
            "initial_payment_method": "cash",
        },
        headers=_auth_header(access_token),
    )
    assert create_resp.status_code == 201, create_resp.text
    bill = create_resp.json()["data"]
    assert bill["patient_id"] == patient_id
    assert bill["total_amount"] == "2100.00"
    assert bill["amount_paid"] == "1000.00"
    assert bill["status"] == "partially_paid"
    assert len(bill["items"]) == 2
    assert bill["queue_token"] is not None and bill["queue_token"].startswith("Token #")
    item_names = {item["lab_test_name_snapshot"] for item in bill["items"]}
    assert item_names == {f"{TEST_LAB_TEST_NAME_PREFIX}CBC", f"{TEST_LAB_TEST_NAME_PREFIX}Scan"}

    bill_id = bill["id"]

    pay_resp = await api_client.post(
        f"/api/v1/lab/bills/{bill_id}/pay",
        json={"amount": "1100.00", "payment_method": "cash"},
        headers=_auth_header(access_token),
    )
    assert pay_resp.status_code == 200, pay_resp.text
    assert pay_resp.json()["data"]["status"] == "paid"
    assert pay_resp.json()["data"]["amount_paid"] == "2100.00"
    assert len(pay_resp.json()["data"]["payments"]) == 2

    get_resp = await api_client.get(
        f"/api/v1/lab/bills/{bill_id}", headers=_auth_header(access_token)
    )
    assert get_resp.status_code == 200
    assert get_resp.json()["data"]["status"] == "paid"


async def test_create_bill_duplicate_test_ids_create_two_independent_lines(
    api_client, real_session, grant_permission
):
    """Confirmed design: no quantity field — the same test appearing
    twice in `items` becomes two independent LabBillItem rows, never
    one row with an implied quantity of 2."""
    actor, access_token = await _create_and_login(api_client, real_session, "dup-lines")
    await grant_permission(actor, PERMISSION_LAB_MANAGE)
    await grant_permission(actor, PERMISSION_LAB_BILL)
    test_id = await _create_test(
        api_client, access_token, f"{TEST_LAB_TEST_NAME_PREFIX}DupLine", price="500.00"
    )

    resp = await api_client.post(
        "/api/v1/lab/bills",
        json={
            "patient_id": None,
            "items": [test_id, test_id],
            "manual_patient_name": "Repeat Test Patient",
            "manual_patient_age": 33,
            "manual_patient_phone": "03001112222",
        },
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 201, resp.text
    bill = resp.json()["data"]
    assert len(bill["items"]) == 2
    assert bill["total_amount"] == "1000.00"
    assert bill["items"][0]["id"] != bill["items"][1]["id"]


async def test_create_bill_rejects_inactive_test(api_client, real_session, grant_permission):
    actor, access_token = await _create_and_login(api_client, real_session, "inactive-test")
    await grant_permission(actor, PERMISSION_LAB_MANAGE)
    await grant_permission(actor, PERMISSION_LAB_BILL)
    test_id = await _create_test(api_client, access_token, f"{TEST_LAB_TEST_NAME_PREFIX}Inactive")
    await api_client.patch(
        f"/api/v1/lab/tests/{test_id}",
        json={"is_active": False},
        headers=_auth_header(access_token),
    )

    resp = await api_client.post(
        "/api/v1/lab/bills",
        json={
            "patient_id": None,
            "items": [test_id],
            "manual_patient_name": "Walk-in",
            "manual_patient_age": 40,
            "manual_patient_phone": "03001112222",
        },
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "LAB_TEST_INACTIVE"


async def test_create_bill_rejects_unknown_test(api_client, real_session, grant_permission):
    actor, access_token = await _create_and_login(api_client, real_session, "unknown-test")
    await grant_permission(actor, PERMISSION_LAB_BILL)

    resp = await api_client.post(
        "/api/v1/lab/bills",
        json={
            "patient_id": None,
            "items": ["01911111-1111-7111-8111-111111111111"],
            "manual_patient_name": "Walk-in",
            "manual_patient_age": 40,
            "manual_patient_phone": "03001112222",
        },
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "LAB_TEST_NOT_FOUND"


# ----------------------------------------------------------------------
# Patient linkage (direct Patient link, never Visit — confirmed design)
# ----------------------------------------------------------------------


async def test_create_bill_manual_patient_and_patient_id_together_rejected(
    api_client, real_session, grant_permission
):
    actor, access_token = await _create_and_login(api_client, real_session, "manual-conflict")
    await grant_permission(actor, PERMISSION_LAB_MANAGE)
    await grant_permission(actor, PERMISSION_LAB_BILL)
    await grant_permission(actor, PERMISSION_PATIENTS_CREATE)
    test_id = await _create_test(
        api_client, access_token, f"{TEST_LAB_TEST_NAME_PREFIX}ManualConflict"
    )
    patient_id = await _create_patient(
        api_client, access_token, f"{TEST_PATIENT_NAME_PREFIX}LabConflict"
    )

    resp = await api_client.post(
        "/api/v1/lab/bills",
        json={
            "patient_id": patient_id,
            "items": [test_id],
            "manual_patient_name": "Someone Else",
            "manual_patient_age": 22,
            "manual_patient_phone": "03001112223",
        },
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "LAB_BILL_MANUAL_PATIENT_CONFLICTS_WITH_PATIENT"


async def test_create_bill_partial_manual_patient_fields_rejected(
    api_client, real_session, grant_permission
):
    actor, access_token = await _create_and_login(api_client, real_session, "manual-incomplete")
    await grant_permission(actor, PERMISSION_LAB_MANAGE)
    await grant_permission(actor, PERMISSION_LAB_BILL)
    test_id = await _create_test(
        api_client, access_token, f"{TEST_LAB_TEST_NAME_PREFIX}ManualIncomplete"
    )

    resp = await api_client.post(
        "/api/v1/lab/bills",
        json={"patient_id": None, "items": [test_id], "manual_patient_name": "Half Filled"},
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "LAB_BILL_MANUAL_PATIENT_FIELDS_INCOMPLETE"


async def test_create_bill_anonymous_walk_in_has_no_patient_or_manual_fields(
    api_client, real_session, grant_permission
):
    actor, access_token = await _create_and_login(api_client, real_session, "anonymous")
    await grant_permission(actor, PERMISSION_LAB_MANAGE)
    await grant_permission(actor, PERMISSION_LAB_BILL)
    test_id = await _create_test(api_client, access_token, f"{TEST_LAB_TEST_NAME_PREFIX}Anonymous")

    resp = await api_client.post(
        "/api/v1/lab/bills",
        json={"patient_id": None, "items": [test_id]},
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 201, resp.text
    bill = resp.json()["data"]
    assert bill["patient_id"] is None
    assert bill["manual_patient_name"] is None


# ----------------------------------------------------------------------
# Discount
# ----------------------------------------------------------------------


async def test_create_bill_with_discount_computes_correct_total(
    api_client, real_session, grant_permission
):
    actor, access_token = await _create_and_login(api_client, real_session, "discount")
    await grant_permission(actor, PERMISSION_LAB_MANAGE)
    await grant_permission(actor, PERMISSION_LAB_BILL)
    test_id = await _create_test(
        api_client, access_token, f"{TEST_LAB_TEST_NAME_PREFIX}Discount", price="1000.00"
    )

    resp = await api_client.post(
        "/api/v1/lab/bills",
        json={
            "patient_id": None,
            "items": [test_id],
            "manual_patient_name": "Walk-in",
            "manual_patient_age": 40,
            "manual_patient_phone": "03001112222",
            "discount_amount": "100.00",
            "discount_reason": "Loyalty discount",
        },
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 201, resp.text
    bill = resp.json()["data"]
    assert bill["total_amount"] == "900.00"
    assert bill["discount_amount"] == "100.00"
    assert bill["discount_reason"] == "Loyalty discount"


async def test_create_bill_discount_exceeding_subtotal_rejected(
    api_client, real_session, grant_permission
):
    actor, access_token = await _create_and_login(api_client, real_session, "discount-exceeds")
    await grant_permission(actor, PERMISSION_LAB_MANAGE)
    await grant_permission(actor, PERMISSION_LAB_BILL)
    test_id = await _create_test(
        api_client, access_token, f"{TEST_LAB_TEST_NAME_PREFIX}DiscountExceeds", price="500.00"
    )

    resp = await api_client.post(
        "/api/v1/lab/bills",
        json={
            "patient_id": None,
            "items": [test_id],
            "manual_patient_name": "Walk-in",
            "manual_patient_age": 40,
            "manual_patient_phone": "03001112222",
            "discount_amount": "600.00",
        },
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "LAB_BILL_DISCOUNT_EXCEEDS_SUBTOTAL"


# ----------------------------------------------------------------------
# Payments
# ----------------------------------------------------------------------


async def test_bill_payment_exceeding_balance_rejected(api_client, real_session, grant_permission):
    actor, access_token = await _create_and_login(api_client, real_session, "pay-exceeds")
    await grant_permission(actor, PERMISSION_LAB_MANAGE)
    await grant_permission(actor, PERMISSION_LAB_BILL)
    test_id = await _create_test(
        api_client, access_token, f"{TEST_LAB_TEST_NAME_PREFIX}PayExceeds", price="500.00"
    )
    bill_resp = await api_client.post(
        "/api/v1/lab/bills",
        json={
            "patient_id": None,
            "items": [test_id],
            "manual_patient_name": "Walk-in",
            "manual_patient_age": 40,
            "manual_patient_phone": "03001112222",
        },
        headers=_auth_header(access_token),
    )
    bill_id = bill_resp.json()["data"]["id"]

    resp = await api_client.post(
        f"/api/v1/lab/bills/{bill_id}/pay",
        json={"amount": "600.00", "payment_method": "cash"},
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "LAB_BILL_PAYMENT_EXCEEDS_BALANCE"


async def test_bill_payment_on_already_paid_bill_rejected(
    api_client, real_session, grant_permission
):
    actor, access_token = await _create_and_login(api_client, real_session, "pay-already-paid")
    await grant_permission(actor, PERMISSION_LAB_MANAGE)
    await grant_permission(actor, PERMISSION_LAB_BILL)
    test_id = await _create_test(
        api_client, access_token, f"{TEST_LAB_TEST_NAME_PREFIX}AlreadyPaid", price="500.00"
    )
    bill_resp = await api_client.post(
        "/api/v1/lab/bills",
        json={
            "patient_id": None,
            "items": [test_id],
            "manual_patient_name": "Walk-in",
            "manual_patient_age": 40,
            "manual_patient_phone": "03001112222",
            "initial_payment_amount": "500.00",
            "initial_payment_method": "cash",
        },
        headers=_auth_header(access_token),
    )
    bill_id = bill_resp.json()["data"]["id"]
    assert bill_resp.json()["data"]["status"] == "paid"

    resp = await api_client.post(
        f"/api/v1/lab/bills/{bill_id}/pay",
        json={"amount": "1.00", "payment_method": "cash"},
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "LAB_BILL_NOT_PAYABLE"


async def test_create_bill_initial_payment_without_method_rejected(
    api_client, real_session, grant_permission
):
    actor, access_token = await _create_and_login(api_client, real_session, "no-method")
    await grant_permission(actor, PERMISSION_LAB_MANAGE)
    await grant_permission(actor, PERMISSION_LAB_BILL)
    test_id = await _create_test(api_client, access_token, f"{TEST_LAB_TEST_NAME_PREFIX}NoMethod")

    resp = await api_client.post(
        "/api/v1/lab/bills",
        json={
            "patient_id": None,
            "items": [test_id],
            "manual_patient_name": "Walk-in",
            "manual_patient_age": 40,
            "manual_patient_phone": "03001112222",
            "initial_payment_amount": "100.00",
        },
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "LAB_BILL_PAYMENT_METHOD_REQUIRED"


# ----------------------------------------------------------------------
# Listing — day view, "my bills", stats by creator
# ----------------------------------------------------------------------


async def test_list_bills_for_day_returns_todays_bills(api_client, real_session, grant_permission):
    actor, access_token = await _create_and_login(api_client, real_session, "list-day")
    await grant_permission(actor, PERMISSION_LAB_MANAGE)
    await grant_permission(actor, PERMISSION_LAB_BILL)
    await grant_permission(actor, PERMISSION_LAB_READ)
    test_id = await _create_test(api_client, access_token, f"{TEST_LAB_TEST_NAME_PREFIX}ListDay")
    await api_client.post(
        "/api/v1/lab/bills",
        json={
            "patient_id": None,
            "items": [test_id],
            "manual_patient_name": "Walk-in",
            "manual_patient_age": 40,
            "manual_patient_phone": "03001112222",
        },
        headers=_auth_header(access_token),
    )

    resp = await api_client.get(
        "/api/v1/lab/bills", params={"date": _TODAY}, headers=_auth_header(access_token)
    )

    assert resp.status_code == 200
    rows = resp.json()["data"]
    assert any(row["manual_patient_name"] == "Walk-in" and row["item_count"] == 1 for row in rows)


async def test_list_my_bills_returns_only_own_bills(api_client, real_session, grant_permission):
    actor_a, token_a = await _create_and_login(api_client, real_session, "mine-a")
    await grant_permission(actor_a, PERMISSION_LAB_MANAGE)
    await grant_permission(actor_a, PERMISSION_LAB_BILL)
    await grant_permission(actor_a, PERMISSION_LAB_READ)
    actor_b, token_b = await _create_and_login(api_client, real_session, "mine-b")
    await grant_permission(actor_b, PERMISSION_LAB_BILL)
    await grant_permission(actor_b, PERMISSION_LAB_READ)
    test_id = await _create_test(api_client, token_a, f"{TEST_LAB_TEST_NAME_PREFIX}MineOnly")

    for token in (token_a, token_b):
        await api_client.post(
            "/api/v1/lab/bills",
            json={
                "patient_id": None,
                "items": [test_id],
                "manual_patient_name": "Walk-in",
                "manual_patient_age": 40,
                "manual_patient_phone": "03001112222",
            },
            headers=_auth_header(token),
        )

    resp = await api_client.get("/api/v1/lab/bills/mine", headers=_auth_header(token_a))

    assert resp.status_code == 200
    assert len(resp.json()["data"]) == 1


async def test_get_bill_stats_by_creator_returns_accurate_counts_and_revenue(
    api_client, real_session, grant_permission
):
    actor, access_token = await _create_and_login(api_client, real_session, "stats-correctness")
    await grant_permission(actor, PERMISSION_LAB_MANAGE)
    await grant_permission(actor, PERMISSION_LAB_BILL)
    await grant_permission(actor, PERMISSION_LAB_READ)
    test_id = await _create_test(
        api_client, access_token, f"{TEST_LAB_TEST_NAME_PREFIX}StatsCorrectness", price="250.00"
    )

    bill_resp = await api_client.post(
        "/api/v1/lab/bills",
        json={
            "patient_id": None,
            "items": [test_id, test_id],
            "manual_patient_name": "Walk-in",
            "manual_patient_age": 40,
            "manual_patient_phone": "03001112222",
        },
        headers=_auth_header(access_token),
    )
    assert bill_resp.status_code == 201, bill_resp.text

    resp = await api_client.get(
        "/api/v1/lab/bills/stats/by-creator", headers=_auth_header(access_token)
    )

    assert resp.status_code == 200
    rows = {row["user_id"]: row for row in resp.json()["data"]}
    assert rows[str(actor.id)]["count"] == 1
    assert rows[str(actor.id)]["revenue"] == "500.00"


# ----------------------------------------------------------------------
# Admin data correction
# ----------------------------------------------------------------------


async def test_update_bill_admin_can_correct_discount(api_client, real_session, grant_permission):
    actor, access_token = await _create_and_login(api_client, real_session, "admin-correct")
    await grant_permission(actor, PERMISSION_LAB_MANAGE)
    await grant_permission(actor, PERMISSION_LAB_BILL)
    await grant_permission(actor, PERMISSION_LAB_UPDATE_BILL)
    test_id = await _create_test(
        api_client, access_token, f"{TEST_LAB_TEST_NAME_PREFIX}AdminCorrect", price="1000.00"
    )
    bill_resp = await api_client.post(
        "/api/v1/lab/bills",
        json={
            "patient_id": None,
            "items": [test_id],
            "manual_patient_name": "Wrong Name",
            "manual_patient_age": 40,
            "manual_patient_phone": "03001112222",
        },
        headers=_auth_header(access_token),
    )
    bill_id = bill_resp.json()["data"]["id"]

    resp = await api_client.patch(
        f"/api/v1/lab/bills/{bill_id}",
        json={
            "manual_patient_name": "Corrected Name",
            "discount_amount": "200.00",
            "discount_reason": "Data-entry correction",
        },
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 200, resp.text
    bill = resp.json()["data"]
    assert bill["manual_patient_name"] == "Corrected Name"
    assert bill["total_amount"] == "800.00"


async def test_update_bill_blocked_once_bill_has_any_payment(
    api_client, real_session, grant_permission
):
    actor, access_token = await _create_and_login(api_client, real_session, "blocked-update")
    await grant_permission(actor, PERMISSION_LAB_MANAGE)
    await grant_permission(actor, PERMISSION_LAB_BILL)
    await grant_permission(actor, PERMISSION_LAB_UPDATE_BILL)
    test_id = await _create_test(
        api_client, access_token, f"{TEST_LAB_TEST_NAME_PREFIX}BlockedUpdate", price="500.00"
    )
    bill_resp = await api_client.post(
        "/api/v1/lab/bills",
        json={
            "patient_id": None,
            "items": [test_id],
            "manual_patient_name": "Walk-in",
            "manual_patient_age": 40,
            "manual_patient_phone": "03001112222",
            "initial_payment_amount": "100.00",
            "initial_payment_method": "cash",
        },
        headers=_auth_header(access_token),
    )
    bill_id = bill_resp.json()["data"]["id"]

    resp = await api_client.patch(
        f"/api/v1/lab/bills/{bill_id}",
        json={"discount_amount": "50.00"},
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "LAB_BILL_HAS_SETTLED_PAYMENT"


async def test_delete_bill_success_removes_it_from_get(api_client, real_session, grant_permission):
    actor, access_token = await _create_and_login(api_client, real_session, "delete-success")
    await grant_permission(actor, PERMISSION_LAB_MANAGE)
    await grant_permission(actor, PERMISSION_LAB_BILL)
    await grant_permission(actor, PERMISSION_LAB_DELETE_BILL)
    await grant_permission(actor, PERMISSION_LAB_READ)
    test_id = await _create_test(
        api_client, access_token, f"{TEST_LAB_TEST_NAME_PREFIX}DeleteSuccess"
    )
    bill_resp = await api_client.post(
        "/api/v1/lab/bills",
        json={
            "patient_id": None,
            "items": [test_id],
            "manual_patient_name": "Walk-in",
            "manual_patient_age": 40,
            "manual_patient_phone": "03001112222",
        },
        headers=_auth_header(access_token),
    )
    bill_id = bill_resp.json()["data"]["id"]

    delete_resp = await api_client.delete(
        f"/api/v1/lab/bills/{bill_id}", headers=_auth_header(access_token)
    )
    assert delete_resp.status_code == 200, delete_resp.text

    get_resp = await api_client.get(
        f"/api/v1/lab/bills/{bill_id}", headers=_auth_header(access_token)
    )
    assert get_resp.status_code == 404


async def test_delete_bill_blocked_once_bill_has_any_payment(
    api_client, real_session, grant_permission
):
    actor, access_token = await _create_and_login(api_client, real_session, "blocked-delete")
    await grant_permission(actor, PERMISSION_LAB_MANAGE)
    await grant_permission(actor, PERMISSION_LAB_BILL)
    await grant_permission(actor, PERMISSION_LAB_DELETE_BILL)
    test_id = await _create_test(
        api_client, access_token, f"{TEST_LAB_TEST_NAME_PREFIX}BlockedDelete", price="500.00"
    )
    bill_resp = await api_client.post(
        "/api/v1/lab/bills",
        json={
            "patient_id": None,
            "items": [test_id],
            "manual_patient_name": "Walk-in",
            "manual_patient_age": 40,
            "manual_patient_phone": "03001112222",
            "initial_payment_amount": "500.00",
            "initial_payment_method": "cash",
        },
        headers=_auth_header(access_token),
    )
    bill_id = bill_resp.json()["data"]["id"]

    resp = await api_client.delete(
        f"/api/v1/lab/bills/{bill_id}", headers=_auth_header(access_token)
    )

    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "LAB_BILL_HAS_SETTLED_PAYMENT"


# ----------------------------------------------------------------------
# Test catalog CRUD
# ----------------------------------------------------------------------


async def test_update_test_partial_patch_only_changes_given_fields(
    api_client, real_session, grant_permission
):
    actor, access_token = await _create_and_login(api_client, real_session, "patch-test")
    await grant_permission(actor, PERMISSION_LAB_MANAGE)
    test_id = await _create_test(
        api_client,
        access_token,
        f"{TEST_LAB_TEST_NAME_PREFIX}PatchTest",
        category="pathology",
        price="500.00",
    )

    resp = await api_client.patch(
        f"/api/v1/lab/tests/{test_id}",
        json={"price": "650.00"},
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 200, resp.text
    test = resp.json()["data"]
    assert test["price"] == "650.00"
    assert test["name"] == f"{TEST_LAB_TEST_NAME_PREFIX}PatchTest"
    assert test["category"] == "pathology"


async def test_search_tests_excludes_inactive(api_client, real_session, grant_permission):
    actor, access_token = await _create_and_login(api_client, real_session, "search-inactive")
    await grant_permission(actor, PERMISSION_LAB_MANAGE)
    await grant_permission(actor, PERMISSION_LAB_READ)
    test_id = await _create_test(
        api_client, access_token, f"{TEST_LAB_TEST_NAME_PREFIX}SearchInactive"
    )
    await api_client.patch(
        f"/api/v1/lab/tests/{test_id}",
        json={"is_active": False},
        headers=_auth_header(access_token),
    )

    resp = await api_client.get(
        "/api/v1/lab/tests/search",
        params={"search": f"{TEST_LAB_TEST_NAME_PREFIX}SearchInactive"},
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 200
    assert resp.json()["data"] == []


# ----------------------------------------------------------------------
# Print (Central Print Service integration)
# ----------------------------------------------------------------------


async def test_print_bill_requires_permission(api_client, real_session, grant_permission):
    actor, access_token = await _create_and_login(api_client, real_session, "print-no-perm")
    await grant_permission(actor, PERMISSION_LAB_MANAGE)
    await grant_permission(actor, PERMISSION_LAB_BILL)
    test_id = await _create_test(
        api_client, access_token, f"{TEST_LAB_TEST_NAME_PREFIX}PrintNoPerm"
    )
    bill_resp = await api_client.post(
        "/api/v1/lab/bills",
        json={
            "patient_id": None,
            "items": [test_id],
            "manual_patient_name": "Walk-in",
            "manual_patient_age": 40,
            "manual_patient_phone": "03001112222",
        },
        headers=_auth_header(access_token),
    )
    bill_id = bill_resp.json()["data"]["id"]

    # A fresh actor with no lab permissions at all.
    _other_actor, other_token = await _create_and_login(api_client, real_session, "print-no-perm-2")

    resp = await api_client.get(
        f"/api/v1/lab/bills/{bill_id}/print", headers=_auth_header(other_token)
    )

    assert resp.status_code == 403


async def test_print_bill_with_manual_patient_shows_reference_and_totals(
    api_client, real_session, grant_permission
):
    actor, access_token = await _create_and_login(api_client, real_session, "print-manual")
    await grant_permission(actor, PERMISSION_LAB_MANAGE)
    await grant_permission(actor, PERMISSION_LAB_BILL)
    await grant_permission(actor, PERMISSION_LAB_READ)
    test_id = await _create_test(
        api_client, access_token, f"{TEST_LAB_TEST_NAME_PREFIX}PrintManual", price="700.00"
    )
    bill_resp = await api_client.post(
        "/api/v1/lab/bills",
        json={
            "patient_id": None,
            "items": [test_id],
            "manual_patient_name": "Print Manual Patient",
            "manual_patient_age": 44,
            "manual_patient_phone": "03007778888",
            "initial_payment_amount": "700.00",
            "initial_payment_method": "cash",
        },
        headers=_auth_header(access_token),
    )
    bill = bill_resp.json()["data"]

    resp = await api_client.get(
        f"/api/v1/lab/bills/{bill['id']}/print", headers=_auth_header(access_token)
    )

    assert resp.status_code == 200, resp.text
    assert bill["queue_token"] in resp.text
    assert "Print Manual Patient" in resp.text
    assert "44 years" in resp.text
    assert "03007778888" in resp.text
    assert f"{TEST_LAB_TEST_NAME_PREFIX}PrintManual" in resp.text
    assert "Pathology" in resp.text
    assert "700.00" in resp.text
    assert "Sale Type" not in resp.text


async def test_print_bill_with_linked_patient_shows_patient_reference(
    api_client, real_session, grant_permission
):
    actor, access_token = await _create_and_login(api_client, real_session, "print-linked")
    await grant_permission(actor, PERMISSION_LAB_MANAGE)
    await grant_permission(actor, PERMISSION_LAB_BILL)
    await grant_permission(actor, PERMISSION_LAB_READ)
    await grant_permission(actor, PERMISSION_PATIENTS_CREATE)
    test_id = await _create_test(
        api_client, access_token, f"{TEST_LAB_TEST_NAME_PREFIX}PrintLinked"
    )
    patient_id = await _create_patient(
        api_client, access_token, f"{TEST_PATIENT_NAME_PREFIX}PrintLinked"
    )
    bill_resp = await api_client.post(
        "/api/v1/lab/bills",
        json={"patient_id": patient_id, "items": [test_id]},
        headers=_auth_header(access_token),
    )
    bill_id = bill_resp.json()["data"]["id"]

    resp = await api_client.get(
        f"/api/v1/lab/bills/{bill_id}/print", headers=_auth_header(access_token)
    )

    assert resp.status_code == 200, resp.text
    assert f"{TEST_PATIENT_NAME_PREFIX}PrintLinked" in resp.text
    assert "Patient Reference" in resp.text


async def test_print_bill_anonymous_walk_in_shows_sale_reference(
    api_client, real_session, grant_permission
):
    actor, access_token = await _create_and_login(api_client, real_session, "print-anonymous")
    await grant_permission(actor, PERMISSION_LAB_MANAGE)
    await grant_permission(actor, PERMISSION_LAB_BILL)
    await grant_permission(actor, PERMISSION_LAB_READ)
    test_id = await _create_test(
        api_client, access_token, f"{TEST_LAB_TEST_NAME_PREFIX}PrintAnonymous"
    )
    bill_resp = await api_client.post(
        "/api/v1/lab/bills",
        json={"patient_id": None, "items": [test_id]},
        headers=_auth_header(access_token),
    )
    bill_id = bill_resp.json()["data"]["id"]

    resp = await api_client.get(
        f"/api/v1/lab/bills/{bill_id}/print", headers=_auth_header(access_token)
    )

    assert resp.status_code == 200, resp.text
    assert "Sale Type" in resp.text
    assert "Walk-in (no patient on file)" in resp.text
    assert "Patient Reference" not in resp.text

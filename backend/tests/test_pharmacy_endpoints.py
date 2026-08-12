"""Full end-to-end HTTP tests for the Pharmacy / Medicine Billing module
— see tests/test_billing_endpoints.py's identical module docstring."""

from datetime import UTC, datetime
from decimal import Decimal

from app.modules.auth.models import User, UserStatus
from app.modules.auth.password_service import PasswordService
from app.modules.auth.repository import UserRepository
from app.modules.pharmacy.constants import (
    PERMISSION_PHARMACY_BILL,
    PERMISSION_PHARMACY_MANAGE,
    PERMISSION_PHARMACY_READ,
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
            "procedure": "Consultation",
            "amount": "1000.00",
            "vitals_required": False,
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
        json={"amount": "80.00"},
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
        json={"amount": "50.00"},
        headers=_auth_header(access_token),
    )
    assert second_pay.status_code == 200, second_pay.text
    second_body = second_pay.json()["data"]
    assert second_body["status"] == "partially_paid"
    assert second_body["amount_paid"] == "130.00"
    assert len(second_body["payments"]) == 2

    third_pay = await api_client.post(
        f"/api/v1/pharmacy/bills/{bill_id}/pay",
        json={"amount": "70.00"},
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
    assert "Amount Paid" in print_resp.text
    assert "Balance Due" in print_resp.text


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
        json={"amount": "50.01"},
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
        json={"amount": "25.00"},
        headers=_auth_header(access_token),
    )
    assert first_pay.json()["data"]["status"] == "paid"

    resp = await api_client.post(
        f"/api/v1/pharmacy/bills/{bill_id}/pay",
        json={"amount": "1.00"},
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
        json={"amount": "0"},
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
        json={"amount": "10.00"},
        headers=_auth_header(other_token),
    )

    assert resp.status_code == 403


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

"""End-to-end HTTP tests for Pharmacy medicine stock tracking (2026-09
addition) — a single `stock_quantity` Integer on `medicine`, the
`POST /pharmacy/medicines/{id}/stock/add` restock endpoint, the global
low-stock threshold, and `create_bill`'s soft insufficient-stock block
with an explicit override. Same conventions as
tests/test_pharmacy_endpoints.py."""

import asyncio

from sqlalchemy import text

from app.modules.auth.models import User, UserStatus
from app.modules.auth.password_service import PasswordService
from app.modules.auth.repository import UserRepository
from app.modules.pharmacy.constants import (
    PERMISSION_PHARMACY_BILL,
    PERMISSION_PHARMACY_MANAGE,
    PERMISSION_PHARMACY_READ,
)
from tests.conftest import TEST_MEDICINE_NAME_PREFIX, make_test_email

_PASSWORD = "Str0ng!Passw0rd#2026"


async def _create_and_login(api_client, real_session, suffix: str) -> tuple[User, str]:
    password_hash = await PasswordService().hash(_PASSWORD)
    email = make_test_email(suffix)
    user = await UserRepository(real_session).add(
        User(
            email=email,
            password_hash=password_hash,
            full_name="Pharmacy Stock Actor",
            status=UserStatus.ACTIVE,
            must_change_password=False,
        )
    )
    await real_session.commit()
    login_resp = await api_client.post(
        "/api/v1/auth/login", json={"email": email, "password": _PASSWORD}
    )
    return user, login_resp.json()["data"]["access_token"]


def _auth_header(access_token: str) -> dict:
    return {"Authorization": f"Bearer {access_token}"}


async def _create_medicine(api_client, access_token, name: str, *, price: str = "50.00") -> str:
    resp = await api_client.post(
        "/api/v1/pharmacy/medicines",
        json={"name": name, "category": "tablet", "unit_price": price},
        headers=_auth_header(access_token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]["id"]


async def _add_stock(api_client, access_token, medicine_id: str, quantity: int) -> dict:
    resp = await api_client.post(
        f"/api/v1/pharmacy/medicines/{medicine_id}/stock/add",
        json={"quantity": quantity},
        headers=_auth_header(access_token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]


async def _search_one(api_client, access_token, name: str) -> dict:
    resp = await api_client.get(
        "/api/v1/pharmacy/medicines/search",
        params={"search": name},
        headers=_auth_header(access_token),
    )
    assert resp.status_code == 200, resp.text
    rows = [row for row in resp.json()["data"] if row["name"] == name]
    assert len(rows) == 1, rows
    return rows[0]


# ----------------------------------------------------------------------
# Catalog: new medicines start at 0, threshold boundary, restock endpoint
# ----------------------------------------------------------------------


async def test_new_medicine_starts_at_zero_stock_and_reads_low(
    api_client, real_session, grant_permission
):
    actor, token = await _create_and_login(api_client, real_session, "stock-zero-default")
    await grant_permission(actor, PERMISSION_PHARMACY_MANAGE)

    name = f"{TEST_MEDICINE_NAME_PREFIX}StockZeroDefault"
    resp = await api_client.post(
        "/api/v1/pharmacy/medicines",
        json={"name": name, "category": "tablet", "unit_price": "50.00"},
        headers=_auth_header(token),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()["data"]
    assert body["stock_quantity"] == 0
    assert body["is_low_stock"] is True  # 0 <= 10


async def test_add_stock_requires_manage_permission(api_client, real_session, grant_permission):
    admin, admin_token = await _create_and_login(api_client, real_session, "stock-perm-admin")
    await grant_permission(admin, PERMISSION_PHARMACY_MANAGE)
    medicine_id = await _create_medicine(
        api_client, admin_token, f"{TEST_MEDICINE_NAME_PREFIX}StockPerm"
    )

    biller, biller_token = await _create_and_login(api_client, real_session, "stock-perm-biller")
    await grant_permission(biller, PERMISSION_PHARMACY_BILL)
    await grant_permission(biller, PERMISSION_PHARMACY_READ)

    resp = await api_client.post(
        f"/api/v1/pharmacy/medicines/{medicine_id}/stock/add",
        json={"quantity": 5},
        headers=_auth_header(biller_token),
    )
    assert resp.status_code == 403


async def test_add_stock_increments_and_writes_an_audit_row(
    api_client, real_session, grant_permission
):
    actor, token = await _create_and_login(api_client, real_session, "stock-add-audit")
    await grant_permission(actor, PERMISSION_PHARMACY_MANAGE)
    medicine_id = await _create_medicine(
        api_client, token, f"{TEST_MEDICINE_NAME_PREFIX}StockAddAudit"
    )

    after_first = await _add_stock(api_client, token, medicine_id, 40)
    assert after_first["stock_quantity"] == 40
    assert after_first["is_low_stock"] is False
    after_second = await _add_stock(api_client, token, medicine_id, 10)
    assert after_second["stock_quantity"] == 50

    count = (
        await real_session.execute(
            text(
                "SELECT count(*) FROM audit_log WHERE entity_id = :mid "
                "AND action = 'pharmacy.medicine_stock_added'"
            ),
            {"mid": medicine_id},
        )
    ).scalar_one()
    assert count == 2


async def test_add_stock_rejects_non_positive_quantity(api_client, real_session, grant_permission):
    actor, token = await _create_and_login(api_client, real_session, "stock-add-zero")
    await grant_permission(actor, PERMISSION_PHARMACY_MANAGE)
    medicine_id = await _create_medicine(
        api_client, token, f"{TEST_MEDICINE_NAME_PREFIX}StockAddZero"
    )
    resp = await api_client.post(
        f"/api/v1/pharmacy/medicines/{medicine_id}/stock/add",
        json={"quantity": 0},
        headers=_auth_header(token),
    )
    assert resp.status_code == 422


async def test_is_low_stock_flips_at_the_global_threshold_boundary(
    api_client, real_session, grant_permission
):
    """PHARMACY_LOW_STOCK_THRESHOLD is 10: stock_quantity <= 10 reads
    low, == 11 does not."""
    actor, token = await _create_and_login(api_client, real_session, "stock-boundary")
    await grant_permission(actor, PERMISSION_PHARMACY_MANAGE)
    await grant_permission(actor, PERMISSION_PHARMACY_READ)
    name = f"{TEST_MEDICINE_NAME_PREFIX}StockBoundary"
    medicine_id = await _create_medicine(api_client, token, name)

    at_ten = await _add_stock(api_client, token, medicine_id, 10)
    assert at_ten["stock_quantity"] == 10
    assert at_ten["is_low_stock"] is True

    at_eleven = await _add_stock(api_client, token, medicine_id, 1)
    assert at_eleven["stock_quantity"] == 11
    assert at_eleven["is_low_stock"] is False


# ----------------------------------------------------------------------
# Bill sale: decrement, soft block, override + clamp, concurrency
# ----------------------------------------------------------------------


async def test_bill_within_stock_decrements_the_count(api_client, real_session, grant_permission):
    actor, token = await _create_and_login(api_client, real_session, "stock-bill-ok")
    await grant_permission(actor, PERMISSION_PHARMACY_MANAGE)
    await grant_permission(actor, PERMISSION_PHARMACY_BILL)
    await grant_permission(actor, PERMISSION_PHARMACY_READ)
    name = f"{TEST_MEDICINE_NAME_PREFIX}StockBillOk"
    medicine_id = await _create_medicine(api_client, token, name, price="30.00")
    await _add_stock(api_client, token, medicine_id, 10)

    resp = await api_client.post(
        "/api/v1/pharmacy/bills",
        json={"visit_id": None, "items": [{"medicine_id": medicine_id, "quantity": 4}]},
        headers=_auth_header(token),
    )
    assert resp.status_code == 201, resp.text

    assert (await _search_one(api_client, token, name))["stock_quantity"] == 6


async def test_bill_over_stock_without_override_is_blocked_with_available_count(
    api_client, real_session, grant_permission
):
    actor, token = await _create_and_login(api_client, real_session, "stock-bill-block")
    await grant_permission(actor, PERMISSION_PHARMACY_MANAGE)
    await grant_permission(actor, PERMISSION_PHARMACY_BILL)
    await grant_permission(actor, PERMISSION_PHARMACY_READ)
    name = f"{TEST_MEDICINE_NAME_PREFIX}StockBillBlock"
    medicine_id = await _create_medicine(api_client, token, name)
    await _add_stock(api_client, token, medicine_id, 3)

    resp = await api_client.post(
        "/api/v1/pharmacy/bills",
        json={"visit_id": None, "items": [{"medicine_id": medicine_id, "quantity": 5}]},
        headers=_auth_header(token),
    )
    assert resp.status_code == 422
    error = resp.json()["error"]
    assert error["code"] == "MEDICINE_INSUFFICIENT_STOCK"
    shortfalls = error["details"]["shortfalls"]
    assert len(shortfalls) == 1
    assert shortfalls[0]["medicine_id"] == medicine_id
    assert shortfalls[0]["requested"] == 5
    assert shortfalls[0]["available"] == 3

    # Nothing was written — stock untouched.
    assert (await _search_one(api_client, token, name))["stock_quantity"] == 3


async def test_bill_over_stock_with_override_succeeds_and_clamps_at_zero(
    api_client, real_session, grant_permission
):
    actor, token = await _create_and_login(api_client, real_session, "stock-bill-override")
    await grant_permission(actor, PERMISSION_PHARMACY_MANAGE)
    await grant_permission(actor, PERMISSION_PHARMACY_BILL)
    await grant_permission(actor, PERMISSION_PHARMACY_READ)
    name = f"{TEST_MEDICINE_NAME_PREFIX}StockBillOverride"
    medicine_id = await _create_medicine(api_client, token, name, price="20.00")
    await _add_stock(api_client, token, medicine_id, 3)

    resp = await api_client.post(
        "/api/v1/pharmacy/bills",
        json={
            "visit_id": None,
            "items": [{"medicine_id": medicine_id, "quantity": 5}],
            "override_insufficient_stock": True,
        },
        headers=_auth_header(token),
    )
    assert resp.status_code == 201, resp.text
    bill = resp.json()["data"]
    # The sale is recorded in full even though the count was short.
    assert bill["items"][0]["quantity"] == 5
    assert bill["total_amount"] == "100.00"

    # Stock clamped at 0, never negative (the CHECK constraint holds).
    assert (await _search_one(api_client, token, name))["stock_quantity"] == 0


async def test_two_concurrent_bills_for_the_last_unit_serialize_on_the_row_lock(
    api_client, real_session, grant_permission
):
    """The core concurrency guarantee: MedicineRepository.get_for_update
    serializes two simultaneous sells of the same medicine's last unit —
    exactly one bill succeeds within stock, the other is blocked (no
    override), and the count never goes negative."""
    actor, token = await _create_and_login(api_client, real_session, "stock-concurrent")
    await grant_permission(actor, PERMISSION_PHARMACY_MANAGE)
    await grant_permission(actor, PERMISSION_PHARMACY_BILL)
    await grant_permission(actor, PERMISSION_PHARMACY_READ)
    name = f"{TEST_MEDICINE_NAME_PREFIX}StockConcurrent"
    medicine_id = await _create_medicine(api_client, token, name, price="15.00")
    await _add_stock(api_client, token, medicine_id, 1)

    payload = {"visit_id": None, "items": [{"medicine_id": medicine_id, "quantity": 1}]}
    first, second = await asyncio.gather(
        api_client.post("/api/v1/pharmacy/bills", json=payload, headers=_auth_header(token)),
        api_client.post("/api/v1/pharmacy/bills", json=payload, headers=_auth_header(token)),
    )

    statuses = sorted([first.status_code, second.status_code])
    assert statuses == [201, 422], (first.status_code, second.status_code, first.text, second.text)
    loser = first if first.status_code == 422 else second
    assert loser.json()["error"]["code"] == "MEDICINE_INSUFFICIENT_STOCK"
    assert loser.json()["error"]["details"]["shortfalls"][0]["available"] == 0

    # Exactly one unit sold; the count landed at 0, never below.
    assert (await _search_one(api_client, token, name))["stock_quantity"] == 0

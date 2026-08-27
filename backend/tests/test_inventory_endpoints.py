"""Full end-to-end HTTP tests for the Ward/Emergency Inventory
Management module — see tests/test_pharmacy_endpoints.py's identical
module docstring."""

from datetime import date

from app.modules.auth.models import User, UserStatus
from app.modules.auth.password_service import PasswordService
from app.modules.auth.repository import UserRepository
from app.modules.inventory.constants import (
    PERMISSION_INVENTORY_MANAGE,
    PERMISSION_INVENTORY_READ,
    PERMISSION_INVENTORY_RECORD_USAGE,
    PERMISSION_INVENTORY_REQUEST_RESTOCK,
)
from app.modules.patients.constants import PERMISSION_PATIENTS_CREATE
from tests.conftest import (
    TEST_INVENTORY_ITEM_NAME_PREFIX,
    TEST_PATIENT_NAME_PREFIX,
    make_test_email,
)

_PASSWORD = "Str0ng!Passw0rd#2026"
_TODAY = date.today().isoformat()


async def _create_and_login(api_client, real_session, suffix: str) -> tuple[User, str]:
    password_hash = await PasswordService().hash(_PASSWORD)
    email = make_test_email(suffix)
    user = await UserRepository(real_session).add(
        User(
            email=email,
            password_hash=password_hash,
            full_name="Inventory Endpoint Actor",
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


async def _create_item(
    api_client, access_token, name: str, *, category: str = "medicine", unit: str = "piece"
) -> str:
    resp = await api_client.post(
        "/api/v1/inventory/items",
        json={"name": name, "category": category, "unit": unit},
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


async def test_create_item_requires_manage_permission(api_client, real_session):
    _actor, access_token = await _create_and_login(api_client, real_session, "no-perm-create")

    resp = await api_client.post(
        "/api/v1/inventory/items",
        json={
            "name": f"{TEST_INVENTORY_ITEM_NAME_PREFIX}NoPerm",
            "category": "medicine",
            "unit": "piece",
        },
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 403


async def test_list_items_requires_read_permission(api_client, real_session):
    _actor, access_token = await _create_and_login(api_client, real_session, "no-perm-list")

    resp = await api_client.get("/api/v1/inventory/items", headers=_auth_header(access_token))

    assert resp.status_code == 403


async def test_record_usage_requires_record_usage_permission(
    api_client, real_session, grant_permission
):
    actor, access_token = await _create_and_login(api_client, real_session, "no-perm-usage")
    await grant_permission(actor, PERMISSION_INVENTORY_MANAGE)
    item_id = await _create_item(
        api_client, access_token, f"{TEST_INVENTORY_ITEM_NAME_PREFIX}NoUsagePerm"
    )

    resp = await api_client.post(
        "/api/v1/inventory/usage",
        json={"items": [{"item_id": item_id, "quantity": "1"}], "used_on": _TODAY},
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 403


async def test_raise_restock_request_requires_request_restock_permission(
    api_client, real_session, grant_permission
):
    actor, access_token = await _create_and_login(api_client, real_session, "no-perm-restock")
    await grant_permission(actor, PERMISSION_INVENTORY_MANAGE)
    item_id = await _create_item(
        api_client, access_token, f"{TEST_INVENTORY_ITEM_NAME_PREFIX}NoRestockPerm"
    )

    resp = await api_client.post(
        "/api/v1/inventory/requests",
        json={"item_id": item_id},
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 403


async def test_fulfill_request_requires_manage_permission(
    api_client, real_session, grant_permission
):
    """Structural proof of the segregation of duties: a role holding
    only `inventory:request_restock` cannot fulfill its own request —
    that requires the separate `inventory:manage` code, held by the
    Inventory Manager, not Vitals."""
    manager, manager_token = await _create_and_login(api_client, real_session, "fulfill-manager")
    await grant_permission(manager, PERMISSION_INVENTORY_MANAGE)
    item_id = await _create_item(
        api_client, manager_token, f"{TEST_INVENTORY_ITEM_NAME_PREFIX}FulfillPerm"
    )

    vitals_actor, vitals_token = await _create_and_login(api_client, real_session, "fulfill-vitals")
    await grant_permission(vitals_actor, PERMISSION_INVENTORY_REQUEST_RESTOCK)
    request_resp = await api_client.post(
        "/api/v1/inventory/requests",
        json={"item_id": item_id},
        headers=_auth_header(vitals_token),
    )
    request_id = request_resp.json()["data"]["id"]

    resp = await api_client.post(
        f"/api/v1/inventory/requests/{request_id}/fulfill",
        json={"transfer_quantity": "5", "transferred_on": _TODAY},
        headers=_auth_header(vitals_token),
    )

    assert resp.status_code == 403


# ----------------------------------------------------------------------
# Catalog correctness
# ----------------------------------------------------------------------


async def test_create_item_rejects_category_unit_mismatch(
    api_client, real_session, grant_permission
):
    actor, access_token = await _create_and_login(api_client, real_session, "bad-unit")
    await grant_permission(actor, PERMISSION_INVENTORY_MANAGE)

    resp = await api_client.post(
        "/api/v1/inventory/items",
        # "ml" is not a standardized unit for "equipment" — see
        # app/modules/inventory/models.py's CATEGORY_ALLOWED_UNITS.
        json={
            "name": f"{TEST_INVENTORY_ITEM_NAME_PREFIX}BadUnit",
            "category": "equipment",
            "unit": "ml",
        },
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "INVENTORY_CATEGORY_UNIT_MISMATCH"


async def test_update_item_revalidates_category_unit_on_partial_patch(
    api_client, real_session, grant_permission
):
    """A PATCH that only changes `category` must still be checked
    against the item's *existing* unit — see InventoryService.
    update_item's own docstring for why this can only be validated in
    the service, never the request schema alone."""
    actor, access_token = await _create_and_login(api_client, real_session, "patch-mismatch")
    await grant_permission(actor, PERMISSION_INVENTORY_MANAGE)
    item_id = await _create_item(
        api_client,
        access_token,
        f"{TEST_INVENTORY_ITEM_NAME_PREFIX}PatchMismatch",
        category="drip",
        unit="ml",
    )

    resp = await api_client.patch(
        f"/api/v1/inventory/items/{item_id}",
        json={"category": "equipment"},
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "INVENTORY_CATEGORY_UNIT_MISMATCH"


# ----------------------------------------------------------------------
# Stock-level correctness (receive / transfer / usage)
# ----------------------------------------------------------------------


async def test_receive_then_transfer_moves_stock_between_tiers(
    api_client, real_session, grant_permission
):
    actor, access_token = await _create_and_login(api_client, real_session, "receive-transfer")
    await grant_permission(actor, PERMISSION_INVENTORY_MANAGE)
    item_id = await _create_item(
        api_client, access_token, f"{TEST_INVENTORY_ITEM_NAME_PREFIX}ReceiveTransfer"
    )

    receive_resp = await api_client.post(
        f"/api/v1/inventory/items/{item_id}/receive",
        json={"quantity": "100", "received_on": _TODAY},
        headers=_auth_header(access_token),
    )
    assert receive_resp.status_code == 200, receive_resp.text
    assert receive_resp.json()["data"]["main_stock_level"] == "100.00"
    assert receive_resp.json()["data"]["emergency_stock_level"] == "0.00"

    transfer_resp = await api_client.post(
        f"/api/v1/inventory/items/{item_id}/transfer",
        json={"quantity": "30", "transferred_on": _TODAY},
        headers=_auth_header(access_token),
    )
    assert transfer_resp.status_code == 200, transfer_resp.text
    assert transfer_resp.json()["data"]["main_stock_level"] == "70.00"
    assert transfer_resp.json()["data"]["emergency_stock_level"] == "30.00"


async def test_transfer_exceeding_main_stock_is_rejected(
    api_client, real_session, grant_permission
):
    actor, access_token = await _create_and_login(api_client, real_session, "over-transfer")
    await grant_permission(actor, PERMISSION_INVENTORY_MANAGE)
    await grant_permission(actor, PERMISSION_INVENTORY_READ)
    item_id = await _create_item(
        api_client, access_token, f"{TEST_INVENTORY_ITEM_NAME_PREFIX}OverTransfer"
    )
    await api_client.post(
        f"/api/v1/inventory/items/{item_id}/receive",
        json={"quantity": "10", "received_on": _TODAY},
        headers=_auth_header(access_token),
    )

    resp = await api_client.post(
        f"/api/v1/inventory/items/{item_id}/transfer",
        json={"quantity": "11", "transferred_on": _TODAY},
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "INSUFFICIENT_MAIN_STOCK"

    # Neither level moved — a rejected transfer is fully atomic.
    item_resp = await api_client.get(
        f"/api/v1/inventory/items/{item_id}", headers=_auth_header(access_token)
    )
    assert item_resp.json()["data"]["main_stock_level"] == "10.00"
    assert item_resp.json()["data"]["emergency_stock_level"] == "0.00"


async def test_record_usage_decrements_emergency_stock(api_client, real_session, grant_permission):
    manager, manager_token = await _create_and_login(api_client, real_session, "usage-manager")
    await grant_permission(manager, PERMISSION_INVENTORY_MANAGE)
    await grant_permission(manager, PERMISSION_INVENTORY_READ)
    await grant_permission(manager, PERMISSION_PATIENTS_CREATE)
    item_id = await _create_item(
        api_client, manager_token, f"{TEST_INVENTORY_ITEM_NAME_PREFIX}UsageDecrement"
    )
    await api_client.post(
        f"/api/v1/inventory/items/{item_id}/receive",
        json={"quantity": "20", "received_on": _TODAY},
        headers=_auth_header(manager_token),
    )
    await api_client.post(
        f"/api/v1/inventory/items/{item_id}/transfer",
        json={"quantity": "20", "transferred_on": _TODAY},
        headers=_auth_header(manager_token),
    )

    vitals_actor, vitals_token = await _create_and_login(api_client, real_session, "usage-vitals")
    await grant_permission(vitals_actor, PERMISSION_INVENTORY_RECORD_USAGE)
    patient_id = await _create_patient(
        api_client, manager_token, f"{TEST_PATIENT_NAME_PREFIX}InventoryUsage"
    )

    resp = await api_client.post(
        "/api/v1/inventory/usage",
        json={
            "items": [{"item_id": item_id, "quantity": "6", "reason_note": "Post-op drip"}],
            "used_on": _TODAY,
            "patient_id": patient_id,
        },
        headers=_auth_header(vitals_token),
    )

    assert resp.status_code == 201, resp.text
    assert len(resp.json()["data"]) == 1
    assert resp.json()["data"][0]["patient_id"] == patient_id
    assert resp.json()["data"][0]["reason_note"] == "Post-op drip"

    item_resp = await api_client.get(
        f"/api/v1/inventory/items/{item_id}", headers=_auth_header(manager_token)
    )
    assert item_resp.json()["data"]["emergency_stock_level"] == "14.00"


async def test_record_usage_batch_creates_one_independent_entry_per_item(
    api_client, real_session, grant_permission
):
    """The 2026-08-27 batch addition: multiple items in one `items` list
    submitted together for the same patient must land as N separate,
    fully independent `InventoryUsageEntry` rows (matching Reception's
    procedure-list/Pharmacy's medicine-bill shape) — not a single merged
    row, and not a new parent/batch entity."""
    manager, manager_token = await _create_and_login(api_client, real_session, "usage-batch-mgr")
    await grant_permission(manager, PERMISSION_INVENTORY_MANAGE)
    await grant_permission(manager, PERMISSION_INVENTORY_READ)
    await grant_permission(manager, PERMISSION_PATIENTS_CREATE)
    item_a = await _create_item(
        api_client, manager_token, f"{TEST_INVENTORY_ITEM_NAME_PREFIX}BatchA"
    )
    item_b = await _create_item(
        api_client, manager_token, f"{TEST_INVENTORY_ITEM_NAME_PREFIX}BatchB"
    )
    for item_id in (item_a, item_b):
        await api_client.post(
            f"/api/v1/inventory/items/{item_id}/receive",
            json={"quantity": "20", "received_on": _TODAY},
            headers=_auth_header(manager_token),
        )
        await api_client.post(
            f"/api/v1/inventory/items/{item_id}/transfer",
            json={"quantity": "20", "transferred_on": _TODAY},
            headers=_auth_header(manager_token),
        )

    vitals_actor, vitals_token = await _create_and_login(
        api_client, real_session, "usage-batch-vitals"
    )
    await grant_permission(vitals_actor, PERMISSION_INVENTORY_RECORD_USAGE)
    patient_id = await _create_patient(
        api_client, manager_token, f"{TEST_PATIENT_NAME_PREFIX}InventoryUsageBatch"
    )

    resp = await api_client.post(
        "/api/v1/inventory/usage",
        json={
            "items": [
                {"item_id": item_a, "quantity": "5", "reason_note": "Line A"},
                {"item_id": item_b, "quantity": "3", "reason_note": "Line B"},
            ],
            "used_on": _TODAY,
            "patient_id": patient_id,
        },
        headers=_auth_header(vitals_token),
    )

    assert resp.status_code == 201, resp.text
    entries = resp.json()["data"]
    assert len(entries) == 2
    assert {entry["id"] for entry in entries} == {entries[0]["id"], entries[1]["id"]}
    assert all(entry["patient_id"] == patient_id for entry in entries)
    reason_notes = {entry["item_id"]: entry["reason_note"] for entry in entries}
    assert reason_notes[item_a] == "Line A"
    assert reason_notes[item_b] == "Line B"

    item_a_resp = await api_client.get(
        f"/api/v1/inventory/items/{item_a}", headers=_auth_header(manager_token)
    )
    item_b_resp = await api_client.get(
        f"/api/v1/inventory/items/{item_b}", headers=_auth_header(manager_token)
    )
    assert item_a_resp.json()["data"]["emergency_stock_level"] == "15.00"
    assert item_b_resp.json()["data"]["emergency_stock_level"] == "17.00"


async def test_record_usage_batch_is_all_or_nothing(api_client, real_session, grant_permission):
    """If any line in the batch fails validation, none of the batch's
    stock decrements or usage-entry rows may land — the same atomicity
    `PharmacyService.create_bill` guarantees for its own `items` list."""
    manager, manager_token = await _create_and_login(api_client, real_session, "usage-atomic-mgr")
    await grant_permission(manager, PERMISSION_INVENTORY_MANAGE)
    await grant_permission(manager, PERMISSION_INVENTORY_READ)
    ok_item = await _create_item(
        api_client, manager_token, f"{TEST_INVENTORY_ITEM_NAME_PREFIX}AtomicOk"
    )
    short_item = await _create_item(
        api_client, manager_token, f"{TEST_INVENTORY_ITEM_NAME_PREFIX}AtomicShort"
    )
    await api_client.post(
        f"/api/v1/inventory/items/{ok_item}/receive",
        json={"quantity": "20", "received_on": _TODAY},
        headers=_auth_header(manager_token),
    )
    await api_client.post(
        f"/api/v1/inventory/items/{ok_item}/transfer",
        json={"quantity": "20", "transferred_on": _TODAY},
        headers=_auth_header(manager_token),
    )
    # short_item is never received/transferred — emergency_stock_level stays 0.

    vitals_actor, vitals_token = await _create_and_login(
        api_client, real_session, "usage-atomic-vitals"
    )
    await grant_permission(vitals_actor, PERMISSION_INVENTORY_RECORD_USAGE)

    resp = await api_client.post(
        "/api/v1/inventory/usage",
        json={
            "items": [
                {"item_id": ok_item, "quantity": "5"},
                {"item_id": short_item, "quantity": "1"},
            ],
            "used_on": _TODAY,
            "manual_patient_name": "Atomic Batch Patient",
            "manual_patient_age": 33,
            "manual_patient_phone": "03001114444",
        },
        headers=_auth_header(vitals_token),
    )

    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "INSUFFICIENT_EMERGENCY_STOCK"

    ok_item_resp = await api_client.get(
        f"/api/v1/inventory/items/{ok_item}", headers=_auth_header(manager_token)
    )
    # Unchanged — the first line's decrement must not have survived the
    # second line's failure.
    assert ok_item_resp.json()["data"]["emergency_stock_level"] == "20.00"


async def test_record_usage_exceeding_emergency_stock_is_rejected(
    api_client, real_session, grant_permission
):
    actor, access_token = await _create_and_login(api_client, real_session, "over-usage")
    await grant_permission(actor, PERMISSION_INVENTORY_MANAGE)
    await grant_permission(actor, PERMISSION_INVENTORY_RECORD_USAGE)
    item_id = await _create_item(
        api_client, access_token, f"{TEST_INVENTORY_ITEM_NAME_PREFIX}OverUsage"
    )
    # No receipt/transfer at all — emergency_stock_level is 0.

    resp = await api_client.post(
        "/api/v1/inventory/usage",
        json={
            "items": [{"item_id": item_id, "quantity": "1"}],
            "used_on": _TODAY,
            "manual_patient_name": "Walk-in Patient",
            "manual_patient_age": 40,
            "manual_patient_phone": "03009876543",
        },
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "INSUFFICIENT_EMERGENCY_STOCK"


async def test_record_usage_rejects_both_patient_and_manual_fields(
    api_client, real_session, grant_permission
):
    actor, access_token = await _create_and_login(api_client, real_session, "usage-conflict")
    await grant_permission(actor, PERMISSION_INVENTORY_MANAGE)
    await grant_permission(actor, PERMISSION_INVENTORY_RECORD_USAGE)
    await grant_permission(actor, PERMISSION_PATIENTS_CREATE)
    item_id = await _create_item(
        api_client, access_token, f"{TEST_INVENTORY_ITEM_NAME_PREFIX}UsageConflict"
    )
    await api_client.post(
        f"/api/v1/inventory/items/{item_id}/receive",
        json={"quantity": "10", "received_on": _TODAY},
        headers=_auth_header(access_token),
    )
    await api_client.post(
        f"/api/v1/inventory/items/{item_id}/transfer",
        json={"quantity": "10", "transferred_on": _TODAY},
        headers=_auth_header(access_token),
    )
    patient_id = await _create_patient(
        api_client, access_token, f"{TEST_PATIENT_NAME_PREFIX}InventoryConflict"
    )

    resp = await api_client.post(
        "/api/v1/inventory/usage",
        json={
            "items": [{"item_id": item_id, "quantity": "1"}],
            "used_on": _TODAY,
            "patient_id": patient_id,
            "manual_patient_name": "Someone Else",
            "manual_patient_age": 22,
            "manual_patient_phone": "03001112223",
        },
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "INVENTORY_USAGE_MANUAL_PATIENT_CONFLICTS_WITH_PATIENT"


async def test_record_usage_rejects_incomplete_manual_fields(
    api_client, real_session, grant_permission
):
    actor, access_token = await _create_and_login(api_client, real_session, "usage-incomplete")
    await grant_permission(actor, PERMISSION_INVENTORY_MANAGE)
    await grant_permission(actor, PERMISSION_INVENTORY_RECORD_USAGE)
    item_id = await _create_item(
        api_client, access_token, f"{TEST_INVENTORY_ITEM_NAME_PREFIX}UsageIncomplete"
    )
    await api_client.post(
        f"/api/v1/inventory/items/{item_id}/receive",
        json={"quantity": "10", "received_on": _TODAY},
        headers=_auth_header(access_token),
    )
    await api_client.post(
        f"/api/v1/inventory/items/{item_id}/transfer",
        json={"quantity": "10", "transferred_on": _TODAY},
        headers=_auth_header(access_token),
    )

    resp = await api_client.post(
        "/api/v1/inventory/usage",
        json={
            "items": [{"item_id": item_id, "quantity": "1"}],
            "used_on": _TODAY,
            "manual_patient_name": "Half Filled",
        },
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "INVENTORY_USAGE_MANUAL_PATIENT_FIELDS_INCOMPLETE"


# ----------------------------------------------------------------------
# Restock request lifecycle
# ----------------------------------------------------------------------


async def test_fulfill_restock_request_transfers_stock_and_links_transfer(
    api_client, real_session, grant_permission
):
    manager, manager_token = await _create_and_login(api_client, real_session, "fulfill-flow")
    await grant_permission(manager, PERMISSION_INVENTORY_MANAGE)
    await grant_permission(manager, PERMISSION_INVENTORY_READ)
    item_id = await _create_item(
        api_client, manager_token, f"{TEST_INVENTORY_ITEM_NAME_PREFIX}FulfillFlow"
    )
    await api_client.post(
        f"/api/v1/inventory/items/{item_id}/receive",
        json={"quantity": "50", "received_on": _TODAY},
        headers=_auth_header(manager_token),
    )

    vitals_actor, vitals_token = await _create_and_login(
        api_client, real_session, "fulfill-flow-vitals"
    )
    await grant_permission(vitals_actor, PERMISSION_INVENTORY_REQUEST_RESTOCK)
    request_resp = await api_client.post(
        "/api/v1/inventory/requests",
        json={"item_id": item_id, "requested_quantity": "15", "note": "Running low tonight"},
        headers=_auth_header(vitals_token),
    )
    assert request_resp.status_code == 201, request_resp.text
    request_id = request_resp.json()["data"]["id"]
    assert request_resp.json()["data"]["status"] == "pending"

    fulfill_resp = await api_client.post(
        f"/api/v1/inventory/requests/{request_id}/fulfill",
        json={"transfer_quantity": "15", "transferred_on": _TODAY},
        headers=_auth_header(manager_token),
    )
    assert fulfill_resp.status_code == 200, fulfill_resp.text
    assert fulfill_resp.json()["data"]["status"] == "fulfilled"
    assert fulfill_resp.json()["data"]["fulfilled_by_transfer_id"] is not None

    item_resp = await api_client.get(
        f"/api/v1/inventory/items/{item_id}", headers=_auth_header(manager_token)
    )
    assert item_resp.json()["data"]["main_stock_level"] == "35.00"
    assert item_resp.json()["data"]["emergency_stock_level"] == "15.00"


async def test_fulfill_already_resolved_request_is_rejected(
    api_client, real_session, grant_permission
):
    manager, manager_token = await _create_and_login(api_client, real_session, "double-resolve")
    await grant_permission(manager, PERMISSION_INVENTORY_MANAGE)
    await grant_permission(manager, PERMISSION_INVENTORY_REQUEST_RESTOCK)
    item_id = await _create_item(
        api_client, manager_token, f"{TEST_INVENTORY_ITEM_NAME_PREFIX}DoubleResolve"
    )
    request_resp = await api_client.post(
        "/api/v1/inventory/requests",
        json={"item_id": item_id},
        headers=_auth_header(manager_token),
    )
    request_id = request_resp.json()["data"]["id"]

    reject_resp = await api_client.post(
        f"/api/v1/inventory/requests/{request_id}/reject",
        json={},
        headers=_auth_header(manager_token),
    )
    assert reject_resp.status_code == 200, reject_resp.text
    assert reject_resp.json()["data"]["status"] == "rejected"
    assert reject_resp.json()["data"]["rejection_reason"] is None

    second_reject_resp = await api_client.post(
        f"/api/v1/inventory/requests/{request_id}/reject",
        json={"rejection_reason": "Already handled"},
        headers=_auth_header(manager_token),
    )
    assert second_reject_resp.status_code == 409
    assert second_reject_resp.json()["error"]["code"] == "INVENTORY_RESTOCK_REQUEST_NOT_PENDING"


# ----------------------------------------------------------------------
# Low-stock computation
# ----------------------------------------------------------------------


async def test_is_low_stock_reflects_emergency_level_against_threshold(
    api_client, real_session, grant_permission
):
    actor, access_token = await _create_and_login(api_client, real_session, "low-stock")
    await grant_permission(actor, PERMISSION_INVENTORY_MANAGE)

    resp = await api_client.post(
        "/api/v1/inventory/items",
        json={
            "name": f"{TEST_INVENTORY_ITEM_NAME_PREFIX}LowStock",
            "category": "medicine",
            "unit": "piece",
            "low_stock_threshold": "5",
        },
        headers=_auth_header(access_token),
    )
    item_id = resp.json()["data"]["id"]
    assert resp.json()["data"]["is_low_stock"] is True  # 0 <= 5

    await api_client.post(
        f"/api/v1/inventory/items/{item_id}/receive",
        json={"quantity": "20", "received_on": _TODAY},
        headers=_auth_header(access_token),
    )
    transfer_resp = await api_client.post(
        f"/api/v1/inventory/items/{item_id}/transfer",
        json={"quantity": "10", "transferred_on": _TODAY},
        headers=_auth_header(access_token),
    )
    assert transfer_resp.json()["data"]["is_low_stock"] is False  # 10 > 5


# ----------------------------------------------------------------------
# Patient context lookup
# ----------------------------------------------------------------------


async def test_patient_context_has_no_visit_when_none_registered(
    api_client, real_session, grant_permission
):
    actor, access_token = await _create_and_login(api_client, real_session, "context-no-visit")
    await grant_permission(actor, PERMISSION_INVENTORY_READ)
    await grant_permission(actor, PERMISSION_PATIENTS_CREATE)
    patient_id = await _create_patient(
        api_client, access_token, f"{TEST_PATIENT_NAME_PREFIX}InventoryContextNoVisit"
    )

    resp = await api_client.get(
        f"/api/v1/inventory/patients/{patient_id}/context", headers=_auth_header(access_token)
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["patient_id"] == patient_id
    assert resp.json()["data"]["latest_visit"] is None


# ----------------------------------------------------------------------
# Print (step 6) — report-style A4 documents, HTML (browser handles
# Print/Save-as-PDF), never the 42mm receipt layout.
# ----------------------------------------------------------------------


async def test_print_history_log_requires_manage_permission(
    api_client, real_session, grant_permission
):
    """inventory:read alone (Vitals/Admin's shared visibility permission)
    must not be enough — this is a management-oversight document, gated
    the same as every write action on this module."""
    actor, access_token = await _create_and_login(api_client, real_session, "print-log-no-perm")
    await grant_permission(actor, PERMISSION_INVENTORY_READ)

    resp = await api_client.get(
        "/api/v1/inventory/history/print",
        params={"log_type": "usage"},
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 403


async def test_print_history_log_usage_contains_resolved_names(
    api_client, real_session, grant_permission
):
    """The one real regression risk this endpoint has: every id (item,
    patient, creator) must come back as a resolved display name, not a
    raw id or a crash — this is what a Playwright click-through against
    real data also confirmed visually, pinned here as a fast regression
    check."""
    actor, access_token = await _create_and_login(api_client, real_session, "print-log-usage")
    await grant_permission(actor, PERMISSION_INVENTORY_MANAGE)
    await grant_permission(actor, PERMISSION_INVENTORY_RECORD_USAGE)
    await grant_permission(actor, PERMISSION_PATIENTS_CREATE)
    item_id = await _create_item(
        api_client, access_token, f"{TEST_INVENTORY_ITEM_NAME_PREFIX}PrintLogUsage"
    )
    await api_client.post(
        f"/api/v1/inventory/items/{item_id}/receive",
        json={"quantity": "10", "received_on": _TODAY},
        headers=_auth_header(access_token),
    )
    await api_client.post(
        f"/api/v1/inventory/items/{item_id}/transfer",
        json={"quantity": "10", "transferred_on": _TODAY},
        headers=_auth_header(access_token),
    )
    patient_id = await _create_patient(
        api_client, access_token, f"{TEST_PATIENT_NAME_PREFIX}PrintLogUsage"
    )
    await api_client.post(
        "/api/v1/inventory/usage",
        json={
            "items": [
                {"item_id": item_id, "quantity": "3", "reason_note": "Print log regression check"}
            ],
            "used_on": _TODAY,
            "patient_id": patient_id,
        },
        headers=_auth_header(access_token),
    )

    resp = await api_client.get(
        "/api/v1/inventory/history/print",
        params={"log_type": "usage", "item_id": item_id},
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 200, resp.text
    body = resp.text
    assert f"{TEST_INVENTORY_ITEM_NAME_PREFIX}PrintLogUsage" in body
    assert f"{TEST_PATIENT_NAME_PREFIX}PrintLogUsage" in body
    assert "Print log regression check" in body
    assert actor.full_name in body  # "Recorded By"
    assert "Total Quantity" in body


async def test_print_history_log_receipt_type_uses_correct_title(
    api_client, real_session, grant_permission
):
    """log_type selects the title only (see render_inventory_history_log's
    own docstring) — pinning that "receipt" doesn't accidentally render
    the "usage"/"transfer" title, the one thing that's easy to get wrong
    in a function serving three cases from one title lookup."""
    actor, access_token = await _create_and_login(api_client, real_session, "print-log-receipt")
    await grant_permission(actor, PERMISSION_INVENTORY_MANAGE)

    resp = await api_client.get(
        "/api/v1/inventory/history/print",
        params={"log_type": "receipt"},
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 200, resp.text
    assert "Main Stock Receipt Log" in resp.text
    assert "Transfer to Emergency Stock Log" not in resp.text
    assert "Emergency Stock Usage Log" not in resp.text


async def test_print_daily_usage_slip_requires_record_usage_permission(
    api_client, real_session, grant_permission
):
    actor, access_token = await _create_and_login(api_client, real_session, "print-slip-no-perm")
    await grant_permission(actor, PERMISSION_INVENTORY_READ)

    resp = await api_client.get(
        "/api/v1/inventory/usage/mine/print",
        params={"date": _TODAY},
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 403


async def test_print_daily_usage_slip_is_scoped_to_the_calling_actor(
    api_client, real_session, grant_permission
):
    """The identical hard actor-scoping GET /inventory/usage/mine already
    established — a second Vitals staff member's own usage entry on the
    same item/day must never appear on this user's printed slip."""
    manager, manager_token = await _create_and_login(api_client, real_session, "print-slip-mgr")
    await grant_permission(manager, PERMISSION_INVENTORY_MANAGE)
    item_id = await _create_item(
        api_client, manager_token, f"{TEST_INVENTORY_ITEM_NAME_PREFIX}PrintSlipScoping"
    )
    await api_client.post(
        f"/api/v1/inventory/items/{item_id}/receive",
        json={"quantity": "10", "received_on": _TODAY},
        headers=_auth_header(manager_token),
    )
    await api_client.post(
        f"/api/v1/inventory/items/{item_id}/transfer",
        json={"quantity": "10", "transferred_on": _TODAY},
        headers=_auth_header(manager_token),
    )

    vitals_a, vitals_a_token = await _create_and_login(api_client, real_session, "print-slip-a")
    await grant_permission(vitals_a, PERMISSION_INVENTORY_RECORD_USAGE)
    vitals_b, vitals_b_token = await _create_and_login(api_client, real_session, "print-slip-b")
    await grant_permission(vitals_b, PERMISSION_INVENTORY_RECORD_USAGE)

    await api_client.post(
        "/api/v1/inventory/usage",
        json={
            "items": [{"item_id": item_id, "quantity": "1"}],
            "used_on": _TODAY,
            "manual_patient_name": "Slip A Patient",
            "manual_patient_age": 30,
            "manual_patient_phone": "03001112222",
        },
        headers=_auth_header(vitals_a_token),
    )
    await api_client.post(
        "/api/v1/inventory/usage",
        json={
            "items": [{"item_id": item_id, "quantity": "1"}],
            "used_on": _TODAY,
            "manual_patient_name": "Slip B Patient",
            "manual_patient_age": 31,
            "manual_patient_phone": "03001112223",
        },
        headers=_auth_header(vitals_b_token),
    )

    resp = await api_client.get(
        "/api/v1/inventory/usage/mine/print",
        params={"date": _TODAY},
        headers=_auth_header(vitals_a_token),
    )

    assert resp.status_code == 200, resp.text
    assert "Slip A Patient" in resp.text
    assert "Slip B Patient" not in resp.text
    assert vitals_a.full_name in resp.text  # "Vitals Staff:" header line

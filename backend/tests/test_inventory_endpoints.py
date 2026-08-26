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
        json={"item_id": item_id, "quantity": "1", "used_on": _TODAY},
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
            "item_id": item_id,
            "quantity": "6",
            "used_on": _TODAY,
            "patient_id": patient_id,
            "reason_note": "Post-op drip",
        },
        headers=_auth_header(vitals_token),
    )

    assert resp.status_code == 201, resp.text
    assert resp.json()["data"]["patient_id"] == patient_id
    assert resp.json()["data"]["reason_note"] == "Post-op drip"

    item_resp = await api_client.get(
        f"/api/v1/inventory/items/{item_id}", headers=_auth_header(manager_token)
    )
    assert item_resp.json()["data"]["emergency_stock_level"] == "14.00"


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
            "item_id": item_id,
            "quantity": "1",
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
            "item_id": item_id,
            "quantity": "1",
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
            "item_id": item_id,
            "quantity": "1",
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

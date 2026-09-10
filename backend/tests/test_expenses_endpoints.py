"""Full end-to-end HTTP tests for the Expense Tracking module — see
tests/test_pharmacy_endpoints.py's identical module docstring.

Covers the four things the feature's design hinges on: the expense date
is server-set to the current Asia/Karachi day (never client-suppliable,
never backdatable); edit/delete are owner-only (an explicit
`receptionist_id != actor.id` check, not just the router's permission
gate — the Aug-30 doctor-module audit finding) *and* same-day-only
(a 409 once the calendar day has rolled over); the admin breakdown is
accurate across more than one receptionist; and a logged expense flows
straight through to Net Revenue on `/reception/revenue` with no separate
recompute path. Soft-deleted expenses are excluded from every sum,
list, and breakdown.
"""

from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import text

from app.core.config import get_settings
from app.modules.auth.models import User, UserStatus
from app.modules.auth.password_service import PasswordService
from app.modules.auth.repository import UserRepository
from app.modules.expenses.constants import (
    PERMISSION_EXPENSES_LOG,
    PERMISSION_EXPENSES_READ_ALL,
)
from app.modules.reception.constants import PERMISSION_RECEPTION_REGISTER_VISIT
from tests.conftest import TEST_PATIENT_NAME_PREFIX, make_test_email

_PASSWORD = "Str0ng!Passw0rd#2026"


def _today_local() -> str:
    """The module's own authority on "today" — the current
    `settings.display_timezone` (Asia/Karachi) calendar day, matching
    ExpenseService.today_local exactly."""
    return datetime.now(ZoneInfo(get_settings().display_timezone)).date().isoformat()


async def _create_and_login(api_client, real_session, suffix: str) -> tuple[User, str]:
    password_hash = await PasswordService().hash(_PASSWORD)
    email = make_test_email(suffix)
    user = await UserRepository(real_session).add(
        User(
            email=email,
            password_hash=password_hash,
            full_name=f"Expense Actor {suffix}",
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


async def _log_expense(
    api_client,
    access_token: str,
    *,
    amount: str,
    reason: str = "Auto rickshaw for lab samples",
    recipient_name: str = "Bilal",
) -> dict:
    resp = await api_client.post(
        "/api/v1/expenses",
        json={"amount": amount, "reason": reason, "recipient_name": recipient_name},
        headers=_auth_header(access_token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]


def _new_patient_body(suffix: str) -> dict:
    return {
        "full_name": f"{TEST_PATIENT_NAME_PREFIX}ExpenseHttp{suffix}",
        "guardian_name": None,
        "gender": "female",
        "age_years": 33,
        "phone_number": "03001234567",
        "cnic": None,
        "address": None,
    }


# ----------------------------------------------------------------------
# Permission gating
# ----------------------------------------------------------------------


async def test_create_expense_requires_authentication(api_client):
    resp = await api_client.post(
        "/api/v1/expenses",
        json={"amount": "100.00", "reason": "x", "recipient_name": "y"},
    )
    assert resp.status_code == 401


async def test_create_expense_requires_expenses_log_permission(api_client, real_session):
    _actor, token = await _create_and_login(api_client, real_session, "exp-no-perm")
    resp = await api_client.post(
        "/api/v1/expenses",
        json={"amount": "100.00", "reason": "x", "recipient_name": "y"},
        headers=_auth_header(token),
    )
    assert resp.status_code == 403


async def test_expenses_log_only_actor_cannot_reach_admin_endpoints(
    api_client, real_session, grant_permission
):
    """`expenses:log` covers a receptionist's own petty-cash lifecycle
    only — the cross-receptionist list and the per-receptionist
    breakdown stay `expenses:read_all` (admin-only)."""
    actor, token = await _create_and_login(api_client, real_session, "exp-log-only")
    await grant_permission(actor, PERMISSION_EXPENSES_LOG)

    list_resp = await api_client.get("/api/v1/expenses", headers=_auth_header(token))
    stats_resp = await api_client.get("/api/v1/expenses/stats", headers=_auth_header(token))

    assert list_resp.status_code == 403
    assert stats_resp.status_code == 403


# ----------------------------------------------------------------------
# Create — server-set date & owner
# ----------------------------------------------------------------------


async def test_create_expense_sets_date_server_side_to_karachi_today_and_owner(
    api_client, real_session, grant_permission
):
    actor, token = await _create_and_login(api_client, real_session, "exp-create-ok")
    await grant_permission(actor, PERMISSION_EXPENSES_LOG)

    data = await _log_expense(api_client, token, amount="250.00", recipient_name="Courier")

    assert data["expense_date"] == _today_local()
    assert data["receptionist_id"] == str(actor.id)
    assert data["amount"] == "250.00"
    assert data["recipient_name"] == "Courier"


async def test_create_expense_rejects_blank_recipient_name(
    api_client, real_session, grant_permission
):
    actor, token = await _create_and_login(api_client, real_session, "exp-blank-recip")
    await grant_permission(actor, PERMISSION_EXPENSES_LOG)

    resp = await api_client.post(
        "/api/v1/expenses",
        json={"amount": "10.00", "reason": "ok", "recipient_name": "   "},
        headers=_auth_header(token),
    )
    assert resp.status_code == 422


async def test_create_expense_rejects_non_positive_amount(
    api_client, real_session, grant_permission
):
    actor, token = await _create_and_login(api_client, real_session, "exp-zero-amt")
    await grant_permission(actor, PERMISSION_EXPENSES_LOG)

    resp = await api_client.post(
        "/api/v1/expenses",
        json={"amount": "0", "reason": "ok", "recipient_name": "Someone"},
        headers=_auth_header(token),
    )
    assert resp.status_code == 422


# ----------------------------------------------------------------------
# Own-scoping & ownership enforcement
# ----------------------------------------------------------------------


async def test_list_mine_returns_only_the_callers_own_expenses(
    api_client, real_session, grant_permission
):
    r1, r1_token = await _create_and_login(api_client, real_session, "exp-mine-r1")
    r2, r2_token = await _create_and_login(api_client, real_session, "exp-mine-r2")
    await grant_permission(r1, PERMISSION_EXPENSES_LOG)
    await grant_permission(r2, PERMISSION_EXPENSES_LOG)

    await _log_expense(api_client, r1_token, amount="100.00", reason="r1 one")
    await _log_expense(api_client, r1_token, amount="200.00", reason="r1 two")
    await _log_expense(api_client, r2_token, amount="999.00", reason="r2 one")

    mine_resp = await api_client.get("/api/v1/expenses/mine", headers=_auth_header(r1_token))
    assert mine_resp.status_code == 200
    rows = mine_resp.json()["data"]
    assert len(rows) == 2
    assert {row["reason"] for row in rows} == {"r1 one", "r1 two"}
    assert all(row["receptionist_id"] == str(r1.id) for row in rows)


async def test_non_owner_cannot_update_or_delete_via_id_manipulation(
    api_client, real_session, grant_permission
):
    """A second receptionist holding `expenses:log` still cannot touch
    another receptionist's expense by passing its id — the service
    re-checks `receptionist_id == actor.id` and raises 403."""
    r1, r1_token = await _create_and_login(api_client, real_session, "exp-own-r1")
    r2, r2_token = await _create_and_login(api_client, real_session, "exp-own-r2")
    await grant_permission(r1, PERMISSION_EXPENSES_LOG)
    await grant_permission(r2, PERMISSION_EXPENSES_LOG)

    victim = await _log_expense(api_client, r1_token, amount="500.00", reason="r1 private")
    expense_id = victim["id"]

    patch_resp = await api_client.patch(
        f"/api/v1/expenses/{expense_id}",
        json={"amount": "1.00"},
        headers=_auth_header(r2_token),
    )
    delete_resp = await api_client.delete(
        f"/api/v1/expenses/{expense_id}", headers=_auth_header(r2_token)
    )

    assert patch_resp.status_code == 403
    assert delete_resp.status_code == 403

    # …and the row is untouched: still visible to, and unchanged for, r1.
    mine_resp = await api_client.get("/api/v1/expenses/mine", headers=_auth_header(r1_token))
    rows = mine_resp.json()["data"]
    assert len(rows) == 1
    assert rows[0]["amount"] == "500.00"


async def test_owner_can_update_own_expense_same_day(api_client, real_session, grant_permission):
    actor, token = await _create_and_login(api_client, real_session, "exp-update-ok")
    await grant_permission(actor, PERMISSION_EXPENSES_LOG)

    created = await _log_expense(
        api_client, token, amount="300.00", reason="old", recipient_name="A"
    )
    resp = await api_client.patch(
        f"/api/v1/expenses/{created['id']}",
        json={"amount": "325.50", "reason": "corrected", "recipient_name": "Aslam"},
        headers=_auth_header(token),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["amount"] == "325.50"
    assert data["reason"] == "corrected"
    assert data["recipient_name"] == "Aslam"


async def test_owner_can_delete_own_expense_same_day(api_client, real_session, grant_permission):
    actor, token = await _create_and_login(api_client, real_session, "exp-delete-ok")
    await grant_permission(actor, PERMISSION_EXPENSES_LOG)

    created = await _log_expense(api_client, token, amount="80.00")
    resp = await api_client.delete(f"/api/v1/expenses/{created['id']}", headers=_auth_header(token))
    assert resp.status_code == 200, resp.text

    mine_resp = await api_client.get("/api/v1/expenses/mine", headers=_auth_header(token))
    assert mine_resp.json()["data"] == []


# ----------------------------------------------------------------------
# Same-day-only lock (after the Karachi calendar day rolls over)
# ----------------------------------------------------------------------


async def test_edit_and_delete_are_locked_once_the_day_has_rolled_over(
    api_client, real_session, grant_permission
):
    """The API never accepts a past `expense_date`, so the rolled-over
    state is simulated by ageing the row directly in the DB. Both PATCH
    and DELETE must then come back 409 `EXPENSE_EDIT_WINDOW_CLOSED`
    (a state conflict — the caller still owns the row and holds the
    permission), not a bare 403."""
    actor, token = await _create_and_login(api_client, real_session, "exp-locked")
    await grant_permission(actor, PERMISSION_EXPENSES_LOG)

    created = await _log_expense(api_client, token, amount="120.00")
    yesterday = date.today() - timedelta(days=1)
    await real_session.execute(
        text("UPDATE expense SET expense_date = :d WHERE id = :id"),
        {"d": yesterday, "id": created["id"]},
    )
    await real_session.commit()

    patch_resp = await api_client.patch(
        f"/api/v1/expenses/{created['id']}",
        json={"amount": "1.00"},
        headers=_auth_header(token),
    )
    delete_resp = await api_client.delete(
        f"/api/v1/expenses/{created['id']}", headers=_auth_header(token)
    )

    assert patch_resp.status_code == 409, patch_resp.text
    assert patch_resp.json()["error"]["code"] == "EXPENSE_EDIT_WINDOW_CLOSED"
    assert delete_resp.status_code == 409, delete_resp.text
    assert delete_resp.json()["error"]["code"] == "EXPENSE_EDIT_WINDOW_CLOSED"


# ----------------------------------------------------------------------
# Decimal precision
# ----------------------------------------------------------------------


async def test_decimal_precision_is_preserved_through_write_and_read(
    api_client, real_session, grant_permission
):
    admin, admin_token = await _create_and_login(api_client, real_session, "exp-dec-admin")
    await grant_permission(admin, PERMISSION_EXPENSES_LOG)
    await grant_permission(admin, PERMISSION_EXPENSES_READ_ALL)

    await _log_expense(api_client, admin_token, amount="1234.56", reason="a")
    await _log_expense(api_client, admin_token, amount="78.90", reason="b")
    await _log_expense(api_client, admin_token, amount="0.05", reason="c")

    mine_resp = await api_client.get("/api/v1/expenses/mine", headers=_auth_header(admin_token))
    amounts = sorted(Decimal(row["amount"]) for row in mine_resp.json()["data"])
    assert amounts == [Decimal("0.05"), Decimal("78.90"), Decimal("1234.56")]

    stats_resp = await api_client.get("/api/v1/expenses/stats", headers=_auth_header(admin_token))
    body = stats_resp.json()["data"]
    assert body["grand_total"] == "1313.51"  # 1234.56 + 78.90 + 0.05, no float drift


# ----------------------------------------------------------------------
# Admin cross-receptionist breakdown
# ----------------------------------------------------------------------


async def test_admin_breakdown_is_accurate_across_multiple_receptionists(
    api_client, real_session, grant_permission
):
    r1, r1_token = await _create_and_login(api_client, real_session, "exp-bd-r1")
    r2, r2_token = await _create_and_login(api_client, real_session, "exp-bd-r2")
    admin, admin_token = await _create_and_login(api_client, real_session, "exp-bd-admin")
    await grant_permission(r1, PERMISSION_EXPENSES_LOG)
    await grant_permission(r2, PERMISSION_EXPENSES_LOG)
    await grant_permission(admin, PERMISSION_EXPENSES_READ_ALL)

    await _log_expense(api_client, r1_token, amount="100.00")
    await _log_expense(api_client, r1_token, amount="50.00")
    await _log_expense(api_client, r2_token, amount="200.00")

    stats_resp = await api_client.get("/api/v1/expenses/stats", headers=_auth_header(admin_token))
    assert stats_resp.status_code == 200, stats_resp.text
    body = stats_resp.json()["data"]

    assert body["date"] == _today_local()
    assert body["total_count"] == 3
    assert body["grand_total"] == "350.00"

    rows_by_id = {row["receptionist_id"]: row for row in body["rows"]}
    assert rows_by_id[str(r1.id)]["expense_count"] == 2
    assert rows_by_id[str(r1.id)]["total_amount"] == "150.00"
    assert rows_by_id[str(r1.id)]["receptionist_name"] == r1.full_name
    assert rows_by_id[str(r2.id)]["expense_count"] == 1
    assert rows_by_id[str(r2.id)]["total_amount"] == "200.00"


async def test_admin_list_can_be_filtered_to_one_receptionist(
    api_client, real_session, grant_permission
):
    r1, r1_token = await _create_and_login(api_client, real_session, "exp-filter-r1")
    r2, r2_token = await _create_and_login(api_client, real_session, "exp-filter-r2")
    admin, admin_token = await _create_and_login(api_client, real_session, "exp-filter-admin")
    await grant_permission(r1, PERMISSION_EXPENSES_LOG)
    await grant_permission(r2, PERMISSION_EXPENSES_LOG)
    await grant_permission(admin, PERMISSION_EXPENSES_READ_ALL)

    await _log_expense(api_client, r1_token, amount="10.00")
    await _log_expense(api_client, r1_token, amount="20.00")
    await _log_expense(api_client, r2_token, amount="30.00")

    resp = await api_client.get(
        "/api/v1/expenses",
        params={"receptionist_id": str(r2.id)},
        headers=_auth_header(admin_token),
    )
    assert resp.status_code == 200, resp.text
    rows = resp.json()["data"]
    assert len(rows) == 1
    assert rows[0]["receptionist_id"] == str(r2.id)
    assert rows[0]["amount"] == "30.00"


# ----------------------------------------------------------------------
# Soft-delete is excluded everywhere
# ----------------------------------------------------------------------


async def test_soft_deleted_expense_is_excluded_from_every_sum_and_list(
    api_client, real_session, grant_permission
):
    actor, token = await _create_and_login(api_client, real_session, "exp-softdel")
    await grant_permission(actor, PERMISSION_EXPENSES_LOG)
    await grant_permission(actor, PERMISSION_EXPENSES_READ_ALL)

    await _log_expense(api_client, token, amount="70.00", reason="keep")
    drop = await _log_expense(api_client, token, amount="30.00", reason="drop")
    delete_resp = await api_client.delete(
        f"/api/v1/expenses/{drop['id']}", headers=_auth_header(token)
    )
    assert delete_resp.status_code == 200

    mine_resp = await api_client.get("/api/v1/expenses/mine", headers=_auth_header(token))
    assert [row["reason"] for row in mine_resp.json()["data"]] == ["keep"]

    all_resp = await api_client.get("/api/v1/expenses", headers=_auth_header(token))
    assert [row["reason"] for row in all_resp.json()["data"]] == ["keep"]

    stats_resp = await api_client.get("/api/v1/expenses/stats", headers=_auth_header(token))
    stats = stats_resp.json()["data"]
    assert stats["total_count"] == 1
    assert stats["grand_total"] == "70.00"


# ----------------------------------------------------------------------
# Net Revenue arithmetic on /reception/revenue
# ----------------------------------------------------------------------


async def test_logged_expense_deducts_from_net_revenue_on_reception_revenue(
    api_client, real_session, grant_permission
):
    """The core design goal: an expense must actually reduce Net Revenue
    on the receptionist's own "My Revenue" view over the same rolling
    window as the revenue figures, with no separate recompute path."""
    actor, token = await _create_and_login(api_client, real_session, "exp-net-rev")
    await grant_permission(actor, PERMISSION_RECEPTION_REGISTER_VISIT)
    await grant_permission(actor, PERMISSION_EXPENSES_LOG)

    register_resp = await api_client.post(
        "/api/v1/reception/visits",
        json={
            "new_patient": _new_patient_body("NetRev"),
            "procedures": [{"name": "Consultation", "amount": "3000.00"}],
            "vitals_required": False,
            "initial_payment_amount": "0.01",
            "initial_payment_method": "cash",
            "discount_amount": "1000.00",
            "discount_reason": "Loyalty",
        },
        headers=_auth_header(token),
    )
    assert register_resp.status_code == 201, register_resp.text

    await _log_expense(api_client, token, amount="500.00", reason="Stationery")

    revenue_resp = await api_client.get("/api/v1/reception/revenue", headers=_auth_header(token))
    assert revenue_resp.status_code == 200
    body = revenue_resp.json()["data"]

    assert body["total_revenue"] == "2000.00"
    assert body["expense_count"] == 1
    assert body["total_expenses"] == "500.00"
    assert body["net_revenue"] == "1500.00"


async def test_deleting_an_expense_restores_net_revenue(api_client, real_session, grant_permission):
    actor, token = await _create_and_login(api_client, real_session, "exp-net-rev-del")
    await grant_permission(actor, PERMISSION_RECEPTION_REGISTER_VISIT)
    await grant_permission(actor, PERMISSION_EXPENSES_LOG)

    await api_client.post(
        "/api/v1/reception/visits",
        json={
            "new_patient": _new_patient_body("NetRevDel"),
            "procedures": [{"name": "Consultation", "amount": "1500.00"}],
            "vitals_required": False,
            "initial_payment_amount": "0.01",
            "initial_payment_method": "cash",
        },
        headers=_auth_header(token),
    )
    created = await _log_expense(api_client, token, amount="400.00")

    after_log = (
        await api_client.get("/api/v1/reception/revenue", headers=_auth_header(token))
    ).json()["data"]
    assert after_log["net_revenue"] == "1100.00"

    await api_client.delete(f"/api/v1/expenses/{created['id']}", headers=_auth_header(token))

    after_delete = (
        await api_client.get("/api/v1/reception/revenue", headers=_auth_header(token))
    ).json()["data"]
    assert after_delete["expense_count"] == 0
    assert after_delete["total_expenses"] == "0.00"
    assert after_delete["net_revenue"] == "1500.00"

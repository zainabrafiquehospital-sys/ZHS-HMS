"""Full end-to-end HTTP tests for the Visit module's read-only endpoints
— see tests/test_patients_endpoints.py's identical module docstring."""

from decimal import Decimal

from uuid6 import uuid7

from app.modules.auth.models import User, UserStatus
from app.modules.auth.password_service import PasswordService
from app.modules.auth.repository import UserRepository
from app.modules.patients.models import PatientGender
from app.modules.visits.constants import (
    PERMISSION_PROCEDURES_MANAGE,
    PERMISSION_PROCEDURES_READ,
    PERMISSION_VISITS_READ,
)
from app.shared.payment_method import PaymentMethod
from tests.conftest import TEST_PATIENT_NAME_PREFIX, TEST_PROCEDURE_NAME_PREFIX, make_test_email

_PASSWORD = "Str0ng!Passw0rd#2026"


async def _create_and_login(api_client, real_session, suffix: str) -> tuple[User, str]:
    password_hash = await PasswordService().hash(_PASSWORD)
    email = make_test_email(suffix)
    user = await UserRepository(real_session).add(
        User(
            email=email,
            password_hash=password_hash,
            full_name="Visit Endpoint Actor",
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


async def test_list_visits_requires_authentication(api_client):
    resp = await api_client.get("/api/v1/visits")
    assert resp.status_code == 401


async def test_get_visit_returns_404_for_unknown_id(api_client, real_session, grant_permission):
    actor, access_token = await _create_and_login(api_client, real_session, "get-visit-404")
    await grant_permission(actor, PERMISSION_VISITS_READ)

    resp = await api_client.get(f"/api/v1/visits/{uuid7()}", headers=_auth_header(access_token))

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "VISIT_NOT_FOUND"


async def test_get_visit_returns_registered_visit(
    api_client, real_session, grant_permission, patient_service, visit_service
):
    actor, access_token = await _create_and_login(api_client, real_session, "get-visit-success")
    await grant_permission(actor, PERMISSION_VISITS_READ)
    patient = await patient_service.register_patient(
        actor=actor,
        full_name=f"{TEST_PATIENT_NAME_PREFIX}VisitEndpoint",
        guardian_name=None,
        gender=PatientGender.FEMALE,
        age_years=25,
        phone_number="03001234567",
        cnic=None,
        address=None,
    )
    visit = await visit_service.register_visit(
        actor=actor,
        patient_id=patient.id,
        doctor_user_id=actor.id,
        procedures=[(None, "Consultation", Decimal("1500.00"))],
        vitals_required=False,
        initial_payment_amount=Decimal("0.01"),
        initial_payment_method=PaymentMethod.CASH,
    )

    resp = await api_client.get(f"/api/v1/visits/{visit.id}", headers=_auth_header(access_token))

    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["queue_token"] == visit.queue_token
    assert body["status"] == "waiting_doctor"


async def test_get_visit_stats_by_creator_requires_permission(api_client, real_session):
    _actor, access_token = await _create_and_login(api_client, real_session, "stats-no-perm")

    resp = await api_client.get(
        "/api/v1/visits/stats/by-creator", headers=_auth_header(access_token)
    )

    assert resp.status_code == 403


async def test_get_visit_stats_by_creator_returns_accurate_counts(
    api_client, real_session, grant_permission, patient_service, visit_service
):
    actor, access_token = await _create_and_login(api_client, real_session, "stats-correctness")
    await grant_permission(actor, PERMISSION_VISITS_READ)
    patient = await patient_service.register_patient(
        actor=actor,
        full_name=f"{TEST_PATIENT_NAME_PREFIX}VisitStats",
        guardian_name=None,
        gender=PatientGender.FEMALE,
        age_years=28,
        phone_number="03001234567",
        cnic=None,
        address=None,
    )
    for _ in range(3):
        await visit_service.register_visit(
            actor=actor,
            patient_id=patient.id,
            doctor_user_id=actor.id,
            procedures=[(None, "Consultation", Decimal("1500.00"))],
            vitals_required=False,
            initial_payment_amount=Decimal("0.01"),
            initial_payment_method=PaymentMethod.CASH,
        )

    resp = await api_client.get(
        "/api/v1/visits/stats/by-creator", headers=_auth_header(access_token)
    )

    assert resp.status_code == 200
    rows = {row["user_id"]: row["count"] for row in resp.json()["data"]}
    assert rows[str(actor.id)] == 3


async def test_list_visits_filters_by_patient_id_and_returns_pagination_meta(
    api_client, real_session, grant_permission, patient_service, visit_service
):
    actor, access_token = await _create_and_login(api_client, real_session, "list-visits")
    await grant_permission(actor, PERMISSION_VISITS_READ)
    patient = await patient_service.register_patient(
        actor=actor,
        full_name=f"{TEST_PATIENT_NAME_PREFIX}VisitList",
        guardian_name=None,
        gender=PatientGender.FEMALE,
        age_years=31,
        phone_number="03001234567",
        cnic=None,
        address=None,
    )
    other_patient = await patient_service.register_patient(
        actor=actor,
        full_name=f"{TEST_PATIENT_NAME_PREFIX}VisitListOther",
        guardian_name=None,
        gender=PatientGender.FEMALE,
        age_years=31,
        phone_number="03001234567",
        cnic=None,
        address=None,
    )
    visit = await visit_service.register_visit(
        actor=actor,
        patient_id=patient.id,
        doctor_user_id=actor.id,
        procedures=[(None, "Consultation", Decimal("1500.00"))],
        vitals_required=False,
        initial_payment_amount=Decimal("0.01"),
        initial_payment_method=PaymentMethod.CASH,
    )
    await visit_service.register_visit(
        actor=actor,
        patient_id=other_patient.id,
        doctor_user_id=actor.id,
        procedures=[(None, "Consultation", Decimal("1500.00"))],
        vitals_required=False,
        initial_payment_amount=Decimal("0.01"),
        initial_payment_method=PaymentMethod.CASH,
    )

    resp = await api_client.get(
        "/api/v1/visits",
        params={"page": 1, "page_size": 10, "patient_id": str(patient.id)},
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["meta"]["total"] == 1
    assert body["data"][0]["id"] == str(visit.id)


# ---------------------------------------------------------------------
# Itemized procedures (2026-08-21 addition) — VisitOut.procedure_items,
# both the single-visit (GET /visits/{id}) and batched (GET /visits)
# forms. A legacy visit's empty procedure_items list is already
# implicitly covered above (test_get_visit_returns_registered_visit /
# test_list_visits_filters_by_patient_id_and_returns_pagination_meta
# both register via the old (None, name, amount) tuple shape, which
# still produces a real VisitProcedureItem row per the current
# register_visit contract — see that method's own docstring: every
# visit registered through it is itemized, regardless of whether the
# item is catalog-linked or manual).
# ---------------------------------------------------------------------


async def test_get_visit_includes_its_procedure_items(
    api_client, real_session, grant_permission, patient_service, visit_service
):
    actor, access_token = await _create_and_login(api_client, real_session, "get-visit-items")
    await grant_permission(actor, PERMISSION_VISITS_READ)
    patient = await patient_service.register_patient(
        actor=actor,
        full_name=f"{TEST_PATIENT_NAME_PREFIX}VisitItems",
        guardian_name=None,
        gender=PatientGender.FEMALE,
        age_years=29,
        phone_number="03001234567",
        cnic=None,
        address=None,
    )
    visit = await visit_service.register_visit(
        actor=actor,
        patient_id=patient.id,
        doctor_user_id=actor.id,
        procedures=[
            (None, "Checkup", Decimal("800.00")),
            (None, "Scan", Decimal("700.00")),
        ],
        vitals_required=False,
        initial_payment_amount=Decimal("0.01"),
        initial_payment_method=PaymentMethod.CASH,
    )

    resp = await api_client.get(f"/api/v1/visits/{visit.id}", headers=_auth_header(access_token))

    assert resp.status_code == 200
    items = resp.json()["data"]["procedure_items"]
    assert len(items) == 2
    assert {item["name"] for item in items} == {"Checkup", "Scan"}
    assert {item["amount"] for item in items} == {"800.00", "700.00"}


async def test_list_visits_includes_procedure_items_for_every_row(
    api_client, real_session, grant_permission, patient_service, visit_service
):
    """The batched form (`GET /visits`'s list response) — proves the
    N+1-avoidance batching actually attaches the right items to the
    right row, not just to whichever visit happened to be created
    first."""
    actor, access_token = await _create_and_login(api_client, real_session, "list-visits-items")
    await grant_permission(actor, PERMISSION_VISITS_READ)
    patient = await patient_service.register_patient(
        actor=actor,
        full_name=f"{TEST_PATIENT_NAME_PREFIX}VisitListItemsA",
        guardian_name=None,
        gender=PatientGender.FEMALE,
        age_years=31,
        phone_number="03001234567",
        cnic=None,
        address=None,
    )
    other_patient = await patient_service.register_patient(
        actor=actor,
        full_name=f"{TEST_PATIENT_NAME_PREFIX}VisitListItemsB",
        guardian_name=None,
        gender=PatientGender.FEMALE,
        age_years=31,
        phone_number="03001234567",
        cnic=None,
        address=None,
    )
    visit_a = await visit_service.register_visit(
        actor=actor,
        patient_id=patient.id,
        doctor_user_id=actor.id,
        procedures=[(None, "Checkup", Decimal("800.00"))],
        vitals_required=False,
        initial_payment_amount=Decimal("0.01"),
        initial_payment_method=PaymentMethod.CASH,
    )
    visit_b = await visit_service.register_visit(
        actor=actor,
        patient_id=other_patient.id,
        doctor_user_id=actor.id,
        procedures=[(None, "Scan", Decimal("700.00"))],
        vitals_required=False,
        initial_payment_amount=Decimal("0.01"),
        initial_payment_method=PaymentMethod.CASH,
    )

    resp = await api_client.get(
        "/api/v1/visits",
        params={"page": 1, "page_size": 10, "sort_by": "created_at", "sort_order": "asc"},
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 200
    rows_by_id = {row["id"]: row for row in resp.json()["data"]}
    assert rows_by_id[str(visit_a.id)]["procedure_items"][0]["name"] == "Checkup"
    assert rows_by_id[str(visit_b.id)]["procedure_items"][0]["name"] == "Scan"


# ---------------------------------------------------------------------
# Procedure catalog (2026-08-21 addition) — mirrors
# tests/test_pharmacy_endpoints.py's Medicine-catalog test shape as
# closely as makes sense; see app/modules/visits/constants.py's own
# docstring for the single procedures:manage permission covering
# create/update/delete, and procedures:read gating search only.
# ---------------------------------------------------------------------


async def test_create_procedure_requires_permission(api_client, real_session):
    _actor, access_token = await _create_and_login(api_client, real_session, "create-proc-no-perm")

    resp = await api_client.post(
        "/api/v1/visits/procedures",
        json={"name": f"{TEST_PROCEDURE_NAME_PREFIX}NoPerm", "price": "500.00"},
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "PERMISSION_DENIED"


async def test_create_procedure_success(api_client, real_session, grant_permission):
    actor, access_token = await _create_and_login(api_client, real_session, "create-proc")
    await grant_permission(actor, PERMISSION_PROCEDURES_MANAGE)

    resp = await api_client.post(
        "/api/v1/visits/procedures",
        json={"name": f"{TEST_PROCEDURE_NAME_PREFIX}Checkup", "price": "800.00"},
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 201, resp.text
    body = resp.json()["data"]
    assert body["name"] == f"{TEST_PROCEDURE_NAME_PREFIX}Checkup"
    assert body["price"] == "800.00"
    assert body["is_active"] is True


async def test_list_procedures_requires_permission(api_client, real_session):
    _actor, access_token = await _create_and_login(api_client, real_session, "list-proc-no-perm")

    resp = await api_client.get("/api/v1/visits/procedures", headers=_auth_header(access_token))

    assert resp.status_code == 403


async def test_search_procedures_requires_permission(api_client, real_session):
    _actor, access_token = await _create_and_login(api_client, real_session, "search-proc-no-perm")

    resp = await api_client.get(
        "/api/v1/visits/procedures/search",
        params={"search": "Checkup"},
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 403


async def test_search_procedures_finds_only_active_ones(api_client, real_session, grant_permission):
    actor, access_token = await _create_and_login(api_client, real_session, "search-proc")
    await grant_permission(actor, PERMISSION_PROCEDURES_MANAGE)
    await grant_permission(actor, PERMISSION_PROCEDURES_READ)
    create_resp = await api_client.post(
        "/api/v1/visits/procedures",
        json={"name": f"{TEST_PROCEDURE_NAME_PREFIX}SearchActive", "price": "600.00"},
        headers=_auth_header(access_token),
    )
    inactive_resp = await api_client.post(
        "/api/v1/visits/procedures",
        json={"name": f"{TEST_PROCEDURE_NAME_PREFIX}SearchInactive", "price": "600.00"},
        headers=_auth_header(access_token),
    )
    inactive_id = inactive_resp.json()["data"]["id"]
    await api_client.patch(
        f"/api/v1/visits/procedures/{inactive_id}",
        json={"is_active": False},
        headers=_auth_header(access_token),
    )

    resp = await api_client.get(
        "/api/v1/visits/procedures/search",
        params={"search": f"{TEST_PROCEDURE_NAME_PREFIX}Search"},
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 200
    names = {row["name"] for row in resp.json()["data"]}
    assert f"{TEST_PROCEDURE_NAME_PREFIX}SearchActive" in names
    assert f"{TEST_PROCEDURE_NAME_PREFIX}SearchInactive" not in names
    assert create_resp.status_code == 201  # sanity: the active one really was created


async def test_update_procedure_toggles_active(api_client, real_session, grant_permission):
    actor, access_token = await _create_and_login(api_client, real_session, "update-proc")
    await grant_permission(actor, PERMISSION_PROCEDURES_MANAGE)
    create_resp = await api_client.post(
        "/api/v1/visits/procedures",
        json={"name": f"{TEST_PROCEDURE_NAME_PREFIX}Toggle", "price": "600.00"},
        headers=_auth_header(access_token),
    )
    procedure_id = create_resp.json()["data"]["id"]

    resp = await api_client.patch(
        f"/api/v1/visits/procedures/{procedure_id}",
        json={"is_active": False, "price": "650.00"},
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["is_active"] is False
    assert body["price"] == "650.00"
    assert body["name"] == f"{TEST_PROCEDURE_NAME_PREFIX}Toggle"  # untouched field survives


async def test_delete_procedure_removes_it_from_the_catalog_listing(
    api_client, real_session, grant_permission
):
    """Unlike Medicine (activate/deactivate only), the procedure catalog
    also supports a genuine delete — see app/modules/visits/models.py's
    `Procedure` docstring for why this is safe regardless of whether the
    procedure has ever been selected for a visit."""
    actor, access_token = await _create_and_login(api_client, real_session, "delete-proc")
    await grant_permission(actor, PERMISSION_PROCEDURES_MANAGE)
    create_resp = await api_client.post(
        "/api/v1/visits/procedures",
        json={"name": f"{TEST_PROCEDURE_NAME_PREFIX}Delete", "price": "600.00"},
        headers=_auth_header(access_token),
    )
    procedure_id = create_resp.json()["data"]["id"]

    delete_resp = await api_client.delete(
        f"/api/v1/visits/procedures/{procedure_id}", headers=_auth_header(access_token)
    )
    assert delete_resp.status_code == 200

    list_resp = await api_client.get(
        "/api/v1/visits/procedures",
        params={"search": f"{TEST_PROCEDURE_NAME_PREFIX}Delete"},
        headers=_auth_header(access_token),
    )
    assert list_resp.json()["data"] == []


async def test_delete_procedure_requires_permission(api_client, real_session, grant_permission):
    actor, access_token = await _create_and_login(api_client, real_session, "delete-proc-no-perm")
    await grant_permission(actor, PERMISSION_PROCEDURES_MANAGE)
    create_resp = await api_client.post(
        "/api/v1/visits/procedures",
        json={"name": f"{TEST_PROCEDURE_NAME_PREFIX}DeleteNoPerm", "price": "600.00"},
        headers=_auth_header(access_token),
    )
    procedure_id = create_resp.json()["data"]["id"]

    other_actor, other_token = await _create_and_login(
        api_client, real_session, "delete-proc-no-perm-2"
    )

    resp = await api_client.delete(
        f"/api/v1/visits/procedures/{procedure_id}", headers=_auth_header(other_token)
    )

    assert resp.status_code == 403

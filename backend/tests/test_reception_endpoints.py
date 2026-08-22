"""Full end-to-end HTTP tests for the Reception module — see
tests/test_patients_endpoints.py's identical module docstring."""

from decimal import Decimal

from app.modules.auth.models import User, UserStatus
from app.modules.auth.password_service import PasswordService
from app.modules.auth.repository import UserRepository
from app.modules.consultation.constants import PERMISSION_CONSULTATION_START
from app.modules.reception.constants import (
    PERMISSION_RECEPTION_CANCEL_VISIT,
    PERMISSION_RECEPTION_CLEAR_OWN_REVENUE,
    PERMISSION_RECEPTION_DELETE_VISIT,
    PERMISSION_RECEPTION_REGISTER_VISIT,
    PERMISSION_RECEPTION_UPDATE_VISIT,
)
from app.modules.visits.constants import (
    PERMISSION_PROCEDURES_MANAGE,
    PERMISSION_VISITS_READ,
)
from app.modules.visits.models import Visit, VisitStatus
from app.modules.visits.repository import VisitRepository
from tests.conftest import TEST_PATIENT_NAME_PREFIX, TEST_PROCEDURE_NAME_PREFIX, make_test_email

_PASSWORD = "Str0ng!Passw0rd#2026"


async def _create_and_login(api_client, real_session, suffix: str) -> tuple[User, str]:
    password_hash = await PasswordService().hash(_PASSWORD)
    email = make_test_email(suffix)
    user = await UserRepository(real_session).add(
        User(
            email=email,
            password_hash=password_hash,
            full_name="Reception Endpoint Actor",
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


def _new_patient_body(suffix: str) -> dict:
    return {
        "full_name": f"{TEST_PATIENT_NAME_PREFIX}ReceptionHttp{suffix}",
        "guardian_name": None,
        "gender": "female",
        "age_years": 36,
        "phone_number": "03001234567",
        "cnic": None,
        "address": None,
    }


async def test_register_visit_requires_authentication(api_client):
    resp = await api_client.post("/api/v1/reception/visits", json={})
    assert resp.status_code == 401


async def test_register_visit_without_permission_is_forbidden(api_client, real_session):
    actor, access_token = await _create_and_login(api_client, real_session, "no-perm-register")

    resp = await api_client.post(
        "/api/v1/reception/visits",
        json={
            "new_patient": _new_patient_body("NoPerm"),
            "procedures": [{"name": "Consultation", "amount": "1500.00"}],
            "vitals_required": True,
            "initial_payment_amount": "0.01",
            "initial_payment_method": "cash",
        },
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 403


async def test_register_visit_both_patient_id_and_new_patient_returns_422(
    api_client, real_session, grant_permission
):
    actor, access_token = await _create_and_login(api_client, real_session, "both-sources")
    await grant_permission(actor, PERMISSION_RECEPTION_REGISTER_VISIT)

    resp = await api_client.post(
        "/api/v1/reception/visits",
        json={
            "patient_id": str(actor.id),
            "new_patient": _new_patient_body("Both"),
            "procedures": [{"name": "Consultation", "amount": "1500.00"}],
            "vitals_required": True,
            "initial_payment_amount": "0.01",
            "initial_payment_method": "cash",
        },
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 422


async def test_register_visit_success_with_new_patient(api_client, real_session, grant_permission):
    actor, access_token = await _create_and_login(api_client, real_session, "register-success")
    await grant_permission(actor, PERMISSION_RECEPTION_REGISTER_VISIT)

    resp = await api_client.post(
        "/api/v1/reception/visits",
        json={
            "new_patient": _new_patient_body("Success"),
            "procedures": [{"name": "Consultation", "amount": "1500.00"}],
            "vitals_required": True,
            "initial_payment_amount": "0.01",
            "initial_payment_method": "cash",
        },
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 201
    body = resp.json()["data"]
    assert body["patient"]["mr_number"].startswith("MR-")
    assert body["visit"]["status"] == "waiting_vitals"
    assert body["queue_entry"]["destination"] == "vitals"
    assert body["queue_entry"]["status"] == "waiting"


async def test_register_visit_auto_assigns_online_doctor(
    api_client, real_session, grant_permission
):
    """Phase 6 fast-registration §4 over real HTTP: no `doctor_user_id`
    field exists in the request at all — a currently logged-in,
    `consultation:start`-holding doctor must be auto-assigned."""
    receptionist, receptionist_token = await _create_and_login(
        api_client, real_session, "auto-assign-receptionist"
    )
    await grant_permission(receptionist, PERMISSION_RECEPTION_REGISTER_VISIT)
    doctor, _doctor_token = await _create_and_login(api_client, real_session, "auto-assign-doctor")
    await grant_permission(doctor, PERMISSION_CONSULTATION_START)

    resp = await api_client.post(
        "/api/v1/reception/visits",
        json={
            "new_patient": _new_patient_body("AutoAssign"),
            "procedures": [{"name": "Consultation", "amount": "1500.00"}],
            "vitals_required": False,
            "initial_payment_amount": "0.01",
            "initial_payment_method": "cash",
        },
        headers=_auth_header(receptionist_token),
    )

    assert resp.status_code == 201
    assert resp.json()["data"]["visit"]["doctor_user_id"] == str(doctor.id)


async def test_register_visit_leaves_unassigned_without_online_doctor(
    api_client, real_session, grant_permission
):
    """The other half of Phase 6 fast-registration §4: with no eligible
    online doctor, registration still succeeds and the Visit is simply
    unassigned rather than the request being blocked or erroring."""
    receptionist, access_token = await _create_and_login(
        api_client, real_session, "no-doctor-receptionist"
    )
    await grant_permission(receptionist, PERMISSION_RECEPTION_REGISTER_VISIT)

    resp = await api_client.post(
        "/api/v1/reception/visits",
        json={
            "new_patient": _new_patient_body("NoDoctorOnline"),
            "procedures": [{"name": "Consultation", "amount": "1500.00"}],
            "vitals_required": False,
            "initial_payment_amount": "0.01",
            "initial_payment_method": "cash",
        },
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 201
    assert resp.json()["data"]["visit"]["doctor_user_id"] is None


async def test_print_registration_slip_success(api_client, real_session, grant_permission):
    actor, access_token = await _create_and_login(api_client, real_session, "print-slip-success")
    await grant_permission(actor, PERMISSION_RECEPTION_REGISTER_VISIT)
    register_resp = await api_client.post(
        "/api/v1/reception/visits",
        json={
            "new_patient": _new_patient_body("PrintSlip"),
            "procedures": [{"name": "Consultation", "amount": "1500.00"}],
            "vitals_required": False,
            "initial_payment_amount": "0.01",
            "initial_payment_method": "cash",
        },
        headers=_auth_header(access_token),
    )
    visit_id = register_resp.json()["data"]["visit"]["id"]
    mr_number = register_resp.json()["data"]["patient"]["mr_number"]

    resp = await api_client.get(
        f"/api/v1/reception/visits/{visit_id}/slip/print", headers=_auth_header(access_token)
    )

    assert resp.status_code == 200
    assert mr_number in resp.text
    assert "Consultation" in resp.text
    # The attending doctor is intentionally omitted from this slip design
    # (see app/shared/printing/service.py's render_registration_slip
    # docstring) — assert its absence rather than presence.
    assert "Doctor" not in resp.text


async def test_print_registration_slip_requires_permission(api_client, real_session):
    _actor, access_token = await _create_and_login(api_client, real_session, "print-slip-no-perm")

    resp = await api_client.get(
        "/api/v1/reception/visits/00000000-0000-0000-0000-000000000000/slip/print",
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 403


# ---------------------------------------------------------------------
# Registration-time discount (2026-08-19 addition) — an optional flat
# discount off `amount`, applied directly on the Register Visit form.
# `Visit.amount` ends up already post-discount, so this section also
# proves the design goal: the discount flows through to "My Revenue"
# automatically, with no extra code path — see VisitService.
# register_visit's own docstring for the full mechanism.
# ---------------------------------------------------------------------


async def test_register_visit_with_discount_computes_post_discount_amount(
    api_client, real_session, grant_permission
):
    actor, access_token = await _create_and_login(api_client, real_session, "discount-basic")
    await grant_permission(actor, PERMISSION_RECEPTION_REGISTER_VISIT)

    resp = await api_client.post(
        "/api/v1/reception/visits",
        json={
            "new_patient": _new_patient_body("DiscountBasic"),
            "procedures": [{"name": "Consultation", "amount": "2000.00"}],
            "vitals_required": False,
            "initial_payment_amount": "0.01",
            "initial_payment_method": "cash",
            "discount_amount": "500.00",
            "discount_reason": "Referral",
        },
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 201, resp.text
    visit = resp.json()["data"]["visit"]
    assert visit["amount"] == "1500.00"
    assert visit["discount_amount"] == "500.00"
    assert visit["discount_reason"] == "Referral"


async def test_register_visit_discount_reason_is_optional(api_client, real_session, grant_permission):
    actor, access_token = await _create_and_login(api_client, real_session, "discount-no-reason")
    await grant_permission(actor, PERMISSION_RECEPTION_REGISTER_VISIT)

    resp = await api_client.post(
        "/api/v1/reception/visits",
        json={
            "new_patient": _new_patient_body("DiscountNoReason"),
            "procedures": [{"name": "Consultation", "amount": "1000.00"}],
            "vitals_required": False,
            "initial_payment_amount": "0.01",
            "initial_payment_method": "cash",
            "discount_amount": "100.00",
        },
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 201, resp.text
    visit = resp.json()["data"]["visit"]
    assert visit["amount"] == "900.00"
    assert visit["discount_reason"] is None


async def test_register_visit_discount_exceeding_amount_rejected(
    api_client, real_session, grant_permission
):
    actor, access_token = await _create_and_login(api_client, real_session, "discount-exceeds")
    await grant_permission(actor, PERMISSION_RECEPTION_REGISTER_VISIT)

    resp = await api_client.post(
        "/api/v1/reception/visits",
        json={
            "new_patient": _new_patient_body("DiscountExceeds"),
            "procedures": [{"name": "Consultation", "amount": "500.00"}],
            "vitals_required": False,
            "initial_payment_amount": "0.01",
            "initial_payment_method": "cash",
            "discount_amount": "500.01",
        },
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VISIT_DISCOUNT_EXCEEDS_AMOUNT"


async def test_print_registration_slip_with_discount_shows_lines_in_correct_order(
    api_client, real_session, grant_permission
):
    """The printed slip must show, in order: the original (pre-discount)
    amount, then the Discount line, then the final Net Amount."""
    actor, access_token = await _create_and_login(api_client, real_session, "discount-print-order")
    await grant_permission(actor, PERMISSION_RECEPTION_REGISTER_VISIT)

    register_resp = await api_client.post(
        "/api/v1/reception/visits",
        json={
            "new_patient": _new_patient_body("DiscountPrintOrder"),
            "procedures": [{"name": "Consultation", "amount": "2000.00"}],
            "vitals_required": False,
            "initial_payment_amount": "0.01",
            "initial_payment_method": "cash",
            "discount_amount": "300.00",
            "discount_reason": "Staff discount",
        },
        headers=_auth_header(access_token),
    )
    assert register_resp.status_code == 201, register_resp.text
    visit_id = register_resp.json()["data"]["visit"]["id"]

    resp = await api_client.get(
        f"/api/v1/reception/visits/{visit_id}/slip/print", headers=_auth_header(access_token)
    )
    assert resp.status_code == 200
    html = resp.text
    assert "2,000.00" in html
    assert "Discount (Staff discount)" in html
    assert "1,700.00" in html

    amount_idx = html.index(">Amount<")
    discount_idx = html.index("Discount (Staff discount)")
    net_idx = html.index("Net Amount")
    assert amount_idx < discount_idx < net_idx


async def test_print_registration_slip_without_discount_omits_discount_line(
    api_client, real_session, grant_permission
):
    actor, access_token = await _create_and_login(api_client, real_session, "no-discount-print")
    await grant_permission(actor, PERMISSION_RECEPTION_REGISTER_VISIT)

    register_resp = await api_client.post(
        "/api/v1/reception/visits",
        json={
            "new_patient": _new_patient_body("PlainPrintSlip"),
            "procedures": [{"name": "Consultation", "amount": "800.00"}],
            "vitals_required": False,
            "initial_payment_amount": "0.01",
            "initial_payment_method": "cash",
        },
        headers=_auth_header(access_token),
    )
    visit_id = register_resp.json()["data"]["visit"]["id"]

    resp = await api_client.get(
        f"/api/v1/reception/visits/{visit_id}/slip/print", headers=_auth_header(access_token)
    )
    assert resp.status_code == 200
    assert "Discount" not in resp.text
    # This visit is always itemized (2026-08-21 addition) — the itemized
    # table's tfoot always shows both "Total Amount" and "Net Amount"
    # rows regardless of discount, exactly mirroring
    # render_medicine_bill_receipt's/render_invoice_receipt's identical
    # always-shown convention (see render_registration_slip's own
    # docstring) — unlike the legacy row-based layout (still exercised
    # directly in test_printing_service.py), which only added a Net
    # Amount row once a discount actually applied.
    assert "Net Amount" in resp.text
    assert "Total Amount" in resp.text


async def test_register_visit_discount_flows_through_to_my_revenue(
    api_client, real_session, grant_permission
):
    """The core design goal: a registration-time discount must actually
    reduce what "My Revenue" reports, not just be a cosmetic field on
    the printed slip — proves Visit.amount being stored already
    post-discount is what makes this automatic, with no separate
    revenue-recompute logic anywhere."""
    actor, access_token = await _create_and_login(api_client, real_session, "discount-revenue-flow")
    await grant_permission(actor, PERMISSION_RECEPTION_REGISTER_VISIT)

    register_resp = await api_client.post(
        "/api/v1/reception/visits",
        json={
            "new_patient": _new_patient_body("DiscountRevenueFlow"),
            "procedures": [{"name": "Consultation", "amount": "3000.00"}],
            "vitals_required": False,
            "initial_payment_amount": "0.01",
            "initial_payment_method": "cash",
            "discount_amount": "1000.00",
            "discount_reason": "Loyalty",
        },
        headers=_auth_header(access_token),
    )
    assert register_resp.status_code == 201, register_resp.text

    revenue_resp = await api_client.get(
        "/api/v1/reception/revenue", headers=_auth_header(access_token)
    )
    assert revenue_resp.status_code == 200
    body = revenue_resp.json()["data"]
    assert body["visits_count"] == 1
    # Not 3000.00 — the discount must already be reflected here.
    assert body["visits_revenue"] == "2000.00"
    assert body["total_revenue"] == "2000.00"


async def test_cancel_visit_requires_permission(api_client, real_session, grant_permission):
    actor, access_token = await _create_and_login(api_client, real_session, "cancel-no-perm")
    await grant_permission(actor, PERMISSION_RECEPTION_REGISTER_VISIT)
    register_resp = await api_client.post(
        "/api/v1/reception/visits",
        json={
            "new_patient": _new_patient_body("CancelNoPerm"),
            "procedures": [{"name": "Consultation", "amount": "1500.00"}],
            "vitals_required": False,
            "initial_payment_amount": "0.01",
            "initial_payment_method": "cash",
        },
        headers=_auth_header(access_token),
    )
    visit_id = register_resp.json()["data"]["visit"]["id"]

    resp = await api_client.post(
        f"/api/v1/reception/visits/{visit_id}/cancel",
        json={},
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 403


async def test_cancel_visit_success(api_client, real_session, grant_permission):
    actor, access_token = await _create_and_login(api_client, real_session, "cancel-success")
    await grant_permission(actor, PERMISSION_RECEPTION_REGISTER_VISIT)
    await grant_permission(actor, PERMISSION_RECEPTION_CANCEL_VISIT)
    register_resp = await api_client.post(
        "/api/v1/reception/visits",
        json={
            "new_patient": _new_patient_body("CancelSuccess"),
            "procedures": [{"name": "Consultation", "amount": "1500.00"}],
            "vitals_required": False,
            "initial_payment_amount": "0.01",
            "initial_payment_method": "cash",
        },
        headers=_auth_header(access_token),
    )
    visit_id = register_resp.json()["data"]["visit"]["id"]

    resp = await api_client.post(
        f"/api/v1/reception/visits/{visit_id}/cancel",
        json={"reason": "Patient left"},
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "cancelled"


# ---------------------------------------------------------------------
# Admin data correction (2026-08-19 addition) —
# reception:update_visit / reception:delete_visit, never granted via
# reception:register_visit or reception:cancel_visit alone.
# ---------------------------------------------------------------------


async def _register_visit_http(api_client, access_token, suffix: str) -> str:
    resp = await api_client.post(
        "/api/v1/reception/visits",
        json={
            "new_patient": _new_patient_body(suffix),
            "procedures": [{"name": "Consultation", "amount": "1500.00"}],
            "vitals_required": False,
            "initial_payment_amount": "0.01",
            "initial_payment_method": "cash",
        },
        headers=_auth_header(access_token),
    )
    return resp.json()["data"]["visit"]["id"]


async def test_update_visit_requires_permission(api_client, real_session, grant_permission):
    actor, access_token = await _create_and_login(api_client, real_session, "update-no-perm")
    await grant_permission(actor, PERMISSION_RECEPTION_REGISTER_VISIT)
    visit_id = await _register_visit_http(api_client, access_token, "UpdateNoPerm")

    resp = await api_client.patch(
        f"/api/v1/reception/visits/{visit_id}",
        json={"procedure": "Ultrasound"},
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "PERMISSION_DENIED"


async def test_update_visit_cancel_permission_alone_is_not_sufficient(
    api_client, real_session, grant_permission
):
    """Explicitly proves holding reception:cancel_visit (what
    Receptionists already have) does not implicitly widen into
    reception:update_visit — the two are unrelated, separately-granted
    permissions."""
    actor, access_token = await _create_and_login(api_client, real_session, "update-cancel-only")
    await grant_permission(actor, PERMISSION_RECEPTION_REGISTER_VISIT)
    await grant_permission(actor, PERMISSION_RECEPTION_CANCEL_VISIT)
    visit_id = await _register_visit_http(api_client, access_token, "UpdateCancelOnly")

    resp = await api_client.patch(
        f"/api/v1/reception/visits/{visit_id}",
        json={"procedure": "Ultrasound"},
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 403


async def test_update_visit_admin_can_correct_a_different_receptionists_slip(
    api_client, real_session, grant_permission
):
    """Ownership never matters for this permission — an admin corrects
    any receptionist's slip, not only their own."""
    receptionist, receptionist_token = await _create_and_login(
        api_client, real_session, "update-owner-receptionist"
    )
    await grant_permission(receptionist, PERMISSION_RECEPTION_REGISTER_VISIT)
    visit_id = await _register_visit_http(api_client, receptionist_token, "UpdateOwnership")

    admin, admin_token = await _create_and_login(api_client, real_session, "update-admin")
    await grant_permission(admin, PERMISSION_RECEPTION_UPDATE_VISIT)

    resp = await api_client.patch(
        f"/api/v1/reception/visits/{visit_id}",
        json={
            "full_name": f"{TEST_PATIENT_NAME_PREFIX}CorrectedByAdmin",
            "procedures": [{"name": "Ultrasound", "amount": "2500.00"}],
        },
        headers=_auth_header(admin_token),
    )

    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["patient"]["full_name"] == f"{TEST_PATIENT_NAME_PREFIX}CorrectedByAdmin"
    # `_register_visit_http` always registers an itemized visit (2026-08-21
    # addition) — this replaces its entire procedure-item set rather than
    # the (now-unused-for-this-visit) flat procedure/amount fields; see
    # VisitService.admin_replace_procedure_items's own docstring.
    assert body["visit"]["amount"] == "2500.00"
    assert len(body["visit"]["procedure_items"]) == 1
    assert body["visit"]["procedure_items"][0]["name"] == "Ultrasound"
    assert body["visit"]["procedure_items"][0]["amount"] == "2500.00"


async def test_delete_visit_requires_permission(api_client, real_session, grant_permission):
    actor, access_token = await _create_and_login(api_client, real_session, "delete-no-perm")
    await grant_permission(actor, PERMISSION_RECEPTION_REGISTER_VISIT)
    visit_id = await _register_visit_http(api_client, access_token, "DeleteNoPerm")

    resp = await api_client.delete(
        f"/api/v1/reception/visits/{visit_id}", headers=_auth_header(access_token)
    )

    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "PERMISSION_DENIED"


async def test_delete_visit_cancel_permission_alone_is_not_sufficient(
    api_client, real_session, grant_permission
):
    """The requirement this guards: Receptionists must never gain
    delete access, including implicitly through the cancel permission
    they already hold."""
    actor, access_token = await _create_and_login(api_client, real_session, "delete-cancel-only")
    await grant_permission(actor, PERMISSION_RECEPTION_REGISTER_VISIT)
    await grant_permission(actor, PERMISSION_RECEPTION_CANCEL_VISIT)
    visit_id = await _register_visit_http(api_client, access_token, "DeleteCancelOnly")

    resp = await api_client.delete(
        f"/api/v1/reception/visits/{visit_id}", headers=_auth_header(access_token)
    )

    assert resp.status_code == 403


async def test_delete_visit_succeeds_despite_a_settled_registration_payment_via_http(
    api_client, real_session, grant_permission
):
    """2026-08-23 revision — a visit registered via the real HTTP
    endpoint always collects a real registration-charge payment now
    (see VisitService.register_visit's own docstring), but that no
    longer blocks `DELETE /reception/visits/{id}` at all (see
    VisitHasSettledPaymentError's own docstring for why a soft-delete's
    much lower integrity risk doesn't warrant the same block editing
    gets) — only a settled Billing Invoice still does."""
    receptionist, receptionist_token = await _create_and_login(
        api_client, real_session, "delete-owner-receptionist"
    )
    await grant_permission(receptionist, PERMISSION_RECEPTION_REGISTER_VISIT)
    visit_id = await _register_visit_http(api_client, receptionist_token, "DeleteSuccess")

    admin, admin_token = await _create_and_login(api_client, real_session, "delete-admin")
    await grant_permission(admin, PERMISSION_RECEPTION_DELETE_VISIT)
    await grant_permission(admin, PERMISSION_VISITS_READ)

    delete_resp = await api_client.delete(
        f"/api/v1/reception/visits/{visit_id}", headers=_auth_header(admin_token)
    )
    assert delete_resp.status_code == 200

    get_resp = await api_client.get(
        f"/api/v1/visits/{visit_id}", headers=_auth_header(admin_token)
    )
    assert get_resp.status_code == 404


async def test_delete_visit_success_removes_it_from_get_for_a_legacy_visit(
    api_client, real_session, patient_service, grant_permission
):
    """The HTTP-level sibling of `test_admin_delete_visit_allowed_for_
    legacy_visit_with_no_payment_tracking` (test_reception_service.py)
    — a visit predating payment tracking (`payment_status IS NULL`,
    constructed directly here since it's the one shape a real HTTP
    registration can never produce) is, alongside the test immediately
    above, one of the two `payment_status` shapes now uniformly
    deletable."""
    admin, admin_token = await _create_and_login(api_client, real_session, "delete-legacy-admin")
    await grant_permission(admin, PERMISSION_RECEPTION_DELETE_VISIT)
    await grant_permission(admin, PERMISSION_VISITS_READ)

    patient = await patient_service.register_patient(
        actor=admin,
        full_name=f"{TEST_PATIENT_NAME_PREFIX}DeleteLegacyHttp",
        guardian_name=None,
        gender=None,
        age_years=30,
        phone_number="03001234567",
        cnic=None,
        address=None,
    )
    visit = Visit(
        patient_id=patient.id,
        doctor_user_id=admin.id,
        queue_token=f"GYN-{admin.id.hex[-8:]}",
        procedure="Consultation",
        amount=Decimal("1500.00"),
        vitals_required=False,
        status=VisitStatus.REGISTERED,
        created_by=admin.id,
        updated_by=admin.id,
    )
    visit = await VisitRepository(real_session).add(visit)
    await real_session.commit()

    delete_resp = await api_client.delete(
        f"/api/v1/reception/visits/{visit.id}", headers=_auth_header(admin_token)
    )
    assert delete_resp.status_code == 200

    get_resp = await api_client.get(
        f"/api/v1/visits/{visit.id}", headers=_auth_header(admin_token)
    )
    assert get_resp.status_code == 404


# The invoice-paid delete block itself (VISIT_HAS_SETTLED_INVOICE) is
# deliberately proven at the service layer instead of here — see
# tests/test_reception_service.py's test_admin_delete_visit_blocked_
# when_invoice_paid/_partially_paid. Driving a visit to WAITING_BILLING
# purely over HTTP requires POST /consultations to auto-assign *this*
# test's own actor as the visit's doctor, which is exactly the
# pre-existing, already-diagnosed shared-dev-DB flakiness documented
# elsewhere in this session (a stale logged-in account from a prior
# session can win the auto-assignment instead) — unrelated to this
# feature, but it would make this specific HTTP-level test spuriously
# fail for a reason that has nothing to do with what it's meant to
# verify. The service-layer test pins the doctor explicitly at
# registration and is fully deterministic.


# ---------------------------------------------------------------------
# "My Revenue" (2026-08-19 addition) — RBAC over HTTP: reading requires
# the base reception:register_visit permission every receptionist
# already holds; clearing requires the new, separately-grantable
# reception:clear_own_revenue. Own-only scoping itself is proven at the
# service layer (test_reception_service.py) — these confirm the HTTP
# permission gates are wired correctly.
# ---------------------------------------------------------------------


async def test_get_own_revenue_requires_permission(api_client, real_session):
    _actor, access_token = await _create_and_login(api_client, real_session, "revenue-read-no-perm")

    resp = await api_client.get("/api/v1/reception/revenue", headers=_auth_header(access_token))

    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "PERMISSION_DENIED"


async def test_get_own_revenue_success_via_http(api_client, real_session, grant_permission):
    actor, access_token = await _create_and_login(api_client, real_session, "revenue-read-success")
    await grant_permission(actor, PERMISSION_RECEPTION_REGISTER_VISIT)
    await _register_visit_http(api_client, access_token, "RevenueHttpRead")

    resp = await api_client.get("/api/v1/reception/revenue", headers=_auth_header(access_token))

    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["visits_count"] == 1
    assert body["visits_revenue"] == "1500.00"
    assert body["total_revenue"] == "1500.00"
    # Never cleared, so this is the 24h auto-window's own timestamp — a
    # real, recent value, never null/all-time (2026-08-19 fix).
    assert body["cleared_at"]


async def test_clear_own_revenue_requires_permission(api_client, real_session, grant_permission):
    """Holding reception:register_visit alone (every receptionist's
    baseline) must not be enough to clear — clearing needs its own,
    separately-grantable permission."""
    actor, access_token = await _create_and_login(api_client, real_session, "revenue-clear-no-perm")
    await grant_permission(actor, PERMISSION_RECEPTION_REGISTER_VISIT)

    resp = await api_client.post(
        "/api/v1/reception/revenue/clear", headers=_auth_header(access_token)
    )

    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "PERMISSION_DENIED"


async def test_clear_own_revenue_success_via_http(api_client, real_session, grant_permission):
    actor, access_token = await _create_and_login(api_client, real_session, "revenue-clear-success")
    await grant_permission(actor, PERMISSION_RECEPTION_REGISTER_VISIT)
    await grant_permission(actor, PERMISSION_RECEPTION_CLEAR_OWN_REVENUE)
    await _register_visit_http(api_client, access_token, "RevenueHttpClear")

    clear_resp = await api_client.post(
        "/api/v1/reception/revenue/clear", headers=_auth_header(access_token)
    )
    assert clear_resp.status_code == 200
    assert clear_resp.json()["data"]["cleared_at"]

    after_resp = await api_client.get("/api/v1/reception/revenue", headers=_auth_header(access_token))
    body = after_resp.json()["data"]
    assert body["visits_count"] == 0
    assert body["total_revenue"] == "0.00"
    assert body["cleared_at"]


async def test_get_own_revenue_never_reflects_another_receptionists_visits(
    api_client, real_session, grant_permission
):
    """There is no user-id parameter on this endpoint at all — this
    confirms two different receptionists calling it get two different,
    correctly-isolated answers, the way the endpoint's own hard-scoping
    to the caller is meant to guarantee."""
    receptionist_a, token_a = await _create_and_login(api_client, real_session, "revenue-http-a")
    await grant_permission(receptionist_a, PERMISSION_RECEPTION_REGISTER_VISIT)
    await _register_visit_http(api_client, token_a, "RevenueHttpIsolationA")

    receptionist_b, token_b = await _create_and_login(api_client, real_session, "revenue-http-b")
    await grant_permission(receptionist_b, PERMISSION_RECEPTION_REGISTER_VISIT)

    resp_b = await api_client.get("/api/v1/reception/revenue", headers=_auth_header(token_b))

    assert resp_b.status_code == 200
    assert resp_b.json()["data"]["visits_count"] == 0
    assert resp_b.json()["data"]["total_revenue"] == "0.00"


# ---------------------------------------------------------------------
# Itemized procedures — catalog-linked and manual entries coexisting
# (2026-08-21 addition). See app/modules/visits/models.py's
# `VisitProcedureItem` docstring for the full per-item (not per-visit)
# mutual-exclusivity rationale this proves.
# ---------------------------------------------------------------------


async def test_register_visit_with_catalog_and_manual_procedures_together(
    api_client, real_session, grant_permission
):
    actor, access_token = await _create_and_login(api_client, real_session, "catalog-plus-manual")
    await grant_permission(actor, PERMISSION_RECEPTION_REGISTER_VISIT)
    await grant_permission(actor, PERMISSION_PROCEDURES_MANAGE)
    create_resp = await api_client.post(
        "/api/v1/visits/procedures",
        json={"name": f"{TEST_PROCEDURE_NAME_PREFIX}CatalogPlusManual", "price": "1000.00"},
        headers=_auth_header(access_token),
    )
    procedure_id = create_resp.json()["data"]["id"]

    resp = await api_client.post(
        "/api/v1/reception/visits",
        json={
            "new_patient": _new_patient_body("CatalogPlusManual"),
            "procedures": [
                {"procedure_id": procedure_id},
                {"name": "Custom Follow-up", "amount": "250.00"},
            ],
            "vitals_required": False,
            "initial_payment_amount": "0.01",
            "initial_payment_method": "cash",
        },
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 201, resp.text
    visit = resp.json()["data"]["visit"]
    assert visit["amount"] == "1250.00"  # 1000.00 (catalog) + 250.00 (manual)
    items = visit["procedure_items"]
    assert len(items) == 2
    catalog_item = next(item for item in items if item["procedure_id"] == procedure_id)
    manual_item = next(item for item in items if item["procedure_id"] is None)
    assert catalog_item["name"] == f"{TEST_PROCEDURE_NAME_PREFIX}CatalogPlusManual"
    assert catalog_item["amount"] == "1000.00"
    assert manual_item["name"] == "Custom Follow-up"
    assert manual_item["amount"] == "250.00"


async def test_register_visit_catalog_procedure_price_is_locked_not_client_supplied(
    api_client, real_session, grant_permission
):
    """Confirmed design decision: unlike a manual entry, a catalog-linked
    procedure's price is always taken from the catalog itself — the
    request schema rejects an attempt to also send name/amount for it
    (see VisitProcedureItemRequest's own docstring), so there is no way
    for a client-supplied price to silently override the catalog one."""
    actor, access_token = await _create_and_login(api_client, real_session, "catalog-price-lock")
    await grant_permission(actor, PERMISSION_RECEPTION_REGISTER_VISIT)
    await grant_permission(actor, PERMISSION_PROCEDURES_MANAGE)
    create_resp = await api_client.post(
        "/api/v1/visits/procedures",
        json={"name": f"{TEST_PROCEDURE_NAME_PREFIX}PriceLock", "price": "1200.00"},
        headers=_auth_header(access_token),
    )
    procedure_id = create_resp.json()["data"]["id"]

    resp = await api_client.post(
        "/api/v1/reception/visits",
        json={
            "new_patient": _new_patient_body("PriceLock"),
            "procedures": [{"procedure_id": procedure_id, "name": "Sneaky", "amount": "1.00"}],
            "vitals_required": False,
            "initial_payment_amount": "0.01",
            "initial_payment_method": "cash",
        },
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 422


async def test_register_visit_rejects_inactive_catalog_procedure(
    api_client, real_session, grant_permission
):
    actor, access_token = await _create_and_login(api_client, real_session, "catalog-inactive")
    await grant_permission(actor, PERMISSION_RECEPTION_REGISTER_VISIT)
    await grant_permission(actor, PERMISSION_PROCEDURES_MANAGE)
    create_resp = await api_client.post(
        "/api/v1/visits/procedures",
        json={"name": f"{TEST_PROCEDURE_NAME_PREFIX}Inactive", "price": "900.00"},
        headers=_auth_header(access_token),
    )
    procedure_id = create_resp.json()["data"]["id"]
    await api_client.patch(
        f"/api/v1/visits/procedures/{procedure_id}",
        json={"is_active": False},
        headers=_auth_header(access_token),
    )

    resp = await api_client.post(
        "/api/v1/reception/visits",
        json={
            "new_patient": _new_patient_body("CatalogInactive"),
            "procedures": [{"procedure_id": procedure_id}],
            "vitals_required": False,
            "initial_payment_amount": "0.01",
            "initial_payment_method": "cash",
        },
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "PROCEDURE_INACTIVE"


async def test_register_visit_manual_entry_requires_name_and_amount(
    api_client, real_session, grant_permission
):
    actor, access_token = await _create_and_login(api_client, real_session, "manual-incomplete")
    await grant_permission(actor, PERMISSION_RECEPTION_REGISTER_VISIT)

    resp = await api_client.post(
        "/api/v1/reception/visits",
        json={
            "new_patient": _new_patient_body("ManualIncomplete"),
            "procedures": [{"name": "Consultation"}],  # no amount
            "vitals_required": False,
            "initial_payment_amount": "0.01",
            "initial_payment_method": "cash",
        },
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 422


# ---------------------------------------------------------------------
# Registration-charge payment tracking (2026-08-22 addition) — a real
# payment (full or partial, never zero) is always required at
# registration; see VisitService.register_visit's own docstring.
# ---------------------------------------------------------------------


async def test_register_visit_full_payment_marks_visit_paid_via_http(
    api_client, real_session, grant_permission
):
    actor, access_token = await _create_and_login(api_client, real_session, "http-full-payment")
    await grant_permission(actor, PERMISSION_RECEPTION_REGISTER_VISIT)

    resp = await api_client.post(
        "/api/v1/reception/visits",
        json={
            "new_patient": _new_patient_body("HttpFullPayment"),
            "procedures": [{"name": "Consultation", "amount": "1500.00"}],
            "vitals_required": False,
            "initial_payment_amount": "1500.00",
            "initial_payment_method": "cash",
        },
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 201
    visit = resp.json()["data"]["visit"]
    assert visit["amount_paid"] == "1500.00"
    assert visit["payment_status"] == "paid"


async def test_register_visit_partial_payment_marks_visit_partially_paid_via_http(
    api_client, real_session, grant_permission
):
    actor, access_token = await _create_and_login(api_client, real_session, "http-partial-payment")
    await grant_permission(actor, PERMISSION_RECEPTION_REGISTER_VISIT)

    resp = await api_client.post(
        "/api/v1/reception/visits",
        json={
            "new_patient": _new_patient_body("HttpPartialPayment"),
            "procedures": [{"name": "C-Section", "amount": "50000.00"}],
            "vitals_required": False,
            "initial_payment_amount": "20000.00",
            "initial_payment_method": "jazzcash",
        },
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 201
    visit = resp.json()["data"]["visit"]
    assert visit["amount_paid"] == "20000.00"
    assert visit["payment_status"] == "partially_paid"


async def test_register_visit_rejects_zero_payment_via_http(
    api_client, real_session, grant_permission
):
    actor, access_token = await _create_and_login(api_client, real_session, "http-zero-payment")
    await grant_permission(actor, PERMISSION_RECEPTION_REGISTER_VISIT)

    resp = await api_client.post(
        "/api/v1/reception/visits",
        json={
            "new_patient": _new_patient_body("HttpZeroPayment"),
            "procedures": [{"name": "Consultation", "amount": "1500.00"}],
            "vitals_required": False,
            "initial_payment_amount": "0",
            "initial_payment_method": "cash",
        },
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 422


async def test_register_visit_rejects_payment_exceeding_amount_via_http(
    api_client, real_session, grant_permission
):
    actor, access_token = await _create_and_login(api_client, real_session, "http-over-payment")
    await grant_permission(actor, PERMISSION_RECEPTION_REGISTER_VISIT)

    resp = await api_client.post(
        "/api/v1/reception/visits",
        json={
            "new_patient": _new_patient_body("HttpOverPayment"),
            "procedures": [{"name": "Consultation", "amount": "1500.00"}],
            "vitals_required": False,
            "initial_payment_amount": "1500.01",
            "initial_payment_method": "cash",
        },
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VISIT_PAYMENT_EXCEEDS_BALANCE"


async def test_register_visit_requires_payment_method_via_http(
    api_client, real_session, grant_permission
):
    actor, access_token = await _create_and_login(api_client, real_session, "http-no-method")
    await grant_permission(actor, PERMISSION_RECEPTION_REGISTER_VISIT)

    resp = await api_client.post(
        "/api/v1/reception/visits",
        json={
            "new_patient": _new_patient_body("HttpNoMethod"),
            "procedures": [{"name": "Consultation", "amount": "1500.00"}],
            "vitals_required": False,
            "initial_payment_amount": "1500.00",
            "initial_payment_method": "",
        },
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 422


async def test_get_pending_revenue_summary_requires_permission(api_client, real_session):
    _actor, access_token = await _create_and_login(api_client, real_session, "pending-rev-no-perm")

    resp = await api_client.get(
        "/api/v1/visits/pending-revenue-summary", headers=_auth_header(access_token)
    )

    assert resp.status_code == 403


async def test_get_pending_revenue_summary_reflects_a_partially_paid_visit(
    api_client, real_session, grant_permission
):
    actor, access_token = await _create_and_login(api_client, real_session, "pending-rev-http")
    await grant_permission(actor, PERMISSION_RECEPTION_REGISTER_VISIT)
    await grant_permission(actor, PERMISSION_VISITS_READ)

    before = await api_client.get(
        "/api/v1/visits/pending-revenue-summary", headers=_auth_header(access_token)
    )
    before_amount = Decimal(before.json()["data"]["pending_revenue"])

    await api_client.post(
        "/api/v1/reception/visits",
        json={
            "new_patient": _new_patient_body("PendingRevHttp"),
            "procedures": [{"name": "C-Section", "amount": "50000.00"}],
            "vitals_required": False,
            "initial_payment_amount": "20000.00",
            "initial_payment_method": "cash",
        },
        headers=_auth_header(access_token),
    )

    after = await api_client.get(
        "/api/v1/visits/pending-revenue-summary", headers=_auth_header(access_token)
    )
    after_amount = Decimal(after.json()["data"]["pending_revenue"])

    assert after_amount - before_amount == Decimal("30000.00")

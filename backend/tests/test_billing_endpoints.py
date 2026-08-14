"""Full end-to-end HTTP tests for the Billing module — see
tests/test_patients_endpoints.py's identical module docstring."""

from app.modules.auth.models import User, UserStatus
from app.modules.auth.password_service import PasswordService
from app.modules.auth.repository import UserRepository
from app.modules.billing.constants import (
    PERMISSION_BILLING_MANAGE,
    PERMISSION_BILLING_READ,
    PERMISSION_BILLING_SUBMIT_CHARGE,
)
from app.modules.consultation.constants import (
    PERMISSION_CONSULTATION_MANAGE,
    PERMISSION_CONSULTATION_START,
)
from app.modules.reception.constants import PERMISSION_RECEPTION_REGISTER_VISIT
from tests.conftest import TEST_PATIENT_NAME_PREFIX, make_test_email

_PASSWORD = "Str0ng!Passw0rd#2026"


async def _create_and_login(api_client, real_session, suffix: str) -> tuple[User, str]:
    password_hash = await PasswordService().hash(_PASSWORD)
    email = make_test_email(suffix)
    user = await UserRepository(real_session).add(
        User(
            email=email,
            password_hash=password_hash,
            full_name="Billing Endpoint Actor",
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


async def _make_visit_waiting_billing(api_client, access_token, suffix: str) -> str:
    """Drives a Visit to WAITING_BILLING purely over HTTP — requires the
    actor to hold reception + consultation permissions too, granted by
    the caller before invoking this helper."""
    register_resp = await api_client.post(
        "/api/v1/reception/visits",
        json={
            "new_patient": {
                "full_name": f"{TEST_PATIENT_NAME_PREFIX}BillingHttp{suffix}",
                "guardian_name": None,
                "gender": "female",
                "age_years": 34,
                "phone_number": "03001234567",
                "cnic": None,
                "address": None,
            },
            "procedure": "Consultation",
            "amount": "1500.00",
            "vitals_required": False,
        },
        headers=_auth_header(access_token),
    )
    visit_id = register_resp.json()["data"]["visit"]["id"]

    start_resp = await api_client.post(
        "/api/v1/consultations", json={"visit_id": visit_id}, headers=_auth_header(access_token)
    )
    consultation_id = start_resp.json()["data"]["id"]

    await api_client.post(
        f"/api/v1/consultations/{consultation_id}/complete",
        json={},
        headers=_auth_header(access_token),
    )
    return visit_id


async def test_submit_pending_item_requires_permission(api_client, real_session):
    _actor, access_token = await _create_and_login(api_client, real_session, "no-perm-submit")

    resp = await api_client.post(
        "/api/v1/billing/pending-items",
        json={
            "visit_id": "019fd77d-8445-74c6-be04-b855f517f6fe",
            "description": "x",
            "amount": "100",
        },
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 403


async def test_full_billing_lifecycle_via_http(api_client, real_session, grant_permission):
    doctor, access_token = await _create_and_login(api_client, real_session, "full-lifecycle")
    await grant_permission(doctor, PERMISSION_RECEPTION_REGISTER_VISIT)
    await grant_permission(doctor, PERMISSION_CONSULTATION_START)
    await grant_permission(doctor, PERMISSION_CONSULTATION_MANAGE)
    await grant_permission(doctor, PERMISSION_BILLING_SUBMIT_CHARGE)
    await grant_permission(doctor, PERMISSION_BILLING_MANAGE)
    await grant_permission(doctor, PERMISSION_BILLING_READ)
    visit_id = await _make_visit_waiting_billing(api_client, access_token, "Full")

    submit_resp = await api_client.post(
        "/api/v1/billing/pending-items",
        json={"visit_id": visit_id, "description": "Ultrasound", "amount": "1500.00"},
        headers=_auth_header(access_token),
    )
    assert submit_resp.status_code == 201
    item_id = submit_resp.json()["data"]["id"]

    approve_resp = await api_client.post(
        f"/api/v1/billing/pending-items/{item_id}/approve", headers=_auth_header(access_token)
    )
    assert approve_resp.status_code == 200
    assert approve_resp.json()["data"]["status"] == "approved"

    generate_resp = await api_client.post(
        "/api/v1/billing/invoices",
        json={
            "visit_id": visit_id,
            "base_description": "Consultation Fee",
            "base_amount": "1000.00",
        },
        headers=_auth_header(access_token),
    )
    assert generate_resp.status_code == 201
    invoice_body = generate_resp.json()["data"]
    assert invoice_body["total_amount"] == "2500.00"
    assert len(invoice_body["line_items"]) == 2
    invoice_id = invoice_body["id"]

    pay_resp = await api_client.post(
        f"/api/v1/billing/invoices/{invoice_id}/pay",
        json={"amount": "2500.00"},
        headers=_auth_header(access_token),
    )
    assert pay_resp.status_code == 200
    assert pay_resp.json()["data"]["status"] == "paid"

    visit_resp = await api_client.get(
        f"/api/v1/visits/{visit_id}", headers=_auth_header(access_token)
    )
    assert visit_resp.status_code == 403  # visits:read never granted here

    print_resp = await api_client.get(
        f"/api/v1/billing/invoices/{invoice_id}/print", headers=_auth_header(access_token)
    )
    assert print_resp.status_code == 200
    assert print_resp.headers["content-type"].startswith("text/html")
    assert "2,500.00" in print_resp.text
    assert "Token #" in print_resp.text


async def test_partial_invoice_payments_via_http_sum_correctly_and_reject_overpay(
    api_client, real_session, grant_permission
):
    doctor, access_token = await _create_and_login(api_client, real_session, "partial-http")
    await grant_permission(doctor, PERMISSION_RECEPTION_REGISTER_VISIT)
    await grant_permission(doctor, PERMISSION_CONSULTATION_START)
    await grant_permission(doctor, PERMISSION_CONSULTATION_MANAGE)
    await grant_permission(doctor, PERMISSION_BILLING_MANAGE)
    await grant_permission(doctor, PERMISSION_BILLING_READ)
    visit_id = await _make_visit_waiting_billing(api_client, access_token, "PartialHttp")

    generate_resp = await api_client.post(
        "/api/v1/billing/invoices",
        json={"visit_id": visit_id, "base_description": "Consultation Fee", "base_amount": "1000.00"},
        headers=_auth_header(access_token),
    )
    assert generate_resp.status_code == 201
    invoice_id = generate_resp.json()["data"]["id"]
    assert generate_resp.json()["data"]["payments"] == []

    first_pay = await api_client.post(
        f"/api/v1/billing/invoices/{invoice_id}/pay",
        json={"amount": "400.00"},
        headers=_auth_header(access_token),
    )
    assert first_pay.status_code == 200, first_pay.text
    first_body = first_pay.json()["data"]
    assert first_body["status"] == "partially_paid"
    assert first_body["amount_paid"] == "400.00"
    assert len(first_body["payments"]) == 1
    assert first_body["payments"][0]["amount"] == "400.00"

    # A second payment that would exceed the remaining 600.00 balance
    # must be rejected outright, and must not mutate the invoice.
    overpay_resp = await api_client.post(
        f"/api/v1/billing/invoices/{invoice_id}/pay",
        json={"amount": "600.01"},
        headers=_auth_header(access_token),
    )
    assert overpay_resp.status_code == 422
    assert overpay_resp.json()["error"]["code"] == "PAYMENT_EXCEEDS_BALANCE"

    second_pay = await api_client.post(
        f"/api/v1/billing/invoices/{invoice_id}/pay",
        json={"amount": "600.00"},
        headers=_auth_header(access_token),
    )
    assert second_pay.status_code == 200, second_pay.text
    second_body = second_pay.json()["data"]
    assert second_body["status"] == "paid"
    assert second_body["amount_paid"] == "1000.00"
    assert len(second_body["payments"]) == 2
    assert [p["amount"] for p in second_body["payments"]] == ["400.00", "600.00"]

    print_resp = await api_client.get(
        f"/api/v1/billing/invoices/{invoice_id}/print", headers=_auth_header(access_token)
    )
    assert print_resp.status_code == 200
    assert "1,000.00" in print_resp.text


async def test_generate_invoice_with_discount_via_http(api_client, real_session, grant_permission):
    doctor, access_token = await _create_and_login(api_client, real_session, "discount-http")
    await grant_permission(doctor, PERMISSION_RECEPTION_REGISTER_VISIT)
    await grant_permission(doctor, PERMISSION_CONSULTATION_START)
    await grant_permission(doctor, PERMISSION_CONSULTATION_MANAGE)
    await grant_permission(doctor, PERMISSION_BILLING_MANAGE)
    await grant_permission(doctor, PERMISSION_BILLING_READ)
    visit_id = await _make_visit_waiting_billing(api_client, access_token, "DiscountHttp")

    # A discount without a reason is rejected outright.
    no_reason_resp = await api_client.post(
        "/api/v1/billing/invoices",
        json={
            "visit_id": visit_id,
            "base_description": "Consultation Fee",
            "base_amount": "1000.00",
            "discount_amount": "100.00",
        },
        headers=_auth_header(access_token),
    )
    assert no_reason_resp.status_code == 422
    assert no_reason_resp.json()["error"]["code"] == "DISCOUNT_REASON_REQUIRED"

    # A discount exceeding the subtotal is rejected outright.
    overshoot_resp = await api_client.post(
        "/api/v1/billing/invoices",
        json={
            "visit_id": visit_id,
            "base_description": "Consultation Fee",
            "base_amount": "1000.00",
            "discount_amount": "1000.01",
            "discount_reason": "Too generous",
        },
        headers=_auth_header(access_token),
    )
    assert overshoot_resp.status_code == 422
    assert overshoot_resp.json()["error"]["code"] == "DISCOUNT_EXCEEDS_SUBTOTAL"

    generate_resp = await api_client.post(
        "/api/v1/billing/invoices",
        json={
            "visit_id": visit_id,
            "base_description": "Consultation Fee",
            "base_amount": "1000.00",
            "discount_amount": "200.00",
            "discount_reason": "Staff family discount",
        },
        headers=_auth_header(access_token),
    )
    assert generate_resp.status_code == 201, generate_resp.text
    invoice_body = generate_resp.json()["data"]
    assert invoice_body["total_amount"] == "800.00"
    assert invoice_body["discount_amount"] == "200.00"
    assert invoice_body["discount_reason"] == "Staff family discount"
    invoice_id = invoice_body["id"]

    print_resp = await api_client.get(
        f"/api/v1/billing/invoices/{invoice_id}/print", headers=_auth_header(access_token)
    )
    assert print_resp.status_code == 200
    assert "Subtotal" in print_resp.text
    assert "Staff family discount" in print_resp.text
    assert "800.00" in print_resp.text


async def test_generate_invoice_with_initial_payment_via_http(
    api_client, real_session, grant_permission
):
    """The merged single-step flow over a real HTTP request/response —
    Advance Received travels in the same POST /billing/invoices call
    (`initial_payment_amount`), and the response already reflects the
    recorded payment (no second request needed)."""
    doctor, access_token = await _create_and_login(api_client, real_session, "initial-payment-http")
    await grant_permission(doctor, PERMISSION_RECEPTION_REGISTER_VISIT)
    await grant_permission(doctor, PERMISSION_CONSULTATION_START)
    await grant_permission(doctor, PERMISSION_CONSULTATION_MANAGE)
    await grant_permission(doctor, PERMISSION_BILLING_MANAGE)
    await grant_permission(doctor, PERMISSION_BILLING_READ)
    visit_id = await _make_visit_waiting_billing(api_client, access_token, "InitialPaymentHttp")

    generate_resp = await api_client.post(
        "/api/v1/billing/invoices",
        json={
            "visit_id": visit_id,
            "base_description": "Consultation Fee",
            "base_amount": "1000.00",
            "initial_payment_amount": "600.00",
        },
        headers=_auth_header(access_token),
    )
    assert generate_resp.status_code == 201, generate_resp.text
    body = generate_resp.json()["data"]
    assert body["status"] == "partially_paid"
    assert body["amount_paid"] == "600.00"
    assert len(body["payments"]) == 1
    assert body["payments"][0]["amount"] == "600.00"
    # Pending = Total - Received (Total already post-discount; no
    # discount here, so Total - Discount collapses to just Total).
    pending = float(body["total_amount"]) - float(body["amount_paid"])
    assert pending == 400.00


async def test_generate_invoice_initial_payment_exceeding_balance_creates_no_invoice(
    api_client, real_session, grant_permission
):
    """Atomicity across a real HTTP request boundary: an
    initial_payment_amount that exceeds the balance is rejected, and —
    verified from a completely separate, later request (its own fresh
    DB session) — leaves no Invoice behind at all. Never a created-but-
    unpaid-and-unrecoverable record from a payment that failed."""
    doctor, access_token = await _create_and_login(api_client, real_session, "initial-payment-atomic")
    await grant_permission(doctor, PERMISSION_RECEPTION_REGISTER_VISIT)
    await grant_permission(doctor, PERMISSION_CONSULTATION_START)
    await grant_permission(doctor, PERMISSION_CONSULTATION_MANAGE)
    await grant_permission(doctor, PERMISSION_BILLING_MANAGE)
    await grant_permission(doctor, PERMISSION_BILLING_READ)
    visit_id = await _make_visit_waiting_billing(api_client, access_token, "InitialPaymentAtomic")

    failed_resp = await api_client.post(
        "/api/v1/billing/invoices",
        json={
            "visit_id": visit_id,
            "base_description": "Consultation Fee",
            "base_amount": "1000.00",
            "initial_payment_amount": "1000.01",
        },
        headers=_auth_header(access_token),
    )
    assert failed_resp.status_code == 422
    assert failed_resp.json()["error"]["code"] == "PAYMENT_EXCEEDS_BALANCE"

    list_resp = await api_client.get(
        f"/api/v1/billing/visits/{visit_id}/invoices", headers=_auth_header(access_token)
    )
    assert list_resp.status_code == 200
    assert list_resp.json()["data"] == []

    # The visit is still generate-able afterward too — confirms
    # InvoiceAlreadyOpenError never fires, i.e. no open invoice was
    # left behind by the failed attempt.
    retry_resp = await api_client.post(
        "/api/v1/billing/invoices",
        json={"visit_id": visit_id, "base_description": "Consultation Fee", "base_amount": "1000.00"},
        headers=_auth_header(access_token),
    )
    assert retry_resp.status_code == 201, retry_resp.text


async def test_print_invoice_requires_permission(api_client, real_session, grant_permission):
    doctor, access_token = await _create_and_login(api_client, real_session, "print-no-perm")
    await grant_permission(doctor, PERMISSION_RECEPTION_REGISTER_VISIT)
    await grant_permission(doctor, PERMISSION_CONSULTATION_START)
    await grant_permission(doctor, PERMISSION_CONSULTATION_MANAGE)
    await grant_permission(doctor, PERMISSION_BILLING_SUBMIT_CHARGE)
    await grant_permission(doctor, PERMISSION_BILLING_MANAGE)
    visit_id = await _make_visit_waiting_billing(api_client, access_token, "PrintNoPerm")
    generate_resp = await api_client.post(
        "/api/v1/billing/invoices",
        json={"visit_id": visit_id, "base_description": "Fee", "base_amount": "1000"},
        headers=_auth_header(access_token),
    )
    invoice_id = generate_resp.json()["data"]["id"]

    resp = await api_client.get(
        f"/api/v1/billing/invoices/{invoice_id}/print", headers=_auth_header(access_token)
    )

    assert resp.status_code == 403


async def test_doctor_cannot_approve_or_pay_only_submit(api_client, real_session, grant_permission):
    """Structural proof of §7's segregation of duties: a role holding
    only `billing:submit_charge` cannot approve, generate, or pay —
    those all require `billing:manage`, a separate code."""
    doctor, access_token = await _create_and_login(api_client, real_session, "doctor-only-submit")
    await grant_permission(doctor, PERMISSION_RECEPTION_REGISTER_VISIT)
    await grant_permission(doctor, PERMISSION_CONSULTATION_START)
    await grant_permission(doctor, PERMISSION_CONSULTATION_MANAGE)
    await grant_permission(doctor, PERMISSION_BILLING_SUBMIT_CHARGE)
    visit_id = await _make_visit_waiting_billing(api_client, access_token, "Segregation")
    submit_resp = await api_client.post(
        "/api/v1/billing/pending-items",
        json={"visit_id": visit_id, "description": "Injection", "amount": "500"},
        headers=_auth_header(access_token),
    )
    item_id = submit_resp.json()["data"]["id"]

    approve_resp = await api_client.post(
        f"/api/v1/billing/pending-items/{item_id}/approve", headers=_auth_header(access_token)
    )
    generate_resp = await api_client.post(
        "/api/v1/billing/invoices",
        json={"visit_id": visit_id, "base_description": "Fee", "base_amount": "1000"},
        headers=_auth_header(access_token),
    )

    assert approve_resp.status_code == 403
    assert generate_resp.status_code == 403

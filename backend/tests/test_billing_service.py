from decimal import Decimal

import pytest
from uuid6 import uuid7

from app.core.exceptions import ValidationError
from app.modules.auth.models import User, UserStatus
from app.modules.auth.repository import UserRepository
from app.modules.billing.exceptions import (
    DiscountExceedsSubtotalError,
    DiscountReasonRequiredError,
    InvoiceAlreadyOpenError,
    InvoiceNotFoundError,
    InvoiceNotPayableError,
    PaymentExceedsBalanceError,
    PendingBillingItemNotFoundError,
    PendingBillingItemNotPendingError,
)
from app.modules.billing.models import InvoiceStatus, PendingBillingItemStatus
from app.modules.patients.models import PatientGender
from app.modules.visits.models import VisitStatus
from tests.conftest import TEST_PATIENT_NAME_PREFIX, make_test_email


async def _make_doctor(real_session, suffix: str) -> User:
    doctor = await UserRepository(real_session).add(
        User(
            email=make_test_email(f"billing-doctor-{suffix}"),
            password_hash="hash",
            full_name="Billing Test Doctor",
            status=UserStatus.ACTIVE,
        )
    )
    await real_session.commit()
    return doctor


async def _make_visit_waiting_billing(reception_service, consultation_service, doctor, suffix):
    """Drives a Visit all the way to WAITING_BILLING through the real
    Reception -> Consultation pipeline — see
    tests/test_consultation_service.py's identical rationale for why
    this must go through the real services, not a shortcut."""
    _patient, visit, _entry = await reception_service.register_visit(
        actor=doctor,
        patient_id=None,
        new_patient={
            "full_name": f"{TEST_PATIENT_NAME_PREFIX}Billing{suffix}",
            "guardian_name": None,
            "gender": PatientGender.FEMALE,
            "age_years": 32,
            "phone_number": "03001234567",
            "cnic": None,
            "address": None,
        },
        doctor_user_id=doctor.id,
        procedure="Consultation",
        amount=Decimal("1500.00"),
        vitals_required=False,
    )
    consultation = await consultation_service.start_consultation(actor=doctor, visit_id=visit.id)
    await consultation_service.complete_consultation(
        actor=doctor, consultation_id=consultation.id, updates={}
    )
    return visit


async def test_submit_pending_item_creates_pending_status(
    real_session, reception_service, consultation_service, billing_service
):
    doctor = await _make_doctor(real_session, "submit")
    visit = await _make_visit_waiting_billing(reception_service, consultation_service, doctor, "A")

    item = await billing_service.submit_pending_item(
        actor=doctor, visit_id=visit.id, description="Injection", amount=Decimal("500.00")
    )

    assert item.status == PendingBillingItemStatus.PENDING
    assert item.amount == Decimal("500.00")


async def test_approve_and_reject_pending_item(
    real_session, reception_service, consultation_service, billing_service
):
    doctor = await _make_doctor(real_session, "approve-reject")
    visit = await _make_visit_waiting_billing(reception_service, consultation_service, doctor, "B")
    approved = await billing_service.submit_pending_item(
        actor=doctor, visit_id=visit.id, description="Ultrasound", amount=Decimal("1500")
    )
    rejected = await billing_service.submit_pending_item(
        actor=doctor, visit_id=visit.id, description="Duplicate entry", amount=Decimal("500")
    )

    approved_result = await billing_service.approve_pending_item(actor=doctor, item_id=approved.id)
    rejected_result = await billing_service.reject_pending_item(actor=doctor, item_id=rejected.id)

    assert approved_result.status == PendingBillingItemStatus.APPROVED
    assert rejected_result.status == PendingBillingItemStatus.REJECTED


async def test_approve_already_approved_item_raises(
    real_session, reception_service, consultation_service, billing_service
):
    doctor = await _make_doctor(real_session, "double-approve")
    visit = await _make_visit_waiting_billing(reception_service, consultation_service, doctor, "C")
    item = await billing_service.submit_pending_item(
        actor=doctor, visit_id=visit.id, description="Injection", amount=Decimal("500")
    )
    await billing_service.approve_pending_item(actor=doctor, item_id=item.id)

    with pytest.raises(PendingBillingItemNotPendingError):
        await billing_service.approve_pending_item(actor=doctor, item_id=item.id)


async def test_approve_unknown_item_raises_not_found(real_session, billing_service):
    doctor = await _make_doctor(real_session, "approve-404")
    with pytest.raises(PendingBillingItemNotFoundError):
        await billing_service.approve_pending_item(actor=doctor, item_id=uuid7())


async def test_generate_invoice_includes_only_approved_items(
    real_session, reception_service, consultation_service, visit_service, billing_service
):
    doctor = await _make_doctor(real_session, "generate")
    visit = await _make_visit_waiting_billing(reception_service, consultation_service, doctor, "D")
    approved = await billing_service.submit_pending_item(
        actor=doctor, visit_id=visit.id, description="Ultrasound", amount=Decimal("1500")
    )
    await billing_service.approve_pending_item(actor=doctor, item_id=approved.id)
    pending = await billing_service.submit_pending_item(
        actor=doctor, visit_id=visit.id, description="Not yet decided", amount=Decimal("300")
    )

    invoice = await billing_service.generate_invoice(
        actor=doctor,
        visit_id=visit.id,
        base_description="Consultation Fee",
        base_amount=Decimal("1000"),
    )

    assert invoice.status == InvoiceStatus.PENDING_PAYMENT
    assert invoice.total_amount == Decimal("2500.00")
    line_items = await billing_service.get_line_items(invoice.id)
    assert len(line_items) == 2
    updated_visit = await visit_service.get_visit(visit.id)
    assert updated_visit.status == VisitStatus.PAYMENT_PENDING
    # The still-pending item must remain untouched, unbilled.
    still_pending = await billing_service.list_pending_items(
        visit.id, status=PendingBillingItemStatus.PENDING
    )
    assert [i.id for i in still_pending] == [pending.id]


async def test_money_fields_are_quantized_to_two_decimal_places_in_the_same_response(
    real_session, reception_service, consultation_service, billing_service
):
    """Every money-accepting method must return its value at the
    column's actual 2-decimal scale in the *same* call that created it
    — not only on a later, separate fetch (see app/shared/money.py's
    docstring). Whole-number `Decimal`s (e.g. "1000", not "1000.00")
    are exactly what a real caller sends when there's no fractional
    amount, so this must never depend on the caller pre-formatting."""
    doctor = await _make_doctor(real_session, "quantize")
    visit = await _make_visit_waiting_billing(
        reception_service, consultation_service, doctor, "Quantize"
    )

    pending_item = await billing_service.submit_pending_item(
        actor=doctor, visit_id=visit.id, description="Ultrasound", amount=Decimal("1500")
    )
    assert str(pending_item.amount) == "1500.00"
    await billing_service.approve_pending_item(actor=doctor, item_id=pending_item.id)

    invoice = await billing_service.generate_invoice(
        actor=doctor, visit_id=visit.id, base_description="Fee", base_amount=Decimal("1000")
    )
    assert str(invoice.total_amount) == "2500.00"
    assert str(invoice.amount_paid) == "0.00"

    paid = await billing_service.record_payment(
        actor=doctor, invoice_id=invoice.id, amount=Decimal("2500")
    )
    assert str(paid.amount_paid) == "2500.00"


async def test_generate_invoice_twice_raises_already_open(
    real_session, reception_service, consultation_service, billing_service
):
    doctor = await _make_doctor(real_session, "generate-twice")
    visit = await _make_visit_waiting_billing(reception_service, consultation_service, doctor, "E")
    await billing_service.generate_invoice(
        actor=doctor,
        visit_id=visit.id,
        base_description="Consultation Fee",
        base_amount=Decimal("1000"),
    )

    with pytest.raises(InvoiceAlreadyOpenError):
        await billing_service.generate_invoice(
            actor=doctor,
            visit_id=visit.id,
            base_description="Consultation Fee",
            base_amount=Decimal("1000"),
        )


async def test_generate_invoice_with_discount_reduces_total_and_records_reason(
    real_session, reception_service, consultation_service, billing_service
):
    doctor = await _make_doctor(real_session, "discount")
    visit = await _make_visit_waiting_billing(
        reception_service, consultation_service, doctor, "Discount"
    )
    approved = await billing_service.submit_pending_item(
        actor=doctor, visit_id=visit.id, description="Ultrasound", amount=Decimal("500")
    )
    await billing_service.approve_pending_item(actor=doctor, item_id=approved.id)

    invoice = await billing_service.generate_invoice(
        actor=doctor,
        visit_id=visit.id,
        base_description="Consultation Fee",
        base_amount=Decimal("1000"),
        discount_amount=Decimal("200"),
        discount_reason="Staff family discount",
    )

    # subtotal = 1000 + 500 = 1500; total = 1500 - 200 = 1300.
    assert invoice.total_amount == Decimal("1300.00")
    assert invoice.discount_amount == Decimal("200.00")
    assert invoice.discount_reason == "Staff family discount"
    # The pre-discount subtotal is always recoverable as total + discount.
    line_items = await billing_service.get_line_items(invoice.id)
    assert sum((li.amount for li in line_items), Decimal("0")) == Decimal("1500.00")
    assert invoice.total_amount + invoice.discount_amount == Decimal("1500.00")


async def test_generate_invoice_without_discount_leaves_discount_fields_at_zero_and_none(
    real_session, reception_service, consultation_service, billing_service
):
    doctor = await _make_doctor(real_session, "no-discount")
    visit = await _make_visit_waiting_billing(
        reception_service, consultation_service, doctor, "NoDiscount"
    )

    invoice = await billing_service.generate_invoice(
        actor=doctor, visit_id=visit.id, base_description="Consultation Fee", base_amount=Decimal("1000")
    )

    assert invoice.discount_amount == Decimal("0.00")
    assert invoice.discount_reason is None
    assert invoice.total_amount == Decimal("1000.00")


async def test_generate_invoice_discount_without_reason_raises(
    real_session, reception_service, consultation_service, billing_service
):
    doctor = await _make_doctor(real_session, "discount-no-reason")
    visit = await _make_visit_waiting_billing(
        reception_service, consultation_service, doctor, "DiscountNoReason"
    )

    with pytest.raises(DiscountReasonRequiredError):
        await billing_service.generate_invoice(
            actor=doctor,
            visit_id=visit.id,
            base_description="Consultation Fee",
            base_amount=Decimal("1000"),
            discount_amount=Decimal("100"),
        )


async def test_generate_invoice_discount_blank_reason_raises(
    real_session, reception_service, consultation_service, billing_service
):
    """A whitespace-only reason is not a real reason."""
    doctor = await _make_doctor(real_session, "discount-blank-reason")
    visit = await _make_visit_waiting_billing(
        reception_service, consultation_service, doctor, "DiscountBlankReason"
    )

    with pytest.raises(DiscountReasonRequiredError):
        await billing_service.generate_invoice(
            actor=doctor,
            visit_id=visit.id,
            base_description="Consultation Fee",
            base_amount=Decimal("1000"),
            discount_amount=Decimal("100"),
            discount_reason="   ",
        )


async def test_generate_invoice_discount_exceeding_subtotal_raises(
    real_session, reception_service, consultation_service, billing_service
):
    doctor = await _make_doctor(real_session, "discount-overshoot")
    visit = await _make_visit_waiting_billing(
        reception_service, consultation_service, doctor, "DiscountOvershoot"
    )

    with pytest.raises(DiscountExceedsSubtotalError):
        await billing_service.generate_invoice(
            actor=doctor,
            visit_id=visit.id,
            base_description="Consultation Fee",
            base_amount=Decimal("1000"),
            discount_amount=Decimal("1000.01"),
            discount_reason="Too generous",
        )


async def test_generate_invoice_negative_discount_raises_validation_error(
    real_session, reception_service, consultation_service, billing_service
):
    doctor = await _make_doctor(real_session, "discount-negative")
    visit = await _make_visit_waiting_billing(
        reception_service, consultation_service, doctor, "DiscountNegative"
    )

    with pytest.raises(ValidationError):
        await billing_service.generate_invoice(
            actor=doctor,
            visit_id=visit.id,
            base_description="Consultation Fee",
            base_amount=Decimal("1000"),
            discount_amount=Decimal("-1"),
            discount_reason="Nonsensical",
        )


async def test_generate_invoice_discount_equal_to_subtotal_allows_zero_total(
    real_session, reception_service, consultation_service, billing_service
):
    """A full-amount discount (e.g. a genuinely free consultation) is
    allowed all the way down to zero — the ck_invoice_total_amount_non_
    negative constraint's floor, not an arbitrary business cap we asked
    the user about and were told not to add."""
    doctor = await _make_doctor(real_session, "discount-full")
    visit = await _make_visit_waiting_billing(
        reception_service, consultation_service, doctor, "DiscountFull"
    )

    invoice = await billing_service.generate_invoice(
        actor=doctor,
        visit_id=visit.id,
        base_description="Complimentary Consultation",
        base_amount=Decimal("1000"),
        discount_amount=Decimal("1000"),
        discount_reason="Complimentary — hospital board approval",
    )

    assert invoice.total_amount == Decimal("0.00")
    assert invoice.status == InvoiceStatus.PENDING_PAYMENT


async def test_record_full_payment_marks_paid_and_completes_visit(
    real_session, reception_service, consultation_service, visit_service, billing_service
):
    doctor = await _make_doctor(real_session, "full-payment")
    visit = await _make_visit_waiting_billing(reception_service, consultation_service, doctor, "F")
    invoice = await billing_service.generate_invoice(
        actor=doctor,
        visit_id=visit.id,
        base_description="Consultation Fee",
        base_amount=Decimal("1000"),
    )

    paid = await billing_service.record_payment(
        actor=doctor, invoice_id=invoice.id, amount=Decimal("1000")
    )

    assert paid.status == InvoiceStatus.PAID
    assert paid.paid_at is not None
    updated_visit = await visit_service.get_visit(visit.id)
    assert updated_visit.status == VisitStatus.COMPLETED


async def test_record_partial_payment_keeps_visit_payment_pending(
    real_session, reception_service, consultation_service, visit_service, billing_service
):
    doctor = await _make_doctor(real_session, "partial-payment")
    visit = await _make_visit_waiting_billing(reception_service, consultation_service, doctor, "G")
    invoice = await billing_service.generate_invoice(
        actor=doctor,
        visit_id=visit.id,
        base_description="Consultation Fee",
        base_amount=Decimal("1000"),
    )

    partial = await billing_service.record_payment(
        actor=doctor, invoice_id=invoice.id, amount=Decimal("400")
    )

    assert partial.status == InvoiceStatus.PARTIALLY_PAID
    assert partial.amount_paid == Decimal("400.00")
    updated_visit = await visit_service.get_visit(visit.id)
    assert updated_visit.status == VisitStatus.PAYMENT_PENDING


async def test_multiple_partial_payments_sum_correctly_and_recorded_as_audit_rows(
    real_session, reception_service, consultation_service, billing_service
):
    """Multiple partials summing correctly, plus the audit-trail
    itself: each `record_payment` call must add its own
    `InvoicePayment` row (never overwrite a prior one — same spirit as
    MedicineBillItem's snapshot convention), and `amount_paid` must
    always equal `SUM(payments)` since both are written in the same
    transaction (see InvoicePayment's docstring)."""
    doctor = await _make_doctor(real_session, "multi-partial")
    visit = await _make_visit_waiting_billing(
        reception_service, consultation_service, doctor, "MultiPartial"
    )
    invoice = await billing_service.generate_invoice(
        actor=doctor,
        visit_id=visit.id,
        base_description="Consultation Fee",
        base_amount=Decimal("1000"),
    )

    first = await billing_service.record_payment(
        actor=doctor, invoice_id=invoice.id, amount=Decimal("250")
    )
    assert first.status == InvoiceStatus.PARTIALLY_PAID
    assert first.amount_paid == Decimal("250.00")

    second = await billing_service.record_payment(
        actor=doctor, invoice_id=invoice.id, amount=Decimal("300")
    )
    assert second.status == InvoiceStatus.PARTIALLY_PAID
    assert second.amount_paid == Decimal("550.00")

    third = await billing_service.record_payment(
        actor=doctor, invoice_id=invoice.id, amount=Decimal("450")
    )
    assert third.status == InvoiceStatus.PAID
    assert third.amount_paid == Decimal("1000.00")
    assert third.paid_at is not None

    payments = await billing_service.get_payments(invoice.id)
    assert [p.amount for p in payments] == [Decimal("250.00"), Decimal("300.00"), Decimal("450.00")]
    assert sum((p.amount for p in payments), Decimal("0")) == third.amount_paid
    # Each row is independently attributed/timestamped, not a single
    # mutable field overwritten in place.
    assert all(p.created_by == doctor.id for p in payments)
    assert len({p.id for p in payments}) == 3


async def test_record_payment_exceeding_balance_raises(
    real_session, reception_service, consultation_service, billing_service
):
    doctor = await _make_doctor(real_session, "overpay")
    visit = await _make_visit_waiting_billing(reception_service, consultation_service, doctor, "H")
    invoice = await billing_service.generate_invoice(
        actor=doctor,
        visit_id=visit.id,
        base_description="Consultation Fee",
        base_amount=Decimal("1000"),
    )

    with pytest.raises(PaymentExceedsBalanceError):
        await billing_service.record_payment(
            actor=doctor, invoice_id=invoice.id, amount=Decimal("1000.01")
        )


async def test_record_payment_on_paid_invoice_raises_immutable(
    real_session, reception_service, consultation_service, billing_service
):
    """Paid invoices are immutable (§7.4) — a second payment attempt
    against an already-fully-paid invoice must be rejected."""
    doctor = await _make_doctor(real_session, "pay-twice")
    visit = await _make_visit_waiting_billing(reception_service, consultation_service, doctor, "I")
    invoice = await billing_service.generate_invoice(
        actor=doctor,
        visit_id=visit.id,
        base_description="Consultation Fee",
        base_amount=Decimal("1000"),
    )
    await billing_service.record_payment(
        actor=doctor, invoice_id=invoice.id, amount=Decimal("1000")
    )

    with pytest.raises(InvoiceNotPayableError):
        await billing_service.record_payment(
            actor=doctor, invoice_id=invoice.id, amount=Decimal("1")
        )


async def test_record_payment_zero_or_negative_raises_validation_error(
    real_session, reception_service, consultation_service, billing_service
):
    doctor = await _make_doctor(real_session, "zero-payment")
    visit = await _make_visit_waiting_billing(reception_service, consultation_service, doctor, "J")
    invoice = await billing_service.generate_invoice(
        actor=doctor,
        visit_id=visit.id,
        base_description="Consultation Fee",
        base_amount=Decimal("1000"),
    )

    with pytest.raises(ValidationError):
        await billing_service.record_payment(
            actor=doctor, invoice_id=invoice.id, amount=Decimal("0")
        )


async def test_post_payment_charge_opens_new_invoice_not_reopening_paid_one(
    real_session, reception_service, consultation_service, visit_service, billing_service
):
    """Phase 6 §7.4's central invariant: a billing request that arrives
    after payment never reopens the paid Invoice — it always creates a
    new, separate Outstanding Invoice, and the Visit's own
    COMPLETED -> PAYMENT_PENDING reopening transition (§4.1) drives it."""
    doctor = await _make_doctor(real_session, "post-payment-charge")
    visit = await _make_visit_waiting_billing(reception_service, consultation_service, doctor, "K")
    first_invoice = await billing_service.generate_invoice(
        actor=doctor,
        visit_id=visit.id,
        base_description="Consultation Fee",
        base_amount=Decimal("1000"),
    )
    await billing_service.record_payment(
        actor=doctor, invoice_id=first_invoice.id, amount=Decimal("1000")
    )
    completed_visit = await visit_service.get_visit(visit.id)
    assert completed_visit.status == VisitStatus.COMPLETED

    late_item = await billing_service.submit_pending_item(
        actor=doctor,
        visit_id=visit.id,
        description="Post-discharge dressing",
        amount=Decimal("200"),
    )
    await billing_service.approve_pending_item(actor=doctor, item_id=late_item.id)
    second_invoice = await billing_service.generate_invoice(
        actor=doctor,
        visit_id=visit.id,
        base_description="Additional charge",
        base_amount=Decimal("1"),
    )

    assert second_invoice.id != first_invoice.id
    assert second_invoice.total_amount == Decimal("201.00")
    reopened_visit = await visit_service.get_visit(visit.id)
    assert reopened_visit.status == VisitStatus.PAYMENT_PENDING
    # The original paid invoice is completely untouched.
    original = await billing_service.get_invoice(first_invoice.id)
    assert original.status == InvoiceStatus.PAID
    assert original.total_amount == Decimal("1000.00")


async def test_get_invoice_raises_not_found(billing_service):
    with pytest.raises(InvoiceNotFoundError):
        await billing_service.get_invoice(uuid7())

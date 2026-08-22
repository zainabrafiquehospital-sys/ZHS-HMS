from datetime import UTC, datetime
from decimal import Decimal

from app.shared.printing.service import (
    render_invoice_receipt,
    render_medicine_bill_receipt,
    render_registration_slip,
)


def _render(**overrides) -> str:
    defaults = dict(
        hospital_name="ZRH Hospital",
        patient_full_name="Jane Doe",
        patient_mr_number="MR-000001",
        visit_queue_token="GYN-000001",
        visit_procedure="Consultation",
        invoice_id="11111111-1111-1111-1111-111111111111",
        invoice_status="paid",
        invoice_created_at=datetime(2026, 1, 1, 10, 30, tzinfo=UTC),
        line_items=[("Consultation Fee", Decimal("1000.00")), ("Ultrasound", Decimal("1500.00"))],
        total_amount=Decimal("2500.00"),
        amount_paid=Decimal("2500.00"),
    )
    defaults.update(overrides)
    return render_invoice_receipt(**defaults)


def _render_slip(**overrides) -> str:
    defaults = dict(
        hospital_name="ZRH Hospital",
        display_timezone="Asia/Karachi",
        patient_full_name="Jane Doe",
        patient_mr_number="MR-000001",
        patient_age_years=30,
        patient_phone_number="03001234567",
        visit_queue_token="Token #001",
        visit_procedure="Consultation",
        visit_amount=Decimal("1500.00"),
        visit_created_at=datetime(2026, 1, 1, 10, 30, tzinfo=UTC),
        assigned_doctor_full_name=None,
    )
    defaults.update(overrides)
    return render_registration_slip(**defaults)


def _render_bill(**overrides) -> str:
    defaults = dict(
        hospital_name="ZRH Hospital",
        display_timezone="Asia/Karachi",
        bill_id="22222222-2222-2222-2222-222222222222",
        bill_created_at=datetime(2026, 1, 1, 10, 30, tzinfo=UTC),
        bill_queue_token=None,
        patient_full_name=None,
        patient_age_years=None,
        patient_phone_number=None,
        line_items=[("Panadol", "tablet", 2, Decimal("50.00"), Decimal("100.00"))],
        total_amount=Decimal("100.00"),
        amount_paid=Decimal("100.00"),
    )
    defaults.update(overrides)
    return render_medicine_bill_receipt(**defaults)


def test_render_includes_all_core_fields():
    html_document = _render()

    assert "ZRH Hospital" in html_document
    assert "Jane Doe" in html_document
    assert "MR-000001" in html_document
    assert "GYN-000001" in html_document
    assert "Consultation Fee" in html_document
    assert "Ultrasound" in html_document
    assert "1,000.00" in html_document
    assert "1,500.00" in html_document
    assert "2,500.00" in html_document


def test_render_computes_balance_due():
    html_document = _render(amount_paid=Decimal("400.00"))

    # total 2500.00, paid 400.00 -> balance due 2100.00
    assert "2,100.00" in html_document


def test_render_escapes_html_in_free_text_fields():
    """Patient/doctor-supplied free text is assembled directly into
    HTML — this must never allow injected markup to survive unescaped
    (stored XSS the moment this document is opened in a browser)."""
    html_document = _render(patient_full_name="<script>alert(1)</script>")

    assert "<script>alert(1)</script>" not in html_document
    assert "&lt;script&gt;" in html_document


def test_render_is_valid_html_document():
    html_document = _render()

    assert html_document.strip().startswith("<!doctype html>")
    assert "</html>" in html_document


def test_render_with_discount_shows_total_discount_and_net_amount_in_order():
    """2026-08-19 fix: the receipt must show the pre-discount subtotal,
    then the Discount line, then a distinct Net Amount line as the
    actual bottom-line total — not leave the final total only implied
    by Received/Pending."""
    html_document = _render(
        total_amount=Decimal("2000.00"),
        amount_paid=Decimal("500.00"),
        discount_amount=Decimal("500.00"),
        discount_reason="Staff discount",
    )

    assert "Discount (Staff discount)" in html_document
    assert "Net Amount" in html_document
    # subtotal (2500.00, recovered) -> discount -> net amount (2000.00)
    assert "2,500.00" in html_document
    assert "2,000.00" in html_document

    total_idx = html_document.index("Total Amount")
    discount_idx = html_document.index("Discount (Staff discount)")
    net_idx = html_document.index("Net Amount")
    assert total_idx < discount_idx < net_idx


def test_render_without_discount_omits_discount_row_but_keeps_net_amount():
    html_document = _render()

    assert "Discount" not in html_document
    assert "Net Amount" in html_document
    total_idx = html_document.index("Total Amount")
    net_idx = html_document.index("Net Amount")
    assert total_idx < net_idx


def test_render_slip_without_discount_shows_single_amount_row():
    """The common case (2026-08-19 addition) must be byte-for-byte the
    same shape this template has always produced — a single "Amount"
    row, no Discount/Net Amount rows at all."""
    html_document = _render_slip()

    assert ">Amount<" in html_document
    assert "Discount" not in html_document
    assert "Net Amount" not in html_document
    assert "1,500.00" in html_document


def test_render_slip_with_discount_shows_amount_discount_net_amount_in_order():
    html_document = _render_slip(
        visit_amount=Decimal("1500.00"),
        visit_discount_amount=Decimal("500.00"),
        visit_discount_reason="Referral",
    )

    assert "Discount (Referral)" in html_document
    assert "Net Amount" in html_document
    # subtotal (2000.00, recovered) -> discount -> net amount (1500.00)
    assert "2,000.00" in html_document
    assert "1,500.00" in html_document

    amount_idx = html_document.index(">Amount<")
    discount_idx = html_document.index("Discount (Referral)")
    net_idx = html_document.index("Net Amount")
    assert amount_idx < discount_idx < net_idx


def test_render_slip_escapes_html_in_discount_reason():
    html_document = _render_slip(
        visit_discount_amount=Decimal("100.00"),
        visit_discount_reason="<script>alert(1)</script>",
    )

    assert "<script>alert(1)</script>" not in html_document
    assert "&lt;script&gt;" in html_document


# ---------------------------------------------------------------------
# Itemized procedures (2026-08-21 addition) — the hybrid switch between
# this slip's two layouts. `visit_procedure_items` empty/omitted (every
# test above) exercises the legacy, byte-for-byte-unchanged branch;
# non-empty exercises the new itemized table. See
# render_registration_slip's own docstring for the full mechanism.
# ---------------------------------------------------------------------


def test_render_slip_with_one_procedure_item_shows_itemized_table():
    html_document = _render_slip(
        visit_amount=Decimal("800.00"),
        visit_procedure_items=[("Checkup", Decimal("800.00"))],
    )

    assert "Checkup" in html_document
    assert "800.00" in html_document
    assert "Total Amount" in html_document
    assert "Net Amount" in html_document
    assert 'class="items"' in html_document
    # The legacy row-based "Procedure" label must not also render.
    assert '<span class="label">Procedure</span>' not in html_document


def test_render_slip_with_multiple_procedure_items_lists_each_on_its_own_line():
    html_document = _render_slip(
        visit_amount=Decimal("1800.00"),
        visit_procedure_items=[
            ("Checkup", Decimal("800.00")),
            ("Scan", Decimal("700.00")),
            ("Follow-up", Decimal("300.00")),
        ],
    )

    assert "Checkup" in html_document
    assert "Scan" in html_document
    assert "Follow-up" in html_document
    assert "800.00" in html_document
    assert "700.00" in html_document
    assert "300.00" in html_document
    assert "1,800.00" in html_document  # subtotal: 800 + 700 + 300


def test_render_slip_itemized_without_discount_still_shows_net_amount():
    """Unlike the legacy layout (single Amount row, no Net Amount unless
    discounted), the itemized table always shows both Total Amount and
    Net Amount — mirroring render_medicine_bill_receipt's/
    render_invoice_receipt's identical always-shown convention."""
    html_document = _render_slip(
        visit_amount=Decimal("800.00"),
        visit_procedure_items=[("Checkup", Decimal("800.00"))],
    )

    assert "Discount" not in html_document
    assert "Total Amount" in html_document
    assert "Net Amount" in html_document


def test_render_slip_itemized_with_discount_shows_lines_in_correct_order():
    html_document = _render_slip(
        visit_amount=Decimal("1500.00"),
        visit_discount_amount=Decimal("300.00"),
        visit_discount_reason="Staff discount",
        visit_procedure_items=[
            ("Checkup", Decimal("1000.00")),
            ("Scan", Decimal("800.00")),
        ],
    )

    assert "Discount (Staff discount)" in html_document
    assert "1,800.00" in html_document  # subtotal
    assert "1,500.00" in html_document  # net

    total_idx = html_document.index("Total Amount")
    discount_idx = html_document.index("Discount (Staff discount)")
    net_idx = html_document.index("Net Amount")
    assert total_idx < discount_idx < net_idx


def test_render_slip_itemized_escapes_html_in_procedure_name():
    html_document = _render_slip(
        visit_amount=Decimal("500.00"),
        visit_procedure_items=[("<script>alert(1)</script>", Decimal("500.00"))],
    )

    assert "<script>alert(1)</script>" not in html_document
    assert "&lt;script&gt;" in html_document


def test_render_slip_empty_procedure_items_list_falls_back_to_legacy_layout():
    """An explicitly-empty list must behave identically to the omitted/
    None default — both mean "not itemized" (see this function's own
    docstring: `visit_procedure_items` is falsy either way)."""
    html_document = _render_slip(visit_procedure_items=[])

    assert ">Amount<" in html_document
    assert 'class="items"' not in html_document


# ---------------------------------------------------------------------
# Payment method (2026-08-19 addition) — a "Paid via: <method(s)>"
# summary line on every receipt/slip type, built from the caller-
# computed distinct list of payment methods actually used (see
# render_invoice_receipt's own docstring for the full convention).
# ---------------------------------------------------------------------


def test_invoice_receipt_shows_single_payment_method():
    html_document = _render(payment_methods=["cash"])

    assert "Paid via: Cash" in html_document


def test_invoice_receipt_shows_multiple_distinct_payment_methods_in_order():
    html_document = _render(payment_methods=["bank_transfer", "jazzcash", "cash"])

    assert "Paid via: Bank Transfer, JazzCash, Cash" in html_document


def test_invoice_receipt_omits_paid_via_line_when_nothing_paid():
    html_document = _render(amount_paid=Decimal("0.00"), payment_methods=[])

    assert "Paid via" not in html_document


def test_medicine_bill_receipt_shows_payment_method():
    html_document = _render_bill(payment_methods=["easypaisa"])

    assert "Paid via: EasyPaisa" in html_document


def test_medicine_bill_receipt_omits_paid_via_line_when_nothing_paid():
    html_document = _render_bill(amount_paid=Decimal("0.00"), payment_methods=[])

    assert "Paid via" not in html_document


def test_registration_slip_has_no_payment_method_concept():
    """The Registration Slip has no `payment_methods` (plural, distinct-
    methods-used) parameter and never renders a "Paid via" summary line,
    unlike the two receipt types that print after money has actually
    been collected via Billing/Pharmacy — still true after the
    2026-08-22 addition of `visit_amount_paid`/`visit_payment_status`
    (a Total/Received/Pending strip, never a per-method breakdown)."""
    html_document = _render_slip()

    assert "Paid via" not in html_document


# ---------------------------------------------------------------------
# Registration-charge payment tracking (2026-08-22 addition) —
# visit_amount_paid/visit_payment_status. Both default to None on
# _render_slip's own defaults dict above, so every existing test in
# this file continues to exercise the byte-for-byte-unchanged legacy
# path unless it explicitly overrides them here.
# ---------------------------------------------------------------------


def test_slip_full_payment_shows_no_payment_strip():
    """`payment_status='paid'` (whether settled in one payment or
    several — printing always reflects current state) renders exactly
    like the plain no-payment-tracking case: no strip at all."""
    html_document = _render_slip(
        visit_amount_paid=Decimal("1500.00"), visit_payment_status="paid"
    )

    assert '<div class="payment-strip">' not in html_document


def test_slip_legacy_visit_with_no_payment_tracking_shows_no_payment_strip():
    html_document = _render_slip(visit_amount_paid=None, visit_payment_status=None)

    assert '<div class="payment-strip">' not in html_document


def test_slip_partial_payment_shows_total_received_pending_strip():
    html_document = _render_slip(
        visit_amount=Decimal("50000.00"),
        visit_amount_paid=Decimal("20000.00"),
        visit_payment_status="partially_paid",
    )

    assert '<div class="payment-strip">' in html_document
    assert ">Total<" in html_document
    assert ">Received<" in html_document
    assert ">Pending<" in html_document
    assert "50,000.00" in html_document
    assert "20,000.00" in html_document
    assert "30,000.00" in html_document  # the derived pending balance


def test_slip_partial_payment_itemized_shows_payment_strip_below_items_table():
    html_document = _render_slip(
        visit_amount=Decimal("50000.00"),
        visit_amount_paid=Decimal("20000.00"),
        visit_payment_status="partially_paid",
        visit_procedure_items=[("C-Section", Decimal("50000.00"))],
    )

    assert '<div class="payment-strip">' in html_document
    items_index = html_document.index('<div class="items">')
    strip_index = html_document.index('<div class="payment-strip">')
    assert items_index < strip_index


def test_slip_fully_settled_after_multiple_payments_shows_no_payment_strip():
    """Printing always reflects the visit's *current* state, never its
    payment history — a visit paid off via two separate payments looks
    identical, once fully paid, to one paid in a single payment."""
    html_document = _render_slip(
        visit_amount=Decimal("50000.00"),
        visit_amount_paid=Decimal("50000.00"),
        visit_payment_status="paid",
    )

    assert '<div class="payment-strip">' not in html_document
    assert "Pending" not in html_document

from datetime import UTC, datetime
from decimal import Decimal

from app.shared.printing.service import render_invoice_receipt


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

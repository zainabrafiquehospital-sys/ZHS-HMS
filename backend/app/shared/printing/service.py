"""The Central Print Service (Phase 6 architecture §14): "every
printable document passes through this one Print Service, which is
responsible for layout/rendering, not for deciding *whether* a module
may print a given document (that authorization still belongs to the
owning module)." This module owns none of that authorization — the
Billing router decides *whether* an invoice may be printed (via the
same `billing:read` RBAC gate as viewing it) and supplies the data;
this service only ever turns already-fetched data into a rendered
document. No database access, no repository, no model — genuinely
stateless, matching Phase 6 §12.1's description of `print` as a
cross-cutting rendering service every module calls into but that
depends on none of them.

Scope decision for this build: renders **HTML**, not a PDF binary — no
PDF-generation library (weasyprint, reportlab, ...) is part of this
project's dependencies yet, and adding one is a real dependency/
deployment decision this build does not make unilaterally. HTML is one
of Phase 6 §14's own listed output formats and is immediately usable
today: a browser opening this response can print it (to a physical
printer, to a system "Save as PDF" driver, or to a thermal-printer
driver) via the browser's native print pipeline — the same mechanism
most real hospital front-desk software actually relies on for receipt
printing. Adding a server-side PDF renderer later is additive (a new
method here), not a redesign of this service's boundary."""

import base64
import html
from datetime import UTC, datetime
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo


def _escape(value: str) -> str:
    return html.escape(value, quote=True)


def _money(amount: Decimal) -> str:
    return f"{amount:,.2f}"


def render_invoice_receipt(
    *,
    hospital_name: str,
    patient_full_name: str,
    patient_mr_number: str,
    visit_queue_token: str,
    visit_procedure: str,
    invoice_id: str,
    invoice_status: str,
    invoice_created_at: datetime,
    line_items: list[tuple[str, Decimal]],
    total_amount: Decimal,
    amount_paid: Decimal,
    discount_amount: Decimal = Decimal("0.00"),
    discount_reason: str | None = None,
) -> str:
    """Renders a single-page, print-ready HTML receipt for one Invoice.
    Every dynamic value is HTML-escaped — this document assembles
    patient- and doctor-supplied free text (names, procedure,
    descriptions) directly into markup, so unescaped interpolation would
    be a stored-XSS vector the moment this HTML is ever opened in a
    browser (which is its entire purpose).

    Leads with the simple three-line mental model every workspace
    screen now shares: **Total Amount** (the pre-discount subtotal —
    `total_amount` is already post-discount on the stored Invoice, see
    BillingService.generate_invoice's docstring, so this recovers it as
    `total_amount + discount_amount` rather than storing it twice),
    **Discount** (only shown when actually applied — `discount_amount
    == 0` means the row is fully absent, never a zero line), then
    **Received**/**Pending** (`amount_paid` / `total_amount -
    amount_paid` — Pending is mathematically identical to `Total -
    Discount - Received` since `Total - Discount` is exactly the stored
    post-discount `total_amount`)."""
    pending = total_amount - amount_paid
    subtotal = total_amount + discount_amount
    rows = "".join(
        f"<tr><td>{_escape(description)}</td>" f"<td class='amount'>{_money(amount)}</td></tr>"
        for description, amount in line_items
    )
    discount_row = ""
    if discount_amount > 0:
        discount_label = "Discount"
        if discount_reason:
            discount_label = f"Discount ({_escape(discount_reason)})"
        discount_row = (
            f"<tr><td>{discount_label}</td><td class='amount'>-{_money(discount_amount)}</td></tr>"
        )
    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Invoice Receipt — {_escape(visit_queue_token)}</title>
<style>
  body {{ font-family: Arial, sans-serif; max-width: 480px; margin: 0 auto; padding: 16px; }}
  h1 {{ font-size: 18px; text-align: center; margin-bottom: 0; }}
  .subtitle {{ text-align: center; color: #555; margin-top: 4px; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 16px; }}
  th, td {{ text-align: left; padding: 4px 0; }}
  td.amount, th.amount {{ text-align: right; }}
  .totals td {{ font-weight: bold; border-top: 1px solid #000; padding-top: 6px; }}
  .meta {{ margin-top: 12px; font-size: 13px; color: #333; }}
  @media print {{ body {{ padding: 0; }} }}
</style>
</head>
<body>
  <h1>{_escape(hospital_name)}</h1>
  <div class="subtitle">Invoice Receipt</div>
  <div class="meta">
    <div>Patient: {_escape(patient_full_name)} (MR: {_escape(patient_mr_number)})</div>
    <div>Queue Token: {_escape(visit_queue_token)}</div>
    <div>Procedure: {_escape(visit_procedure)}</div>
    <div>Invoice ID: {_escape(invoice_id)}</div>
    <div>Status: {_escape(invoice_status)}</div>
    <div>Date: {invoice_created_at.strftime("%Y-%m-%d %H:%M")}</div>
  </div>
  <table>
    <thead><tr><th>Description</th><th class="amount">Amount</th></tr></thead>
    <tbody>
      {rows}
      <tr class="totals"><td>Total Amount</td><td class="amount">{_money(subtotal)}</td></tr>
      {discount_row}
      <tr><td>Received</td><td class="amount">{_money(amount_paid)}</td></tr>
      <tr><td>Pending</td><td class="amount">{_money(pending)}</td></tr>
    </tbody>
  </table>
</body>
</html>
"""


# frontend/public/images/logo.png, resolved relative to this file rather
# than a hardcoded absolute path, so it works regardless of which machine
# or environment the repository is checked out in — this file lives at
# backend/app/shared/printing/service.py, four directories below the
# repository root that backend/ and frontend/ both sit under.
_LOGO_PATH = Path(__file__).resolve().parents[4] / "frontend" / "public" / "images" / "logo.png"


@lru_cache(maxsize=1)
def _logo_data_uri() -> str | None:
    """Reads the hospital logo once per process and returns it as a
    self-contained `data:` URI to embed directly in the generated HTML,
    rather than an `<img src="/images/logo.png">` URL. Embedding is
    deliberate, not a style choice: this document is written into a blank
    popup window via `document.write()` (see useReception.js's
    `usePrintRegistrationSlip`), whose effective base URL for resolving a
    *relative* path is inconsistent across browsers, and a browser's
    print-to-PDF pipeline does not reliably re-fetch external resources at
    rasterization time. A data URI has no base URL to resolve and no
    network fetch to race — it is already fully loaded the instant the
    HTML is written, so it renders identically in the live preview, the
    print preview, and any exported PDF. Returns `None` (and the caller
    omits the `<img>` tag entirely) if the file isn't present, so a
    missing asset degrades gracefully instead of breaking printing."""
    try:
        data = _LOGO_PATH.read_bytes()
    except OSError:
        return None
    return f"data:image/png;base64,{base64.b64encode(data).decode('ascii')}"


def _to_local_time(moment: datetime, zone_name: str) -> datetime:
    """Converts a stored UTC timestamp to the given IANA zone for
    *display* only — `Visit.created_at` (see app/shared/base_entity.py)
    is a `timestamptz` column; asyncpg always decodes it back into a
    UTC-aware `datetime` regardless of the database session's own
    `TimeZone` setting, so formatting it directly (as this module
    previously did) prints the UTC wall-clock time, not local time. Falls
    back to treating a naive input as already UTC rather than guessing —
    every caller in this codebase produces timezone-aware UTC datetimes,
    so this only guards against that invariant ever changing upstream."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(ZoneInfo(zone_name))


def render_registration_slip(
    *,
    hospital_name: str,
    display_timezone: str,
    patient_full_name: str,
    patient_mr_number: str,
    patient_age_years: int,
    patient_phone_number: str,
    visit_queue_token: str,
    visit_procedure: str,
    visit_amount: Decimal,
    visit_created_at: datetime,
    assigned_doctor_full_name: str | None,
) -> str:
    """Renders Reception's fast-registration slip (Phase 6
    fast-registration §6/§7) — printed immediately after a visit is
    registered, before any doctor may have been assigned yet.

    Layout: A4 single-page, grayscale-only (borders/dividers/typography
    only — no filled color blocks), matching a real front-desk
    registration document rather than a receipt-roll ticket. Previous
    revisions of this template targeted an 80mm thermal roll; this one
    is intentionally A4-first per a later design pass — see this
    module's docstring for why HTML (browser print pipeline), not a
    server-side PDF, is still this build's chosen output format.

    `assigned_doctor_full_name` is deliberately accepted but not
    rendered — the attending doctor is intentionally omitted from this
    slip for now (a later revision adds it back); the parameter stays
    in the signature so the caller (reception/router.py) and the data
    it already resolves are untouched.

    `display_timezone` is an IANA zone name (e.g. `"Asia/Karachi"`,
    supplied by the caller from `settings.display_timezone`) — see
    `_to_local_time`'s docstring for why `visit_created_at` must be
    converted, not formatted as-is."""
    registered_on = _to_local_time(visit_created_at, display_timezone).strftime(
        "%d %b %Y, %I:%M %p"
    )

    logo_data_uri = _logo_data_uri()
    logo_html = (
        f'<img class="logo" src="{logo_data_uri}" alt="{_escape(hospital_name)} logo">'
        if logo_data_uri
        else ""
    )

    def _row(label: str, value: str) -> str:
        return (
            f'<div class="row"><span class="label">{_escape(label)}</span>'
            f'<span class="value">{_escape(value)}</span></div>'
        )

    patient_rows = "".join(
        [
            _row("MR Number", patient_mr_number),
            _row("Patient Name", patient_full_name),
            _row("Age", f"{patient_age_years} years"),
            _row("Contact Number", patient_phone_number),
        ]
    )
    visit_rows = "".join(
        [
            _row("Procedure", visit_procedure),
            _row("Amount", _money(visit_amount)),
            _row("Registered On", registered_on),
        ]
    )

    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Registration Slip — {_escape(visit_queue_token)}</title>
<style>
  :root {{
    --ink: #111111;
    --ink-soft: #555555;
    --rule: #d0d0d0;
    --rule-strong: #111111;
  }}
  * {{ box-sizing: border-box; }}
  html, body {{
    margin: 0;
    padding: 0;
    font-family: 'Inter', -apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
    color: var(--ink);
    background: #eeeeee;
  }}
  body {{
    padding: 28px 16px;
    display: flex;
    justify-content: center;
  }}
  .sheet {{
    width: 100%;
    max-width: 720px;
    background: #ffffff;
    border: 1px solid #dddddd;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
    padding: 32px 36px;
  }}

  /* ---------- Header ---------- */
  .header {{
    display: grid;
    grid-template-columns: auto 1fr auto;
    align-items: center;
    gap: 20px;
    padding-bottom: 16px;
  }}
  .logo {{
    height: 56px;
    width: auto;
    object-fit: contain;
  }}
  .identity {{ text-align: center; }}
  .identity .name {{
    font-size: 21px;
    font-weight: 800;
    letter-spacing: 0.5px;
    text-transform: uppercase;
    margin: 0;
  }}
  .identity .tagline {{
    margin-top: 4px;
    font-size: 10.5px;
    font-weight: 600;
    letter-spacing: 1.5px;
    text-transform: uppercase;
    color: var(--ink-soft);
  }}
  .contact-block {{
    text-align: right;
    font-size: 9.5px;
    line-height: 1.5;
    color: var(--ink-soft);
    white-space: nowrap;
  }}
  .contact-block strong {{ color: var(--ink); font-weight: 600; }}
  .header-rule {{ border: none; border-top: 2px solid var(--rule-strong); margin: 0 0 18px; }}

  /* ---------- Title box ---------- */
  .title-box {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    border: 1.5px solid var(--rule-strong);
    padding: 10px 18px;
    margin-bottom: 24px;
  }}
  .title-box .label {{
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 2px;
    text-transform: uppercase;
  }}
  .title-box .token {{
    font-size: 32px;
    font-weight: 800;
    letter-spacing: 1px;
  }}

  /* ---------- Body columns ---------- */
  .body-grid {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 36px;
  }}
  .section-heading {{
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 10px;
  }}
  .section-heading .bar {{
    width: 4px;
    height: 13px;
    background: var(--ink);
    flex-shrink: 0;
  }}
  .section-heading .text {{
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 1.5px;
    text-transform: uppercase;
  }}
  .row {{
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    gap: 12px;
    padding: 8px 0;
    border-bottom: 1px solid var(--rule);
  }}
  .row:last-child {{ border-bottom: none; }}
  .row .label {{
    font-size: 12px;
    font-weight: 500;
    color: var(--ink-soft);
    white-space: nowrap;
  }}
  .row .value {{
    font-size: 13px;
    font-weight: 700;
    text-align: right;
  }}

  /* ---------- Note ---------- */
  .note-box {{
    display: flex;
    gap: 18px;
    border: 1px solid var(--rule-strong);
    padding: 12px 18px;
    margin-top: 28px;
  }}
  .note-box .note-label {{
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1.5px;
    text-transform: uppercase;
    flex-shrink: 0;
  }}
  .note-box .note-text {{
    font-size: 10.5px;
    line-height: 1.6;
    color: var(--ink-soft);
  }}

  /* ---------- Print ---------- */
  @page {{ size: A4; margin: 14mm; }}
  @media print {{
    * {{ 
      print-color-adjust: exact !important; 
      -webkit-print-color-adjust: exact !important; 
      color: #000000 !important;
    }}
    html, body {{ 
      background: #ffffff !important; 
      padding: 0 !important; 
      color: #000000 !important; 
    }}
    body {{ display: block !important; }}
    .sheet {{
      max-width: none !important;
      width: 100% !important;
      border: none !important;
      box-shadow: none !important;
      padding: 0 !important;
      color: #000000 !important;
      background: #ffffff !important;
      page-break-inside: avoid; 
      break-inside: avoid;
    }}
    .logo {{ filter: grayscale(1); }}
  }}
</style>
</head>
<body>
  <div class="sheet">
    <div class="header">
      {logo_html}
      <div class="identity">
        <p class="name">{_escape(hospital_name)}</p>
        <div class="tagline">Gynecology &bull; Maternity &bull; Women's Care</div>
      </div>
      <div class="contact-block">
        <div>Shalimar Link Road, Lahore</div>
        <div><strong>International Standard Healthcare</strong></div>
        <div>Open 24 Hours</div>
        <div>Contact Us : 0300-0430009</div>
      </div>
    </div>
    <hr class="header-rule">

    <div class="title-box">
      <span class="label">Registration Slip</span>
      <span class="token">{_escape(visit_queue_token)}</span>
    </div>

    <div class="body-grid">
      <div>
        <div class="section-heading">
          <span class="bar"></span>
          <span class="text">Patient Information</span>
        </div>
        {patient_rows}
      </div>
      <div>
        <div class="section-heading">
          <span class="bar"></span>
          <span class="text">Visit Details</span>
        </div>
        {visit_rows}
      </div>
    </div>

    <div class="note-box">
      <span class="note-label">Note</span>
      <span class="note-text">
        Please retain this registration slip for your appointment and billing records.
        Present it at the reception desk during your visit for faster check-in.
      </span>
    </div>
  </div>
</body>
</html>
"""


def render_medicine_bill_receipt(
    *,
    hospital_name: str,
    display_timezone: str,
    bill_id: str,
    bill_created_at: datetime,
    visit_queue_token: str | None,
    patient_full_name: str | None,
    patient_mr_number: str | None,
    patient_age_years: int | None,
    patient_phone_number: str | None,
    line_items: list[tuple[str, str, int, Decimal, Decimal]],
    total_amount: Decimal,
    amount_paid: Decimal,
) -> str:
    """Renders the Pharmacy module's medicine bill slip — reuses the
    exact `.sheet`/`.header`/`.title-box`/`.body-grid` grayscale, A4,
    print-ready structure `render_registration_slip` established (same
    design language, same reasons: this document also prints on a plain
    B&W office printer, where layout/typography carries the document,
    not color — see this module's own docstring on the Central Print
    Service's grayscale convention).

    `visit_queue_token`/`patient_full_name`/`patient_mr_number`/
    `patient_age_years`/`patient_phone_number` are all `None` for a
    standalone walk-in sale with no linked Visit (see
    app/modules/pharmacy/models.py's `MedicineBill.visit_id` docstring)
    — the patient/visit reference section is simply omitted in that
    case rather than rendered with placeholder dashes. When a Visit is
    linked, `patient_age_years`/`patient_phone_number` mirror the same
    two fields `render_registration_slip` already shows (Age, Contact
    Number) — this is the identical `Patient` record, just rendered a
    second time on a different document.

    `line_items` is `(medicine_name, category, quantity, unit_price,
    line_total)` tuples, already snapshotted at billing time (see
    `MedicineBillItem`'s docstring) — this function renders exactly what
    was billed, never re-reads the live price list.

    `amount_paid` mirrors `render_invoice_receipt`'s identical Total
    Amount / Received / Pending footer (Pharmacy has no discount
    concept, so there is no conditional Discount row here — always
    exactly these three) — a bill freshly created and not yet paid
    renders `Received: 0.00` / `Pending` equal to the total, exactly
    like an unpaid Invoice would, rather than silently implying the
    sale was already settled."""
    billed_on = _to_local_time(bill_created_at, display_timezone).strftime("%d %b %Y, %I:%M %p")
    pending = total_amount - amount_paid
    short_bill_id = bill_id.split("-")[0].upper()

    logo_data_uri = _logo_data_uri()
    logo_html = (
        f'<img class="logo" src="{logo_data_uri}" alt="{_escape(hospital_name)} logo">'
        if logo_data_uri
        else ""
    )

    def _row(label: str, value: str) -> str:
        return (
            f'<div class="row"><span class="label">{_escape(label)}</span>'
            f'<span class="value">{_escape(value)}</span></div>'
        )

    reference_section = ""
    if patient_full_name is not None:
        reference_rows = "".join(
            [
                _row("Patient Name", patient_full_name),
                _row("MR Number", patient_mr_number or "—"),
                _row("Age", f"{patient_age_years} years" if patient_age_years is not None else "—"),
                _row("Contact Number", patient_phone_number or "—"),
                _row("Queue Token", visit_queue_token or "—"),
                _row("Billed On", billed_on),
            ]
        )
        reference_section = f"""
    <div class="section-heading">
      <span class="bar"></span>
      <span class="text">Patient / Visit Reference</span>
    </div>
    {reference_rows}
"""
    else:
        reference_section = f"""
    <div class="section-heading">
      <span class="bar"></span>
      <span class="text">Sale Reference</span>
    </div>
    {_row("Sale Type", "Walk-in (no visit on file)")}
    {_row("Billed On", billed_on)}
"""

    item_rows = "".join(
        f"<tr><td>{_escape(name)}</td><td class='category'>{_escape(category.title())}</td>"
        f"<td class='qty'>{quantity}</td><td class='amount'>{_money(unit_price)}</td>"
        f"<td class='amount'>{_money(line_total)}</td></tr>"
        for name, category, quantity, unit_price, line_total in line_items
    )

    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Medicine Slip — {_escape(short_bill_id)}</title>
<style>
  :root {{
    --ink: #111111;
    --ink-soft: #555555;
    --rule: #d0d0d0;
    --rule-strong: #111111;
  }}
  * {{ box-sizing: border-box; }}
  html, body {{
    margin: 0;
    padding: 0;
    font-family: 'Inter', -apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
    color: var(--ink);
    background: #eeeeee;
  }}
  body {{
    padding: 28px 16px;
    display: flex;
    justify-content: center;
  }}
  .sheet {{
    width: 100%;
    max-width: 720px;
    background: #ffffff;
    border: 1px solid #dddddd;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
    padding: 32px 36px;
  }}

  /* ---------- Header ---------- */
  .header {{
    display: grid;
    grid-template-columns: auto 1fr auto;
    align-items: center;
    gap: 20px;
    padding-bottom: 16px;
  }}
  .logo {{
    height: 56px;
    width: auto;
    object-fit: contain;
  }}
  .identity {{ text-align: center; }}
  .identity .name {{
    font-size: 21px;
    font-weight: 800;
    letter-spacing: 0.5px;
    text-transform: uppercase;
    margin: 0;
  }}
  .identity .tagline {{
    margin-top: 4px;
    font-size: 10.5px;
    font-weight: 600;
    letter-spacing: 1.5px;
    text-transform: uppercase;
    color: var(--ink-soft);
  }}
  .contact-block {{
    text-align: right;
    font-size: 9.5px;
    line-height: 1.5;
    color: var(--ink-soft);
    white-space: nowrap;
  }}
  .contact-block strong {{ color: var(--ink); font-weight: 600; }}
  .header-rule {{ border: none; border-top: 2px solid var(--rule-strong); margin: 0 0 18px; }}

  /* ---------- Title box ---------- */
  .title-box {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    border: 1.5px solid var(--rule-strong);
    padding: 10px 18px;
    margin-bottom: 24px;
  }}
  .title-box .label {{
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 2px;
    text-transform: uppercase;
  }}
  .title-box .token {{
    font-size: 26px;
    font-weight: 800;
    letter-spacing: 1px;
    font-family: 'Courier New', monospace;
  }}

  /* ---------- Reference section ---------- */
  .section-heading {{
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 10px;
  }}
  .section-heading .bar {{
    width: 4px;
    height: 13px;
    background: var(--ink);
    flex-shrink: 0;
  }}
  .section-heading .text {{
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 1.5px;
    text-transform: uppercase;
  }}
  .row {{
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    gap: 12px;
    padding: 7px 0;
    border-bottom: 1px solid var(--rule);
  }}
  .row:last-child {{ border-bottom: none; }}
  .row .label {{
    font-size: 12px;
    font-weight: 500;
    color: var(--ink-soft);
    white-space: nowrap;
  }}
  .row .value {{
    font-size: 13px;
    font-weight: 700;
    text-align: right;
  }}

  /* ---------- Itemized table ---------- */
  .items {{ margin-top: 26px; }}
  table {{ width: 100%; border-collapse: collapse; }}
  thead th {{
    text-align: left;
    font-size: 10.5px;
    font-weight: 700;
    letter-spacing: 1px;
    text-transform: uppercase;
    color: var(--ink-soft);
    border-bottom: 1.5px solid var(--rule-strong);
    padding: 0 0 8px;
  }}
  tbody td {{
    font-size: 13px;
    padding: 8px 0;
    border-bottom: 1px solid var(--rule);
  }}
  th.qty, td.qty {{ text-align: center; width: 60px; }}
  th.category, td.category {{ width: 110px; }}
  th.amount, td.amount {{ text-align: right; width: 110px; }}
  tfoot tr:first-child td {{
    font-size: 14px;
    font-weight: 800;
    padding-top: 12px;
    border-top: 2px solid var(--rule-strong);
    border-bottom: none;
  }}
  tfoot tr:not(:first-child) td {{
    font-size: 12px;
    font-weight: 600;
    color: var(--ink-soft);
    padding-top: 4px;
    border-bottom: none;
  }}
  tfoot td.amount {{ text-align: right; }}

  /* ---------- Note ---------- */
  .note-box {{
    display: flex;
    gap: 18px;
    border: 1px solid var(--rule-strong);
    padding: 12px 18px;
    margin-top: 28px;
  }}
  .note-box .note-label {{
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1.5px;
    text-transform: uppercase;
    flex-shrink: 0;
  }}
  .note-box .note-text {{
    font-size: 10.5px;
    line-height: 1.6;
    color: var(--ink-soft);
  }}

  /* ---------- Print ---------- */
  @page {{ size: A4; margin: 14mm; }}
  @media print {{
    * {{
      print-color-adjust: exact !important;
      -webkit-print-color-adjust: exact !important;
      color: #000000 !important;
    }}
    html, body {{
      background: #ffffff !important;
      padding: 0 !important;
      color: #000000 !important;
    }}
    body {{ display: block !important; }}
    .sheet {{
      max-width: none !important;
      width: 100% !important;
      border: none !important;
      box-shadow: none !important;
      padding: 0 !important;
      color: #000000 !important;
      background: #ffffff !important;
      page-break-inside: avoid;
      break-inside: avoid;
    }}
    .logo {{ filter: grayscale(1); }}
  }}
</style>
</head>
<body>
  <div class="sheet">
    <div class="header">
      {logo_html}
      <div class="identity">
        <p class="name">{_escape(hospital_name)}</p>
        <div class="tagline">Gynecology &bull; Maternity &bull; Women's Care</div>
      </div>
      <div class="contact-block">
        <div>Shalimar Link Road, Lahore</div>
        <div><strong>International Standard Healthcare</strong></div>
        <div>Open 24 Hours</div>
        <div>Contact Us : 0300-0430009</div>
      </div>
    </div>
    <hr class="header-rule">

    <div class="title-box">
      <span class="label">Medicine Slip</span>
      <span class="token">MED-{_escape(short_bill_id)}</span>
    </div>

    {reference_section}

    <div class="items">
      <table>
        <thead>
          <tr>
            <th>Medicine</th>
            <th class="category">Category</th>
            <th class="qty">Qty</th>
            <th class="amount">Unit Price</th>
            <th class="amount">Line Total</th>
          </tr>
        </thead>
        <tbody>
          {item_rows}
        </tbody>
        <tfoot>
          <tr>
            <td colspan="4">Total Amount</td>
            <td class="amount">{_money(total_amount)}</td>
          </tr>
          <tr>
            <td colspan="4">Received</td>
            <td class="amount">{_money(amount_paid)}</td>
          </tr>
          <tr>
            <td colspan="4">Pending</td>
            <td class="amount">{_money(pending)}</td>
          </tr>
        </tfoot>
      </table>
    </div>

    <div class="note-box">
      <span class="note-label">Note</span>
      <span class="note-text">
        Please retain this medicine slip for your records. Prices reflect the pharmacy
        price list at the time of this sale and are not affected by any later change.
      </span>
    </div>
  </div>
</body>
</html>
"""

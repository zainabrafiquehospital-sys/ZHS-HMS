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
method here), not a redesign of this service's boundary.

Layout (2026-08-24 redesign — narrow thermal receipt, replacing the
previous A4/half-A4 design): this hospital exclusively prints on an
80mm continuous-roll thermal printer, not A4 — every one of the three
templates below (`render_registration_slip`, `render_invoice_receipt`,
`render_medicine_bill_receipt`) shares one 80mm portrait "receipt"
layout, built around `_RECEIPT_STYLE` and the shared header/title-box/
row helpers just below. `@page {{ size: 80mm auto; margin: 0 2mm; }}`
is the specific fix for the previous bug (a fixed A4-length page left a
large blank trailing section on the roll below the actual content,
since the browser reserved the *declared* page length regardless of
how short the content was) — `auto` tells the print engine to size the
page to the content's own height instead of a fixed length; the small
`2mm` horizontal margin is a separate, later fix (see `_RECEIPT_STYLE`'s
own module-level comment) for a real printer's left-edge hardware
offset, not part of the original dead-space bug. Every
field this module rendered before this redesign still renders — this
is a restructuring of *how* fields are arranged (stacked rows instead
of side-by-side columns, flex item-rows instead of a wide `<table>`),
never a change to *which* fields exist or their underlying values.
Still grayscale-only (borders/dividers/typography carry the document,
no filled color blocks) — that principle predates and is unaffected by
this redesign."""

import base64
import html
from datetime import UTC, date, datetime
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

from app.shared.payment_method import PAYMENT_METHOD_LABELS


def _escape(value: str) -> str:
    return html.escape(value, quote=True)


def _money(amount: Decimal) -> str:
    return f"{amount:,.2f}"


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


def format_local_timestamp(moment: datetime, zone_name: str) -> str:
    """Public (unlike `_to_local_time`) specifically for
    `render_inventory_history_log`'s caller (app/modules/inventory/
    router.py) — that render function's `rows` are already-formatted
    display strings, not raw domain values, since its columns are
    caller-defined and heterogeneous across the receipt/transfer/usage
    cases it serves (see that section's own top-level docstring for why
    one shared function, not three typed ones). Every other render
    function above keeps owning its own timestamp formatting internally
    because it knows its exact fixed field set; this is the one
    deliberate exception, so the timezone-conversion logic itself still
    lives in exactly one place rather than being duplicated in the
    router."""
    return _to_local_time(moment, zone_name).strftime("%d %b %Y, %I:%M %p")


# ---------------------------------------------------------------------
# Shared 80mm receipt building blocks (2026-08-24 addition) — every one
# of the three render functions below is built from these, so the three
# documents stay genuinely identical in structure/spirit rather than
# three independently-drifting copies (which is exactly how the pre-
# redesign templates ended up inconsistent: render_invoice_receipt never
# received the header/title-box treatment its two siblings did). The
# sheet is deliberately narrower than the physical 80mm roll (42mm,
# 2026-08-24 third correction below) — @page still reserves a real 2mm
# margin on each side (fixes a print-head left offset, unrelated to
# this width), and `.sheet` itself is narrower still than what that
# leaves; see `_RECEIPT_STYLE`'s own `@page` rule and the `.sheet`
# rule's math.
#
# 2026-08-24 correction: the original redesign used 76mm here, sized as
# a rendering-only safety margin against the nominal 80mm roll width. A
# live production printer clipped everything past its real printable
# boundary (content anchored correctly on the left, lost on the right)
# — 76mm was still too wide for that printer's actual printable area.
#
# 2026-08-24 second correction (same day, real hardware round two): the
# first correction's 72mm was *still* too wide, and a second printed
# sample surfaced a distinct second problem — every line was also
# missing its first character on the left, independent of content
# width. That symptom matches a real print-head/hardware left offset
# (the physical head's true starting position sits a couple mm inboard
# of where the page's reported left edge is) — not something an
# internal-content safety margin can fix, since that margin only
# protects against *this document's own* content running wide; it does
# nothing about the printer itself starting to draw a couple mm late.
# `@page`'s own `margin` is the right tool for that specific problem —
# it is a real page-geometry inset the print engine is bound to honor,
# unlike `.sheet` merely sitting centered inside a wider flex body
# (which is a layout choice, not a guarantee nothing renders further
# left or right than intended). `.sheet` is *also* narrowed further on
# top of that margin.
#
# 2026-08-24 third correction (same day, real hardware round three): a
# fresh physical test confirmed the left-offset fix above works
# correctly on real hardware, and confirmed the printer's driver has
# two paper-size profiles reception staff might have selected ("58 x
# 297mm" and "80 x 297mm") that behave *differently* even on the same
# physical 80mm roll — the 58mm profile now prints cleanly (most likely
# because that profile scales the whole declared 80mm page down to
# fit, which incidentally also shrinks any residual overshoot), while
# the 80mm profile (no such scaling, since the declared and selected
# widths already match) still clipped real values on the right: an MR
# number, a phone number, and an amount each lost several characters
# off their end. Reverse-engineered from the exact reported clipped
# text (full string width vs. shown-substring width, at this module's
# own `.row .value` font — see this module's own scratchpad
# verification script for the full working) across all three reported
# values, the printer's *real* usable printable boundary under the
# 80mm profile lands at roughly 65.5-67mm from the physical left edge
# — meaningfully less than the ~72mm this document's own right-hand
# values were reaching under the second correction's 68mm `.sheet`.
# Since this hospital's staff must not be relied on to pick one
# specific driver profile, the fix targets the *tighter* of the two
# real constraints: `.sheet` narrows to 42mm, landing its rightmost
# content (see the `.sheet` rule's own math) at ~59mm from the
# physical edge — roughly 6.5-7mm inside even the more conservative end
# of that reverse-engineered boundary, a real margin rather than
# another single-digit-mm trim (a still-narrower 36mm was tried first
# for maximum safety margin, then set aside for a real, separate
# reason — see the `.sheet` rule's own comment for why). `@page`'s own
# margin is left unchanged at 2mm this round: worked through
# algebraically (see the `.sheet` rule's own comment), a *symmetric*
# `@page` margin has no effect on where a centered `.sheet` actually
# lands — increasing it shrinks the page's content area, but `.sheet`
# remains centered on the same central axis either way, so the margin
# increase that seemed like an obvious second lever turns out to be a
# no-op for this specific problem; `.sheet`'s own width is the only
# lever with a provable effect on the outcome, so it carries the entire
# correction this round rather than splitting it with an unproven
# change.
# ---------------------------------------------------------------------

_RECEIPT_STYLE = """
  :root {
    --ink: #111111;
    --ink-soft: #555555;
    --rule: #d0d0d0;
    --rule-strong: #111111;
  }
  * { box-sizing: border-box; }
  html, body {
    margin: 0;
    padding: 0;
    font-family: 'Inter', -apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
    color: var(--ink);
    background: #eeeeee;
  }
  body {
    padding: 16px 8px;
    display: flex;
    justify-content: center;
  }
  /* .sheet width math (2026-08-24 third correction):
     Whenever a `@page` margin is symmetric (equal left/right, as ours
     always has been) and `.sheet` is centered inside whatever content
     area that margin leaves (still true here, via the flex body
     below), `.sheet` ends up centered on the *full* 80mm page too —
     the algebra: sheet's right edge = margin + (contentArea - sheet)/2
     + sheet = margin + (80 - 2*margin - sheet)/2 + sheet, and the
     margin term cancels out completely, leaving just (80 + sheet) / 2.
     That means changing `@page`'s margin, on its own, does not move
     where `.sheet` lands at all — only `.sheet`'s own width does. This
     is why this round's whole correction lives here, not in `@page`.

     Second correction's 68mm put .sheet's right edge at
     (80 + 68) / 2 = 74mm, and its own 2mm right padding put the
     rightmost real content (a phone number, an MR number, an amount)
     at ~72mm from the physical left edge. A live "80mm" printer-driver
     profile still clipped those values — reverse-engineered from the
     exact reported clipped text (see this module's own top-level
     comment), that profile's *real* usable printable boundary lands
     around 65.5-67mm, not the ~78mm this design assumed. 68mm was
     still too wide for it by a real margin, not a rounding error.

     42mm puts .sheet's right edge at (80 + 42) / 2 = 61mm, and its
     rightmost content at ~59mm (61mm - the 2mm right padding below) —
     roughly 6.5-7mm inside even the more conservative end of that
     reverse-engineered boundary (a real, solid margin — compare to the
     ~0mm the previous 68mm design actually had in practice, despite
     modelling a healthy-looking "7.97mm" under this module's own
     content-area-based check at the time; see that check's own updated
     comment for why it cannot be trusted as an absolute predictor,
     only as an internal self-consistency check). A pure worst-case-
     safety calculation alone would have pushed narrower still (down to
     ~36mm, doubling that buffer) — tried first, then set aside: at
     36mm, realistic long values (a 12-character phone number, a
     53-character procedure name, the receipt's own date row) wrapped
     onto two or three short lines apiece, including the title box and
     the bottom-line total row itself — a real professionalism
     regression the hospital also explicitly cares about, not just
     reliability. 42mm
     was chosen by comparing rendered samples at several widths side by
     side (36/42/48/54mm) and picking the narrowest one at which every
     tested value/label still reads as a normal single-line receipt row
     (only the longer date/time value wraps, which real receipts
     routinely do). Content width narrows from ~63.5mm to ~37.5mm
     (42 - 2*2mm padding - ~0.5mm for the two 1px borders) — still
     comfortable for every specific value that was actually reported
     clipped (a phone number, an MR-prefixed number, a six-figure
     amount all measure under 22mm unwrapped at this module's own font
     sizes, verified directly). */
  .sheet {
    width: 42mm;
    background: #ffffff;
    border: 1px solid #dddddd;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
    padding: 3mm 2mm 4mm;
  }

  /* ---------- Header — stacked/centered, not the old 3-column grid,
     since there is no room at 42mm for a logo, a centered name, and a
     right-aligned contact block to sit side by side. ---------- */
  .header {
    display: flex;
    flex-direction: column;
    align-items: center;
    text-align: center;
  }
  .logo {
    height: 30px;
    width: auto;
    object-fit: contain;
    margin-bottom: 3px;
  }
  .identity .name {
    font-size: 12.5px;
    font-weight: 800;
    letter-spacing: 0.3px;
    text-transform: uppercase;
    margin: 0;
    line-height: 1.3;
  }
  .identity .tagline {
    margin-top: 2px;
    font-size: 8px;
    font-weight: 600;
    letter-spacing: 0.8px;
    text-transform: uppercase;
    color: var(--ink-soft);
  }
  .contact-block {
    margin-top: 5px;
    font-size: 8px;
    line-height: 1.55;
    color: var(--ink-soft);
  }
  .contact-block strong { color: var(--ink); font-weight: 600; }
  .header-rule { border: none; border-top: 1.5px solid var(--rule-strong); margin: 7px 0 8px; }

  /* ---------- Title box — label above token (stacked), not
     side-by-side: a long label plus a token both fit comfortably at
     42mm only when stacked, and stacking reads like a real ticket
     stub. Monospace on the token now applies uniformly across all
     three documents (previously only the medicine slip had it). ---------- */
  .title-box {
    text-align: center;
    border: 1px solid var(--rule-strong);
    padding: 5px 8px;
    margin-bottom: 9px;
  }
  .title-box .label {
    font-size: 9.5px;
    font-weight: 700;
    letter-spacing: 1.5px;
    text-transform: uppercase;
  }
  .title-box .token {
    display: block;
    margin-top: 2px;
    font-size: 14px;
    font-weight: 800;
    letter-spacing: 0.5px;
    font-family: 'Courier New', Consolas, monospace;
  }

  /* ---------- Reference sections — a stacked column of label/value
     rows, one section at a time (Patient Information, then Visit
     Details, ...), never the old 2-column .body-grid. A dashed rule
     between sections is the standard receipt convention for a soft
     block break (a heavier solid rule is reserved for the totals
     transition below, which carries more weight). ---------- */
  .section { padding-top: 8px; margin-top: 8px; border-top: 1px dashed var(--rule); }
  .section:first-child { padding-top: 0; margin-top: 0; border-top: none; }
  /* .items is always a peer of .section, never the first block on the
     sheet — same divider treatment, kept as its own single class
     (rather than "section items" on one element) so it stays a plain,
     unambiguous marker for "this is the item list", matching the
     class name this module has always used for it. */
  .items { padding-top: 8px; margin-top: 8px; border-top: 1px dashed var(--rule); }
  .section-heading {
    font-size: 9.5px;
    font-weight: 700;
    letter-spacing: 1px;
    text-transform: uppercase;
    margin-bottom: 4px;
  }
  .row {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    gap: 8px;
    padding: 2px 0;
  }
  .row .label {
    font-size: 9px;
    font-weight: 500;
    color: var(--ink-soft);
    flex-shrink: 0;
  }
  .row .value {
    /* min-width: 0 (2026-08-24 addition) is a defensive belt-and-
       braces alongside word-break: break-word above — a flex item's
       default min-width is "auto" (its content's own minimum size),
       which on some engines can still keep a long unbroken value
       (a phone number, an MR number) from shrinking/wrapping as far
       as space actually allows; explicit min-width: 0 removes that
       floor so .row's space-between layout can never push .value
       past the sheet's right edge, matching this row's own reported
       clipped-value symptom on real hardware (see this module's own
       top-level and _RECEIPT_STYLE comments for the full incident). */
    min-width: 0;
    font-size: 9.5px;
    font-weight: 700;
    text-align: right;
    word-break: break-word;
  }

  /* ---------- Item rows — replaces every wide multi-column layout
     (the medicine slip's old five-field row most of all): each item is
     its own flex row, name left (wrapping naturally to a second line
     if long, rather than a cramped cell forcing an ellipsis or a
     squeezed column), amount right, pinned to the top so a wrapped
     name never pushes the amount out of alignment. A second, smaller
     muted line under the name (.item-meta) carries whatever else that
     line item needs — quantity/unit price/category for medicines —
     the same "name on one line, qty x price on the next" shape real
     pharmacy receipts use. ---------- */
  .item-row {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 8px;
    padding: 3.5px 0;
    border-bottom: 1px dotted var(--rule);
  }
  .item-row:last-child { border-bottom: none; }
  .item-main { flex: 1; min-width: 0; }
  .item-name {
    font-size: 9.5px;
    font-weight: 600;
    word-break: break-word;
  }
  .item-meta {
    font-size: 8px;
    color: var(--ink-soft);
    margin-top: 1px;
  }
  .item-amount {
    flex-shrink: 0;
    font-size: 9.5px;
    font-weight: 700;
    text-align: right;
    white-space: nowrap;
  }

  /* ---------- Totals — replaces the old table footer: stacked rows,
     a heavier rule ahead of the block (the "final answer" transition
     deserves more visual weight than the dashed section breaks above),
     and the bottom-line and outstanding-balance rows get real size/
     weight emphasis rather than just a bold cell. ---------- */
  .totals {
    margin-top: 5px;
    padding-top: 6px;
    border-top: 1px dashed var(--rule-strong);
  }
  .total-row {
    display: flex;
    justify-content: space-between;
    padding: 2px 0;
    font-size: 9.5px;
    font-weight: 600;
    color: var(--ink-soft);
  }
  .total-row .amount { color: var(--ink); font-weight: 700; }
  .total-row.pending { font-weight: 800; color: var(--ink); }
  .total-row.pending .amount { font-size: 11px; }
  .net-row {
    display: flex;
    justify-content: space-between;
    padding-top: 6px;
    margin-top: 4px;
    border-top: 2px solid var(--rule-strong);
    font-size: 13px;
    font-weight: 800;
    color: var(--ink);
  }
  .paid-via-row {
    font-size: 8px;
    color: var(--ink-soft);
    padding-top: 3px;
  }

  /* ---------- Payment strip — the registration slip's own conditional
     "genuine outstanding balance" callout (see that function's own
     docstring); a standalone block rather than folded into .totals
     since it is a rarer, worth-calling-out case, not a routine row
     set. Stacked rows now, not the old 3-column grid. ---------- */
  .payment-strip {
    margin-top: 6px;
    padding-top: 6px;
    border-top: 1.5px solid var(--rule-strong);
  }
  .payment-row {
    display: flex;
    justify-content: space-between;
    padding: 2px 0;
  }
  .payment-row .payment-label {
    font-size: 8.5px;
    font-weight: 700;
    letter-spacing: 0.4px;
    text-transform: uppercase;
    color: var(--ink-soft);
  }
  .payment-row .payment-value { font-size: 9.5px; font-weight: 700; }
  .payment-row.pending .payment-value { font-size: 11.5px; font-weight: 800; }

  /* ---------- Note ---------- */
  .note {
    margin-top: 9px;
    padding-top: 7px;
    border-top: 1px dashed var(--rule);
  }
  .note .note-label {
    font-size: 8.5px;
    font-weight: 700;
    letter-spacing: 1.2px;
    text-transform: uppercase;
    margin-bottom: 2px;
  }
  .note .note-text {
    font-size: 8px;
    line-height: 1.55;
    color: var(--ink-soft);
  }

  /* ---------- Print — `size: 80mm auto` is the fix for the original
     reported bug: the previous rule declared a fixed A-series page
     length regardless of how short the content is, which is exactly
     what left a large blank trailing section on the roll below the
     receipt. `auto` sizes the printed page to the content's own
     height instead.
     `margin: 0 2mm` (2026-08-24 second correction, was `margin: 0`) is
     a separate, later fix for a distinct problem: a real printer's
     print head starts drawing a couple mm inboard of where the page's
     reported left edge is, clipping the first character of every
     line regardless of content width. A real `@page` margin is a page-
     geometry inset the print engine must honor, unlike `.sheet`
     merely sitting centered in a wider flex body (a layout choice, not
     a guarantee) — see `_RECEIPT_STYLE`'s own module-level comment
     for the full incident, and the `.sheet` rule above for how its own
     width was narrowed further on top of this margin. ---------- */
  @page { size: 80mm auto; margin: 0 2mm; }
  @media print {
    * {
      print-color-adjust: exact !important;
      -webkit-print-color-adjust: exact !important;
      color: #000000 !important;
    }
    html, body {
      background: #ffffff !important;
      padding: 0 !important;
      color: #000000 !important;
    }
    .sheet {
      border: none !important;
      box-shadow: none !important;
      color: #000000 !important;
      background: #ffffff !important;
    }
    .logo { filter: grayscale(1); }
  }
"""


def _row(label: str, value: str) -> str:
    return (
        f'<div class="row"><span class="label">{_escape(label)}</span>'
        f'<span class="value">{_escape(value)}</span></div>'
    )


def _header_html(hospital_name: str) -> str:
    """The masthead every one of the three documents opens with —
    logo, hospital identity, contact block, then a rule. Centered/
    stacked (not the old 3-column grid) — see `_RECEIPT_STYLE`'s own
    `.header` comment."""
    logo_data_uri = _logo_data_uri()
    logo_html = (
        f'<img class="logo" src="{logo_data_uri}" alt="{_escape(hospital_name)} logo">'
        if logo_data_uri
        else ""
    )
    return f"""
    <div class="header">
      {logo_html}
      <div class="identity">
        <p class="name">{_escape(hospital_name)}</p>
        <div class="tagline">Gynecology &bull; Maternity &bull; Women's Care</div>
      </div>
      <div class="contact-block">
        <div>Shalimar Link Road, Lahore</div>
        <div><strong>International Standard Healthcare</strong></div>
        <div>Open 24 Hours &middot; 0300-0430009</div>
      </div>
    </div>
    <hr class="header-rule">
"""


def _title_box_html(label: str, token: str) -> str:
    return f"""
    <div class="title-box">
      <span class="label">{_escape(label)}</span>
      <span class="token">{_escape(token)}</span>
    </div>
"""


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
    payment_methods: list[str] | None = None,
) -> str:
    """Renders a print-ready HTML receipt for one Invoice. Every dynamic
    value is HTML-escaped — this document assembles patient- and
    doctor-supplied free text (names, procedure, descriptions) directly
    into markup, so unescaped interpolation would be a stored-XSS vector
    the moment this HTML is ever opened in a browser (which is its
    entire purpose).

    2026-08-24 redesign: brought up to the same shared 80mm receipt
    layout `render_registration_slip`/`render_medicine_bill_receipt`
    already use (see `_RECEIPT_STYLE`'s own module-level docstring) —
    previously this was the one template left on a plain Arial/no-logo/
    no-title-box layout while its two siblings got the grayscale-receipt
    treatment. `visit_queue_token` (already a parameter) is now the
    prominent title-box token, matching what the other two documents
    show there; `invoice_id` (a full UUID, far too long for that slot)
    moves to a shortened reference row instead, the same fallback
    shortening `render_medicine_bill_receipt` already uses for a legacy
    bill's own id (`bill_id.split("-")[0].upper()`).

    Still leads with the four-line mental model every workspace screen
    shares (2026-08-19 revision, adding the third line below — the
    original three-line version left the actual post-discount total
    only implied by Received+Pending, never shown as its own line):
    **Total Amount** (the pre-discount subtotal — `total_amount` is
    already post-discount on the stored Invoice, see
    BillingService.generate_invoice's docstring, so this recovers it as
    `total_amount + discount_amount` rather than storing it twice),
    **Discount** (only shown when actually applied — `discount_amount
    == 0` means the row is fully absent, never a zero line), **Net
    Amount** (the actual bottom-line total after discount — exactly the
    stored `total_amount`, always shown), then **Received**/**Pending**
    (`amount_paid` / `total_amount - amount_paid`).

    `payment_methods` (2026-08-19 addition) is the caller-computed list
    of *distinct* methods across every `InvoicePayment` on this Invoice,
    in first-payment order (see billing/router.py's `print_invoice`,
    which builds it with `dict.fromkeys` rather than a plain `set` to
    preserve that order) — rendered as one "Paid via: Cash, JazzCash"
    summary line next to Received, not a full itemized per-payment
    breakdown. Omitted entirely when empty (nothing paid yet)."""
    pending = total_amount - amount_paid
    subtotal = total_amount + discount_amount
    short_invoice_id = invoice_id.split("-")[0].upper()

    item_rows = "".join(
        f"""
      <div class="item-row">
        <div class="item-main"><div class="item-name">{_escape(description)}</div></div>
        <div class="item-amount">{_money(amount)}</div>
      </div>"""
        for description, amount in line_items
    )

    discount_row = ""
    if discount_amount > 0:
        discount_label = "Discount"
        if discount_reason:
            discount_label = f"Discount ({_escape(discount_reason)})"
        discount_row = (
            f'<div class="total-row"><span>{discount_label}</span>'
            f'<span class="amount">-{_money(discount_amount)}</span></div>'
        )
    paid_via_row = ""
    if payment_methods:
        labels = ", ".join(PAYMENT_METHOD_LABELS.get(method, method) for method in payment_methods)
        paid_via_row = f'<div class="paid-via-row">Paid via: {_escape(labels)}</div>'

    reference_rows = "".join(
        [
            _row("Patient", f"{patient_full_name} (MR: {patient_mr_number})"),
            _row("Procedure", visit_procedure),
            _row("Invoice Ref", short_invoice_id),
            _row("Status", invoice_status),
            _row("Date", invoice_created_at.strftime("%Y-%m-%d %H:%M")),
        ]
    )

    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Invoice Receipt — {_escape(visit_queue_token)}</title>
<style>
{_RECEIPT_STYLE}
</style>
</head>
<body>
  <div class="sheet">
    {_header_html(hospital_name)}
    {_title_box_html("Invoice Receipt", visit_queue_token)}

    <div class="section">
      {reference_rows}
    </div>

    <div class="section">
      <div class="section-heading">Charges</div>
      {item_rows}
      <div class="totals">
        <div class="total-row"><span>Total Amount</span><span class="amount">{_money(subtotal)}</span></div>
        {discount_row}
        <div class="net-row"><span>Net Amount</span><span>{_money(total_amount)}</span></div>
        <div class="total-row"><span>Received</span><span class="amount">{_money(amount_paid)}</span></div>
        {paid_via_row}
        <div class="total-row pending"><span>Pending</span><span class="amount">{_money(pending)}</span></div>
      </div>
    </div>
  </div>
</body>
</html>
"""


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
    visit_discount_amount: Decimal = Decimal("0.00"),
    visit_discount_reason: str | None = None,
    visit_procedure_items: list[tuple[str, Decimal]] | None = None,
    visit_amount_paid: Decimal | None = None,
    visit_payment_status: str | None = None,
) -> str:
    """Renders Reception's fast-registration slip (Phase 6
    fast-registration §6/§7) — printed immediately after a visit is
    registered, before any doctor may have been assigned yet.

    Layout (2026-08-24 redesign): this hospital prints exclusively on an
    80mm continuous-roll thermal printer, not A4 — see this module's own
    top-level docstring and `_RECEIPT_STYLE` for the shared 80mm receipt
    layout every one of the three Central Print Service templates now
    uses. Every field this slip has ever shown still renders; only the
    arrangement changed (stacked reference sections instead of a
    2-column grid, flex item-rows instead of a `<table>`).

    `assigned_doctor_full_name` is deliberately accepted but not
    rendered — the attending doctor is intentionally omitted from this
    slip for now (a later revision adds it back); the parameter stays
    in the signature so the caller (reception/router.py) and the data
    it already resolves are untouched.

    `display_timezone` is an IANA zone name (e.g. `"Asia/Karachi"`,
    supplied by the caller from `settings.display_timezone`) — see
    `_to_local_time`'s docstring for why `visit_created_at` must be
    converted, not formatted as-is.

    `visit_procedure_items` (2026-08-21 addition) is the hybrid switch
    between this slip's two possible layouts — a real, confirmed design
    decision, not a stopgap: a visit registered before 2026-08-21 has
    none at all (permanently — see app/modules/visits/models.py's
    `VisitProcedureItem` docstring) and renders the legacy shape — a
    single "Procedure" row, a single "Amount" row, plus Discount/Net
    Amount rows when `visit_discount_amount > 0`. A visit registered
    from 2026-08-21 onward always has at least one and instead renders
    a full itemized Procedure/Amount item list, with the "Visit
    Details" section shrinking to just "Registered On" —
    `visit_procedure`/`visit_amount` are still accepted and still
    correct in this case (see that column's own docstring) but are not
    displayed as a single row; the real, itemized breakdown is.

    `visit_discount_amount`/`visit_discount_reason` (2026-08-19
    addition) mirror `render_invoice_receipt`'s/
    `render_medicine_bill_receipt`'s identical Total/Discount/Net
    Amount convention either way: `visit_amount` is always already
    post-discount (see VisitService.register_visit's docstring), so the
    pre-discount subtotal is always recovered as `visit_amount +
    visit_discount_amount`. When `visit_discount_amount == 0` (the
    common case), only a single Amount/Net-Amount figure renders either
    way — the Discount row appears only when a discount was actually
    applied.

    `visit_amount_paid`/`visit_payment_status` (2026-08-22 addition)
    are `None` for every visit that predates registration-charge
    payment tracking (see app/modules/visits/models.py's `Visit.
    payment_status` docstring) — in that case, and whenever the visit
    is fully `paid`, this slip renders with no payment strip at all (a
    deliberately conservative choice — this slip only ever gains the
    extra strip when there is a real, non-zero balance still owed).
    Only when `payment_status` is `partially_paid` (a genuine
    outstanding balance) does a "Total / Received / Pending" strip
    appear below the Patient/Visit Details section (and below the
    itemized list, when present) — stacked rows, not the old 3-column
    grid (see `_RECEIPT_STYLE`'s own `.payment-strip` comment)."""
    registered_on = _to_local_time(visit_created_at, display_timezone).strftime(
        "%d %b %Y, %I:%M %p"
    )
    is_itemized = bool(visit_procedure_items)

    # A genuine outstanding balance — never shown for a visit that
    # predates payment tracking (`visit_payment_status is None`) or is
    # already fully `paid` (whether settled in one payment or several;
    # printing always reflects the visit's *current* state, never its
    # payment history) — see this function's own docstring above.
    pending_amount = None
    if visit_amount_paid is not None and visit_payment_status == "partially_paid":
        pending_amount = visit_amount - visit_amount_paid

    payment_strip = ""
    if pending_amount is not None and pending_amount > 0:
        payment_strip = f"""
    <div class="payment-strip">
      <div class="payment-row"><span class="payment-label">Total</span><span class="payment-value">{_money(visit_amount)}</span></div>
      <div class="payment-row"><span class="payment-label">Received</span><span class="payment-value">{_money(visit_amount_paid)}</span></div>
      <div class="payment-row pending"><span class="payment-label">Pending</span><span class="payment-value">{_money(pending_amount)}</span></div>
    </div>
"""

    patient_rows = "".join(
        [
            _row("MR Number", patient_mr_number),
            _row("Patient Name", patient_full_name),
            _row("Age", f"{patient_age_years} years"),
            _row("Contact Number", patient_phone_number),
        ]
    )
    subtotal = visit_amount + visit_discount_amount

    if is_itemized:
        # The itemized layout — "Visit Details" shrinks to just
        # Registered On; the real Procedure/Amount breakdown lives in
        # the item list below instead (see this function's own
        # docstring).
        visit_rows = _row("Registered On", registered_on)

        item_rows = "".join(
            f"""
      <div class="item-row">
        <div class="item-main"><div class="item-name">{_escape(name)}</div></div>
        <div class="item-amount">{_money(amount)}</div>
      </div>"""
            for name, amount in visit_procedure_items
        )
        discount_row = ""
        if visit_discount_amount > 0:
            discount_label = "Discount"
            if visit_discount_reason:
                discount_label = f"Discount ({_escape(visit_discount_reason)})"
            discount_row = (
                f'<div class="total-row"><span>{discount_label}</span>'
                f'<span class="amount">-{_money(visit_discount_amount)}</span></div>'
            )
        items_section = f"""
    <div class="items">
      <div class="section-heading">Procedures</div>
      {item_rows}
      <div class="totals">
        <div class="total-row"><span>Total Amount</span><span class="amount">{_money(subtotal)}</span></div>
        {discount_row}
        <div class="net-row"><span>Net Amount</span><span>{_money(visit_amount)}</span></div>
      </div>
    </div>
"""
    else:
        # The legacy layout — same fields this template has always
        # shown for a pre-2026-08-21 visit, now inside the shared
        # stacked-section container instead of the old 2-column grid.
        visit_row_items = [
            _row("Procedure", visit_procedure),
            _row("Amount", _money(subtotal)),
        ]
        if visit_discount_amount > 0:
            discount_label = "Discount"
            if visit_discount_reason:
                discount_label = f"Discount ({visit_discount_reason})"
            visit_row_items.append(_row(discount_label, f"-{_money(visit_discount_amount)}"))
            visit_row_items.append(_row("Net Amount", _money(visit_amount)))
        visit_row_items.append(_row("Registered On", registered_on))
        visit_rows = "".join(visit_row_items)
        items_section = ""

    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Registration Slip — {_escape(visit_queue_token)}</title>
<style>
{_RECEIPT_STYLE}
</style>
</head>
<body>
  <div class="sheet">
    {_header_html(hospital_name)}
    {_title_box_html("Registration Slip", visit_queue_token)}

    <div class="section">
      <div class="section-heading">Patient Information</div>
      {patient_rows}
    </div>
    <div class="section">
      <div class="section-heading">Visit Details</div>
      {visit_rows}
    </div>
    {items_section}{payment_strip}
    <div class="note">
      <div class="note-label">Note</div>
      <div class="note-text">
        Please retain this registration slip for your appointment and billing records.
        Present it at the reception desk during your visit for faster check-in.
      </div>
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
    bill_queue_token: str | None,
    patient_full_name: str | None,
    patient_age_years: int | None,
    patient_phone_number: str | None,
    line_items: list[tuple[str, str, int, Decimal, Decimal]],
    total_amount: Decimal,
    amount_paid: Decimal,
    discount_amount: Decimal = Decimal("0.00"),
    discount_reason: str | None = None,
    payment_methods: list[str] | None = None,
) -> str:
    """Renders the Pharmacy module's medicine bill slip — shares the
    exact 80mm receipt layout the other two Central Print Service
    templates use (see this module's own top-level docstring and
    `_RECEIPT_STYLE`).

    `bill_queue_token` (2026-08-20 addition, replacing the removed
    `visit_queue_token`/`patient_mr_number` parameters — see
    app/modules/pharmacy/models.py's `MedicineBill.queue_token`
    docstring for the full mechanism) is this bill's *own* number, from
    the same unified sequence Visit uses — never the linked Visit's own
    token, since every bill draws its own fresh value at creation.
    `None` only for a bill that predates this feature, in which case
    the title-box falls back to the pre-existing `MED-<uuid fragment>`
    display.

    `patient_full_name`/`patient_age_years`/`patient_phone_number` are
    all `None` for a standalone walk-in sale with no linked Visit (see
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
    was billed, never re-reads the live price list. 2026-08-24 redesign:
    the old 5-column table (Medicine/Category/Qty/Unit Price/Line Total)
    cannot fit legibly at 42mm — each item is now its own row, the
    medicine name on its own line (wrapping naturally if long) and a
    small muted second line underneath carrying category/quantity/unit
    price (`"Tablet · 2 × 50.00"`), with the line total right-aligned
    against the name — the same shape a real pharmacy thermal receipt
    uses. All five original fields still render; only the arrangement
    changed. Each line's own `line_total` is never affected by
    `discount_amount` — a bill-level discount is applied once, below the
    item list, exactly like `render_invoice_receipt`'s identical Total
    Amount / Discount / Net Amount footer. `discount_amount == 0` means
    the Discount row is fully absent, never a zero line, same convention
    as the invoice receipt's. `total_amount` is already post-discount
    (the pre-discount subtotal is recovered as `total_amount +
    discount_amount`, same as the invoice receipt) — `Net Amount` always
    shows it, then `Received`/`Pending` follow: a bill freshly created
    and not yet paid renders `Received: 0.00` / `Pending` equal to the
    (post-discount) total, exactly like an unpaid Invoice would, rather
    than silently implying the sale was already settled.

    `payment_methods` (2026-08-19 addition) mirrors
    `render_invoice_receipt`'s identical parameter exactly — the
    caller-computed list of distinct methods across every
    `MedicineBillPayment` on this bill, in first-payment order,
    rendered as one "Paid via: Cash, JazzCash" summary line next to
    Received. Omitted entirely when empty (nothing paid yet)."""
    billed_on = _to_local_time(bill_created_at, display_timezone).strftime("%d %b %Y, %I:%M %p")
    pending = total_amount - amount_paid
    subtotal = total_amount + discount_amount
    short_bill_id = bill_id.split("-")[0].upper()
    # This bill's own token if it has one (every bill created from
    # 2026-08-20 onward does); the old UUID-fragment display only for
    # bills that predate the unified sequence — see this function's
    # own docstring.
    token_display = bill_queue_token or f"MED-{short_bill_id}"

    reference_section = ""
    if patient_full_name is not None:
        reference_rows = "".join(
            [
                _row("Patient Name", patient_full_name),
                _row(
                    "Age",
                    f"{patient_age_years} years" if patient_age_years is not None else "—",
                ),
                _row("Contact Number", patient_phone_number or "—"),
                _row("Billed On", billed_on),
            ]
        )
        reference_section = f"""
    <div class="section">
      <div class="section-heading">Patient / Visit Reference</div>
      {reference_rows}
    </div>
"""
    else:
        reference_section = f"""
    <div class="section">
      <div class="section-heading">Sale Reference</div>
      {_row("Sale Type", "Walk-in (no visit on file)")}
      {_row("Billed On", billed_on)}
    </div>
"""

    item_rows = "".join(
        f"""
      <div class="item-row">
        <div class="item-main">
          <div class="item-name">{_escape(name)}</div>
          <div class="item-meta">{_escape(category.title())} &middot; {quantity} &times; {_money(unit_price)}</div>
        </div>
        <div class="item-amount">{_money(line_total)}</div>
      </div>"""
        for name, category, quantity, unit_price, line_total in line_items
    )

    discount_row = ""
    if discount_amount > 0:
        discount_label = "Discount"
        if discount_reason:
            discount_label = f"Discount ({_escape(discount_reason)})"
        discount_row = (
            f'<div class="total-row"><span>{discount_label}</span>'
            f'<span class="amount">-{_money(discount_amount)}</span></div>'
        )
    paid_via_row = ""
    if payment_methods:
        labels = ", ".join(PAYMENT_METHOD_LABELS.get(method, method) for method in payment_methods)
        paid_via_row = f'<div class="paid-via-row">Paid via: {_escape(labels)}</div>'

    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Medicine Slip — {_escape(token_display)}</title>
<style>
{_RECEIPT_STYLE}
</style>
</head>
<body>
  <div class="sheet">
    {_header_html(hospital_name)}
    {_title_box_html("Medicine Slip", token_display)}

    {reference_section}

    <div class="items">
      <div class="section-heading">Items</div>
      {item_rows}
      <div class="totals">
        <div class="total-row"><span>Total Amount</span><span class="amount">{_money(subtotal)}</span></div>
        {discount_row}
        <div class="net-row"><span>Net Amount</span><span>{_money(total_amount)}</span></div>
        <div class="total-row"><span>Received</span><span class="amount">{_money(amount_paid)}</span></div>
        {paid_via_row}
        <div class="total-row pending"><span>Pending</span><span class="amount">{_money(pending)}</span></div>
      </div>
    </div>

    <div class="note">
      <div class="note-label">Note</div>
      <div class="note-text">
        Please retain this medicine slip for your records. Prices reflect the pharmacy
        price list at the time of this sale and are not affected by any later change.
      </div>
    </div>
  </div>
</body>
</html>
"""


def render_lab_bill_receipt(
    *,
    hospital_name: str,
    display_timezone: str,
    bill_id: str,
    bill_created_at: datetime,
    bill_queue_token: str | None,
    patient_full_name: str | None,
    patient_age_years: int | None,
    patient_phone_number: str | None,
    line_items: list[tuple[str, str, Decimal]],
    total_amount: Decimal,
    amount_paid: Decimal,
    discount_amount: Decimal = Decimal("0.00"),
    discount_reason: str | None = None,
    payment_methods: list[str] | None = None,
) -> str:
    """Renders the Laboratory Billing module's lab bill slip — shares
    the exact 80mm receipt layout every other Central Print Service
    template uses (see this module's own top-level docstring and
    `_RECEIPT_STYLE`), and mirrors `render_medicine_bill_receipt`'s own
    shape almost exactly, with the one difference that module's own
    design already carries: no quantity.

    `bill_queue_token` mirrors `MedicineBill.queue_token`'s identical
    mechanism (same unified Postgres sequence) — every LabBill gets a
    real token from creation (see that model's own docstring), so the
    `LAB-<uuid fragment>` fallback below only exists for schema-shape
    symmetry, never expected to actually render in practice.

    `patient_full_name`/`patient_age_years`/`patient_phone_number` are
    all `None` for a standalone walk-in sale with no linked Patient
    (confirmed design — LabBill.patient_id is a direct Patient link,
    never Visit-mediated, see app/modules/lab/models.py's own
    docstring) — the patient reference section is simply omitted in
    that case, same convention `render_medicine_bill_receipt` follows
    for its own walk-in case.

    `line_items` is `(lab_test_name, category, price)` triples, already
    snapshotted at billing time (see `LabBillItem`'s docstring) — this
    function renders exactly what was billed, never re-reads the live
    price list. Unlike the medicine slip's own item rows, there is no
    quantity/unit-price sub-line to show (confirmed design: a lab test
    is a service performed, not a countable dispensed unit) — each row
    is just the test's name (with its category as a small muted second
    line) and its price, right-aligned. Two rows for the same test
    (ordered twice) render as two independent rows, exactly as billed.

    Discount/Total/Net/Received/Pending footer, `payment_methods`
    handling, and the `discount_amount == 0` "row fully absent" rule
    are all identical to `render_medicine_bill_receipt`'s own — see
    that function's docstring for the full rationale."""
    billed_on = _to_local_time(bill_created_at, display_timezone).strftime("%d %b %Y, %I:%M %p")
    pending = total_amount - amount_paid
    subtotal = total_amount + discount_amount
    short_bill_id = bill_id.split("-")[0].upper()
    token_display = bill_queue_token or f"LAB-{short_bill_id}"

    reference_section = ""
    if patient_full_name is not None:
        reference_rows = "".join(
            [
                _row("Patient Name", patient_full_name),
                _row(
                    "Age",
                    f"{patient_age_years} years" if patient_age_years is not None else "—",
                ),
                _row("Contact Number", patient_phone_number or "—"),
                _row("Billed On", billed_on),
            ]
        )
        reference_section = f"""
    <div class="section">
      <div class="section-heading">Patient Reference</div>
      {reference_rows}
    </div>
"""
    else:
        reference_section = f"""
    <div class="section">
      <div class="section-heading">Sale Reference</div>
      {_row("Sale Type", "Walk-in (no patient on file)")}
      {_row("Billed On", billed_on)}
    </div>
"""

    item_rows = "".join(
        f"""
      <div class="item-row">
        <div class="item-main">
          <div class="item-name">{_escape(name)}</div>
          <div class="item-meta">{_escape(category.title())}</div>
        </div>
        <div class="item-amount">{_money(price)}</div>
      </div>"""
        for name, category, price in line_items
    )

    discount_row = ""
    if discount_amount > 0:
        discount_label = "Discount"
        if discount_reason:
            discount_label = f"Discount ({_escape(discount_reason)})"
        discount_row = (
            f'<div class="total-row"><span>{discount_label}</span>'
            f'<span class="amount">-{_money(discount_amount)}</span></div>'
        )
    paid_via_row = ""
    if payment_methods:
        labels = ", ".join(PAYMENT_METHOD_LABELS.get(method, method) for method in payment_methods)
        paid_via_row = f'<div class="paid-via-row">Paid via: {_escape(labels)}</div>'

    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Lab Slip — {_escape(token_display)}</title>
<style>
{_RECEIPT_STYLE}
</style>
</head>
<body>
  <div class="sheet">
    {_header_html(hospital_name)}
    {_title_box_html("Lab Slip", token_display)}

    {reference_section}

    <div class="items">
      <div class="section-heading">Tests</div>
      {item_rows}
      <div class="totals">
        <div class="total-row"><span>Total Amount</span><span class="amount">{_money(subtotal)}</span></div>
        {discount_row}
        <div class="net-row"><span>Net Amount</span><span>{_money(total_amount)}</span></div>
        <div class="total-row"><span>Received</span><span class="amount">{_money(amount_paid)}</span></div>
        {paid_via_row}
        <div class="total-row pending"><span>Pending</span><span class="amount">{_money(pending)}</span></div>
      </div>
    </div>

    <div class="note">
      <div class="note-label">Note</div>
      <div class="note-text">
        Please retain this lab slip for your records. Prices reflect the lab test price
        list at the time of this sale and are not affected by any later change.
      </div>
    </div>
  </div>
</body>
</html>
"""


# ---------------------------------------------------------------------
# A4 report layout (2026-08-26 addition, Ward/Emergency Inventory
# Management module) — genuinely different in kind from every document
# above: multi-row tabular reports, primarily meant to be saved as a
# PDF via the browser's own Print dialog "Save as PDF" destination
# (investigated before building: no PDF-generation library exists in
# this project's dependencies, and this module's own top-level
# docstring already committed to "the browser rasterizes, this service
# only ever renders HTML" — adding a second, disconnected binary-PDF
# pipeline for these two documents alone would duplicate what the
# browser already does today for every other print in this app), with
# printing as a secondary option on the exact same document. Never the
# narrow 42mm single-column `_RECEIPT_STYLE` layout above — a real A4
# page, real `<table>` columns, letterhead-style report typography.
#
# `render_inventory_history_log` (the Inventory Manager's own filterable
# log) is deliberately ONE function serving all three of receipts/
# transfers/usage entries, not three near-identical typed functions —
# unlike `render_invoice_receipt`/`render_registration_slip`/
# `render_medicine_bill_receipt` above (which are genuinely different
# documents, with different sections), these three are structurally
# identical reports — a title, a scope description, a table, a summary
# — differing only in which columns apply. `log_type` here exists only
# to pick the title text; every column header and every cell's own
# formatting (item names, patient names, "Recorded By" names — all
# already resolved from ids to display strings) is the caller's
# responsibility (app/modules/inventory/router.py), matching this
# module's own "the owning module decides what to render" boundary.
#
# `render_inventory_daily_usage_slip` is a separate, second function —
# Vitals' own one-staff-member, one-day summary has a genuinely
# different framing (staff name + day, not a generic item/date-range
# filter) even though its content shape (a table of usage rows) is the
# same "usage" case as the log above; it shares the same low-level
# `_report_shell_html`/`_report_table_html` building blocks rather than
# duplicating them.
# ---------------------------------------------------------------------

_INVENTORY_LOG_TITLES = {
    "receipt": "Main Stock Receipt Log",
    "transfer": "Transfer to Emergency Stock Log",
    "usage": "Emergency Stock Usage Log",
}

_REPORT_STYLE = """
  :root {
    --ink: #111111;
    --ink-soft: #555555;
    --rule: #d0d0d0;
    --rule-strong: #111111;
    --header-tint: #f2f2f2;
  }
  * { box-sizing: border-box; }
  html, body {
    margin: 0;
    padding: 0;
    font-family: 'Inter', -apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
    color: var(--ink);
    background: #eeeeee;
  }
  body {
    padding: 16px;
    display: flex;
    justify-content: center;
  }
  .sheet {
    width: 100%;
    max-width: 190mm;
    background: #ffffff;
    border: 1px solid #dddddd;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
    padding: 12mm;
  }

  /* ---------- Header — logo left, identity + contact right, a
     letterhead shape rather than the receipt's centered/stacked one:
     a report is read at a desk, not torn off a till, so a wider
     side-by-side layout reads more like a real business document. ---------- */
  .report-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
  }
  .report-header .identity {
    display: flex;
    align-items: center;
    gap: 10px;
  }
  .report-header .logo {
    height: 40px;
    width: auto;
    object-fit: contain;
  }
  .report-header .name {
    font-size: 16px;
    font-weight: 800;
    letter-spacing: 0.2px;
    margin: 0;
  }
  .report-header .tagline {
    margin-top: 1px;
    font-size: 9px;
    font-weight: 600;
    letter-spacing: 0.6px;
    text-transform: uppercase;
    color: var(--ink-soft);
  }
  .report-header .contact-block {
    text-align: right;
    font-size: 9px;
    line-height: 1.5;
    color: var(--ink-soft);
  }
  .header-rule { border: none; border-top: 1.5px solid var(--rule-strong); margin: 10px 0 14px; }

  /* ---------- Title block ---------- */
  .report-title { font-size: 15px; font-weight: 800; margin: 0 0 4px; }
  .report-meta { font-size: 10px; color: var(--ink-soft); line-height: 1.7; margin-bottom: 14px; }
  .report-meta strong { color: var(--ink); font-weight: 600; }

  /* ---------- Table ---------- */
  table.report-table { width: 100%; border-collapse: collapse; font-size: 10px; }
  table.report-table thead th {
    background: var(--header-tint);
    border: 1px solid var(--rule);
    padding: 6px 8px;
    text-align: left;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.4px;
    font-size: 9px;
  }
  table.report-table td {
    border: 1px solid var(--rule);
    padding: 6px 8px;
    vertical-align: top;
  }
  table.report-table tbody tr:nth-child(even) { background: #fafafa; }
  table.report-table td.numeric, table.report-table th.numeric { text-align: right; }
  .report-empty { padding: 24px 0; text-align: center; color: var(--ink-soft); font-size: 11px; }

  /* ---------- Summary footer ---------- */
  .report-summary {
    margin-top: 12px;
    padding-top: 8px;
    border-top: 1.5px solid var(--rule-strong);
    display: flex;
    flex-wrap: wrap;
    gap: 4px 20px;
    font-size: 10px;
    font-weight: 600;
    color: var(--ink-soft);
  }
  .report-summary strong { color: var(--ink); }

  @page { size: A4; margin: 15mm; }
  @media print {
    * {
      print-color-adjust: exact !important;
      -webkit-print-color-adjust: exact !important;
    }
    html, body { background: #ffffff !important; padding: 0 !important; }
    .sheet { border: none !important; box-shadow: none !important; max-width: none; width: 100%; }
    .logo { filter: grayscale(1); }
  }
"""


def _report_table_html(
    *, column_headers: list[str], rows: list[list[str]], numeric_columns: set[int]
) -> str:
    if not rows:
        return '<p class="report-empty">No rows match this report.</p>'

    header_cells = "".join(
        f'<th class="{"numeric" if index in numeric_columns else ""}">{_escape(header)}</th>'
        for index, header in enumerate(column_headers)
    )
    body_rows = "".join(
        "<tr>"
        + "".join(
            f'<td class="{"numeric" if index in numeric_columns else ""}">{_escape(str(cell))}</td>'
            for index, cell in enumerate(row)
        )
        + "</tr>"
        for row in rows
    )
    return f"""
    <table class="report-table">
      <thead><tr>{header_cells}</tr></thead>
      <tbody>{body_rows}</tbody>
    </table>
"""


def _report_shell_html(
    *,
    hospital_name: str,
    document_title: str,
    title_text: str,
    meta_lines: list[str],
    table_html: str,
    summary_line: str,
) -> str:
    logo_data_uri = _logo_data_uri()
    logo_html = (
        f'<img class="logo" src="{logo_data_uri}" alt="{_escape(hospital_name)} logo">'
        if logo_data_uri
        else ""
    )
    meta_html = "".join(f"<div>{line}</div>" for line in meta_lines)
    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>{_escape(document_title)}</title>
<style>
{_REPORT_STYLE}
</style>
</head>
<body>
  <div class="sheet">
    <div class="report-header">
      <div class="identity">
        {logo_html}
        <div>
          <p class="name">{_escape(hospital_name)}</p>
          <div class="tagline">Gynecology &bull; Maternity &bull; Women's Care</div>
        </div>
      </div>
      <div class="contact-block">
        <div>Shalimar Link Road, Lahore</div>
        <div>Open 24 Hours &middot; 0300-0430009</div>
      </div>
    </div>
    <hr class="header-rule">

    <div class="report-title">{_escape(title_text)}</div>
    <div class="report-meta">{meta_html}</div>

    {table_html}

    <div class="report-summary">{summary_line}</div>
  </div>
</body>
</html>
"""


def render_inventory_history_log(
    *,
    hospital_name: str,
    display_timezone: str,
    log_type: str,
    generated_at: datetime,
    item_name_filter: str | None,
    start_date: date | None,
    end_date: date | None,
    column_headers: list[str],
    numeric_columns: set[int],
    rows: list[list[str]],
    total_quantity: Decimal | None,
) -> str:
    """The Inventory Manager's own filterable history log — "print
    whichever sub-tab and filters are currently active" (confirmed
    design): `log_type` selects the title only (see
    `_INVENTORY_LOG_TITLES`); every column header, every cell's already-
    resolved display string (item names, patient names, "Recorded By"
    names), and `total_quantity` (the sum of whichever numeric column is
    the row quantity, or `None` when that summary wouldn't be
    meaningful) are all supplied by the caller — see this section's own
    top-level docstring for why this one function deliberately serves
    all three receipt/transfer/usage cases rather than three duplicated
    ones."""
    title_text = _INVENTORY_LOG_TITLES[log_type]
    generated_line = f"Generated: {format_local_timestamp(generated_at, display_timezone)}"
    scope_line = f"<strong>Item:</strong> {_escape(item_name_filter or 'All Items')}"
    date_range_line = (
        "<strong>Date Range:</strong> "
        f"{start_date.isoformat() if start_date else 'Any'} to "
        f"{end_date.isoformat() if end_date else 'Any'}"
    )
    meta_lines = [scope_line, date_range_line, generated_line]

    table_html = _report_table_html(
        column_headers=column_headers, rows=rows, numeric_columns=numeric_columns
    )
    summary_parts = [f"<strong>{len(rows)}</strong> row{'s' if len(rows) != 1 else ''}"]
    if total_quantity is not None:
        summary_parts.append(f"<strong>Total Quantity:</strong> {total_quantity}")
    summary_line = " &middot; ".join(summary_parts)

    return _report_shell_html(
        hospital_name=hospital_name,
        document_title=title_text,
        title_text=title_text,
        meta_lines=meta_lines,
        table_html=table_html,
        summary_line=summary_line,
    )


def render_inventory_daily_usage_slip(
    *,
    hospital_name: str,
    display_timezone: str,
    vitals_staff_name: str,
    day: date,
    generated_at: datetime,
    column_headers: list[str],
    numeric_columns: set[int],
    rows: list[list[str]],
    total_quantity: Decimal | None,
) -> str:
    """Vitals' own end-of-day usage summary/audit — "everything used
    that day and which patient it went to" (confirmed design), scoped
    to the one staff member who generated it (never a request-suppliable
    user id — see app/modules/inventory/router.py's own print endpoint
    docstring for the actor-scoping this mirrors from `GET /inventory/
    usage/mine`). Shares `_report_shell_html`/`_report_table_html` with
    `render_inventory_history_log` above rather than duplicating them —
    see this section's own top-level docstring for why these two stay
    separate top-level functions despite that shared plumbing."""
    title_text = "Daily Usage Slip"
    generated_line = f"Generated: {format_local_timestamp(generated_at, display_timezone)}"
    meta_lines = [
        f"<strong>Vitals Staff:</strong> {_escape(vitals_staff_name)}",
        f"<strong>Date:</strong> {day.isoformat()}",
        generated_line,
    ]

    table_html = _report_table_html(
        column_headers=column_headers, rows=rows, numeric_columns=numeric_columns
    )
    summary_parts = [f"<strong>{len(rows)}</strong> entr{'y' if len(rows) == 1 else 'ies'}"]
    if total_quantity is not None:
        summary_parts.append(f"<strong>Total Quantity:</strong> {total_quantity}")
    summary_line = " &middot; ".join(summary_parts)

    return _report_shell_html(
        hospital_name=hospital_name,
        document_title=f"{title_text} — {day.isoformat()}",
        title_text=title_text,
        meta_lines=meta_lines,
        table_html=table_html,
        summary_line=summary_line,
    )

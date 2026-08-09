import { env } from '@/core/config/env';
import { openAndPrintHtml } from '@/utils/printWindow';

/** Escapes text for safe interpolation into the print document's HTML —
 * patient names are free-text, user-supplied at registration, so this
 * guards the same stored-XSS-via-print-popup risk the backend's
 * Central Print Service documents for its own HTML templates (see
 * backend/app/shared/printing/service.py's `_escape`). This feature is
 * deliberately client-side only (Part 3 of this build reuses
 * already-fetched Admin Overview data rather than adding a new
 * backend endpoint — see LeadsSection.jsx's docstring), so there is no
 * server-side escaping step to rely on here; this is the only one. */
function escapeHtml(value) {
  const div = document.createElement('div');
  div.textContent = value ?? '';
  return div.innerHTML;
}

let _logoDataUriPromise = null;

/** Fetches the hospital logo and resolves it to a base64 `data:` URI —
 * the exact same technique the server-rendered registration slip uses
 * (see backend/app/shared/printing/service.py's `_logo_data_uri`
 * docstring) and for the identical reason: this HTML is written into a
 * popup via `document.write` and then immediately printed, and a
 * `data:` URI has no network fetch left to race at rasterization time,
 * unlike a plain `<img src="/images/logo.png">` would. The earlier
 * revision of this module skipped the logo specifically because
 * resolving it client-side meant an *unavoidable* async step before
 * that write — solved here the same way any async prerequisite is
 * solved: await it fully before building the HTML, not by leaving the
 * image out. Cached after the first successful fetch (module-level,
 * mirrors the backend's `@lru_cache`) since the logo file never
 * changes during a session. */
async function getLogoDataUri() {
  if (!_logoDataUriPromise) {
    _logoDataUriPromise = fetch('/images/logo.png')
      .then((res) => {
        if (!res.ok) throw new Error(`Logo fetch failed: ${res.status}`);
        return res.blob();
      })
      .then(
        (blob) =>
          new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = () => resolve(reader.result);
            reader.onerror = reject;
            reader.readAsDataURL(blob);
          }),
      )
      .catch((error) => {
        _logoDataUriPromise = null; // don't cache a failure — allow retry next print
        throw error;
      });
  }
  return _logoDataUriPromise;
}

/** Builds a print-ready, letterhead-style A4 document listing that
 * day's patient leads (name + phone) and sends it through the browser's
 * native print pipeline via the shared `openAndPrintHtml` (see
 * `@/utils/printWindow` — the same popup+print helper Reception's
 * `usePrintRegistrationSlip` and Billing's `usePrintInvoice` use),
 * rather than inventing a second printing mechanism. `async` specifically
 * to fully resolve the logo's data URI (see `getLogoDataUri`) before
 * writing anything to the popup — the caller must `await` this.
 * Degrades to a text-only letterhead (not a thrown error) if the logo
 * genuinely can't be fetched, since a failed logo load is not a reason
 * to block printing the list itself. */
export async function printLeadsSheet({ dateLabel, leads }) {
  const logoDataUri = await getLogoDataUri().catch(() => null);
  const rows = leads
    .map(
      (lead, index) => `
      <tr>
        <td class="num">${index + 1}</td>
        <td>${escapeHtml(lead.fullName)}</td>
        <td>${escapeHtml(lead.phoneNumber)}</td>
      </tr>`,
    )
    .join('');

  const html = `<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Patient Leads — ${escapeHtml(dateLabel)}</title>
<style>
  :root { --ink: #111111; --ink-soft: #555555; --rule: #d0d0d0; --rule-strong: #111111; }
  * { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; font-family: 'Inter', -apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color: var(--ink); }
  body { padding: 28px; }
  .letterhead { text-align: center; padding-bottom: 14px; }
  .letterhead .logo { height: 52px; width: auto; margin-bottom: 6px; }
  .letterhead .name { font-size: 20px; font-weight: 800; letter-spacing: 0.5px; text-transform: uppercase; margin: 0; }
  .letterhead .tagline { margin-top: 4px; font-size: 10.5px; font-weight: 600; letter-spacing: 1.5px; text-transform: uppercase; color: var(--ink-soft); }
  .header-rule { border: none; border-top: 2px solid var(--rule-strong); margin: 14px 0 0; }
  .title-box { display: flex; align-items: center; justify-content: space-between; margin: 18px 0 16px; }
  .title-box .label { font-size: 13px; font-weight: 700; letter-spacing: 1.5px; text-transform: uppercase; }
  .title-box .date { font-size: 13px; font-weight: 600; color: var(--ink-soft); }
  table { width: 100%; border-collapse: collapse; }
  th, td { text-align: left; padding: 7px 8px; border-bottom: 1px solid var(--rule); font-size: 13px; }
  th { font-size: 10.5px; font-weight: 700; letter-spacing: 1px; text-transform: uppercase; color: var(--ink-soft); border-bottom: 1.5px solid var(--rule-strong); }
  td.num, th.num { width: 36px; color: var(--ink-soft); }
  .empty { padding: 24px 0; text-align: center; color: var(--ink-soft); font-size: 13px; }
  @page { size: A4; margin: 16mm; }
  @media print { body { padding: 0; } }
</style>
</head>
<body>
  <div class="letterhead">
    ${logoDataUri ? `<img class="logo" src="${logoDataUri}" alt="${escapeHtml(env.appName)} logo">` : ''}
    <p class="name">${escapeHtml(env.appName)}</p>
    <div class="tagline">Gynecology &bull; Maternity &bull; Women's Care</div>
  </div>
  <hr class="header-rule">
  <div class="title-box">
    <span class="label">Patient Leads</span>
    <span class="date">${escapeHtml(dateLabel)}</span>
  </div>
  ${
    leads.length === 0
      ? '<div class="empty">No patients were registered on this day.</div>'
      : `<table>
    <thead><tr><th class="num">#</th><th>Patient Name</th><th>Phone Number</th></tr></thead>
    <tbody>${rows}</tbody>
  </table>`
  }
</body>
</html>
`;

  await openAndPrintHtml(html);
}

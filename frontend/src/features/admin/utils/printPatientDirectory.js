import { env } from '@/core/config/env';
import { openAndPrintHtml } from '@/utils/printWindow';

/** Own copy of `printLeadsSheet.js`'s exact escape/logo/print pattern —
 * per this feature's build instructions, copied rather than shared or
 * imported, so a future change to one print sheet never silently
 * changes the other. See `printLeadsSheet.js` for the full rationale
 * behind each piece (stored-XSS-via-print-popup guard, base64 logo,
 * `openAndPrintHtml`). */
function escapeHtml(value) {
  const div = document.createElement('div');
  div.textContent = value ?? '';
  return div.innerHTML;
}

let _logoDataUriPromise = null;

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
        _logoDataUriPromise = null;
        throw error;
      });
  }
  return _logoDataUriPromise;
}

/** Builds a print-ready, letterhead-style A4 document listing the
 * Patient Directory's current filtered result set (every patient
 * matching the page's active search, not just the on-screen page — the
 * caller fetches the full matching set before calling this) and sends
 * it through the browser's native print pipeline. `async` to fully
 * resolve the logo's data URI first — the caller must `await` this.
 * Degrades to a text-only letterhead if the logo can't be fetched. */
export async function printPatientDirectory({ searchLabel, patients }) {
  const logoDataUri = await getLogoDataUri().catch(() => null);
  const rows = patients
    .map(
      (patient, index) => `
      <tr>
        <td class="num">${index + 1}</td>
        <td>${escapeHtml(patient.mr_number)}</td>
        <td>${escapeHtml(patient.full_name)}</td>
        <td class="num">${patient.age_years ?? '—'}</td>
        <td>${escapeHtml(patient.phone_number)}</td>
      </tr>`,
    )
    .join('');

  const html = `<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Patient Directory</title>
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
  td.num, th.num { width: 48px; color: var(--ink-soft); }
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
    <span class="label">Patient Directory</span>
    <span class="date">${escapeHtml(searchLabel)}</span>
  </div>
  ${
    patients.length === 0
      ? '<div class="empty">No patients match this search.</div>'
      : `<table>
    <thead><tr><th class="num">#</th><th>MR Number</th><th>Patient Name</th><th class="num">Age</th><th>Phone Number</th></tr></thead>
    <tbody>${rows}</tbody>
  </table>`
  }
</body>
</html>
`;

  await openAndPrintHtml(html);
}

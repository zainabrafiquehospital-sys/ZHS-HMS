/**
 * Regression test for the "stale vitals on an already-open doctor
 * consultation screen" bug (2026-08-30).
 *
 * Root cause: `useVitalsForVisit` (features/vitals/hooks/useVitals.js)
 * fetches once on mount and never refetches — this app deliberately
 * runs no background polling or refetch-on-window-focus globally (see
 * core/providers/QueryProvider.jsx). When vitals staff record a new
 * reading for a visit whose doctor already has the consultation screen
 * open (the mid-consult "Send to Vitals" detour), that resume happens
 * entirely in the *vitals staff's own browser session*
 * (ConsultationService.resume_from_vitals) — nothing told the doctor's
 * separate, already-open tab to re-fetch the vitals list, even though
 * the "awaiting vitals" banner correctly cleared via
 * `useConsultationById`'s own conditional poll.
 *
 * Fix: `useConsultationById` now invalidates `['vitals', 'visits',
 * visitId]` at the exact moment it observes the consultation's status
 * leave `awaiting_vitals` — piggybacking on the one mechanism that
 * already detects that transition, rather than adding new polling or
 * changing any global QueryClient default.
 *
 * This script is self-contained: it seeds its own fresh test visit via
 * the backend API (no external setup needed) and requires the local
 * dev stack running — backend on http://127.0.0.1:8000, frontend on
 * http://localhost:3000, same convention as every other ad hoc
 * Playwright verification in this project (see the `run` skill).
 * Not wired into an automated CI/test-runner (no playwright.config.js
 * exists in this repo yet) — run directly with `node
 * e2e/consultation-vitals-refetch.spec.js` from `frontend/`.
 */
const { chromium } = require('playwright');

const API_BASE = 'http://127.0.0.1:8000/api/v1';
const APP_BASE = 'http://localhost:3000';

const RECEPTIONIST_EMAIL = 'e2e-receptionist@example.com';
const RECEPTIONIST_PASSWORD = 'Str0ngE2EPassw0rd#2026';
const DOCTOR_EMAIL = 'step3-doctor-test@example.com';
const DOCTOR_PASSWORD = 'Step3DoctorTest#2026';
const VITALS_STAFF_EMAIL = 'e2e-vitals@example.com';
const VITALS_STAFF_PASSWORD = 'Str0ngE2EPassw0rd#2026';

const PATIENT_NAME = `Vitals Refetch Regression ${Date.now()}`;

async function login(email, password) {
  const resp = await fetch(`${API_BASE}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  });
  const body = await resp.json();
  if (!resp.ok || body.error) {
    throw new Error(`Login failed for ${email}: ${JSON.stringify(body.error ?? body)}`);
  }
  return { token: body.data.access_token, userId: body.data.user.id };
}

async function registerVisit(receptionToken, doctorUserId) {
  const resp = await fetch(`${API_BASE}/reception/visits`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${receptionToken}`,
    },
    body: JSON.stringify({
      new_patient: {
        full_name: PATIENT_NAME,
        phone_number: '03005559911',
        age_years: 30,
        gender: 'female',
      },
      procedures: [{ name: 'Consultation', amount: 800 }],
      vitals_required: false,
      doctor_user_id: doctorUserId,
      initial_payment_amount: 800,
      initial_payment_method: 'cash',
    }),
  });
  const body = await resp.json();
  if (!resp.ok || body.error) {
    throw new Error(`Visit registration failed: ${JSON.stringify(body.error ?? body)}`);
  }
  return body.data.visit;
}

(async () => {
  const errors = [];
  const check = (cond, label) => {
    if (cond) {
      console.log('PASS:', label);
    } else {
      console.log('FAIL:', label);
      errors.push(label);
    }
  };

  // --- Seed a fresh visit, assigned to the test doctor, via the API ---
  const { token: receptionToken } = await login(RECEPTIONIST_EMAIL, RECEPTIONIST_PASSWORD);
  const { userId: doctorUserId } = await login(DOCTOR_EMAIL, DOCTOR_PASSWORD);
  const visit = await registerVisit(receptionToken, doctorUserId);
  console.log(`Seeded visit ${visit.id} for "${PATIENT_NAME}", assigned to the test doctor.`);

  const browser = await chromium.launch();

  // === Doctor's browser: open the consultation and send to vitals ===
  const doctorPage = await browser.newPage();
  await doctorPage.goto(`${APP_BASE}/login`);
  await doctorPage.fill('input[type="email"], input[name="email"]', DOCTOR_EMAIL);
  await doctorPage.fill('input[type="password"], input[name="password"]', DOCTOR_PASSWORD);
  await doctorPage.click('button[type="submit"]');
  await doctorPage.waitForURL('**/doctor', { timeout: 15000 });
  await doctorPage.waitForFunction((name) => document.body.innerText.includes(name), PATIENT_NAME, {
    timeout: 15000,
  });
  await doctorPage.waitForTimeout(500);

  const card = doctorPage.locator('div.rounded-md.border-border.bg-card').filter({ hasText: PATIENT_NAME });
  await card.first().locator('button:has-text("Start Consultation")').click();
  await doctorPage.waitForURL('**/doctor/consultation/**', { timeout: 10000 });
  await doctorPage.waitForTimeout(1000);
  check(
    (await doctorPage.locator('text=No vitals recorded').count()) > 0,
    'doctor sees "No vitals recorded" before anything happens',
  );

  await doctorPage.fill('#vitalsReason', 'Recheck BP');
  await doctorPage.click('button:has-text("Send to Vitals")');
  await doctorPage.waitForTimeout(1000);
  check(
    (await doctorPage.locator('text=Waiting for vitals to be recorded').count()) > 0,
    'doctor sees the "awaiting vitals" banner after Send to Vitals',
  );

  // === Vitals staff's SEPARATE browser session records new vitals ===
  const vitalsPage = await browser.newPage();
  await vitalsPage.goto(`${APP_BASE}/login`);
  await vitalsPage.fill('input[type="email"], input[name="email"]', VITALS_STAFF_EMAIL);
  await vitalsPage.fill('input[type="password"], input[name="password"]', VITALS_STAFF_PASSWORD);
  await vitalsPage.click('button[type="submit"]');
  await vitalsPage.waitForURL('**/vitals', { timeout: 15000 });
  await vitalsPage.waitForFunction((name) => document.body.innerText.includes(name), PATIENT_NAME, {
    timeout: 15000,
  });
  await vitalsPage.waitForTimeout(500);

  const vitalsCard = vitalsPage.locator('div.rounded-md.border-border.bg-card').filter({ hasText: PATIENT_NAME });
  await vitalsCard.first().locator('button:has-text("Record Vitals")').click();
  await vitalsPage.waitForURL('**/vitals/**', { timeout: 10000 });
  await vitalsPage.waitForTimeout(1000);
  await vitalsPage.fill('input[name="systolic_bp"]', '131');
  await vitalsPage.fill('input[name="diastolic_bp"]', '85');
  await vitalsPage.fill('input[name="pulse_rate"]', '79');
  await vitalsPage.fill('input[name="temperature"]', '98.9');
  await vitalsPage.fill('input[name="spo2_percent"]', '96');
  await vitalsPage.click('button[type="submit"]');
  await vitalsPage.waitForTimeout(2000);
  console.log('Vitals staff recorded 131/85, 98.9°F for the same visit, in a separate browser session.');

  // === Back on the doctor's ALREADY-OPEN tab — no reload, just wait ===
  await doctorPage.waitForFunction(
    () => !document.body.innerText.includes('Waiting for vitals to be recorded'),
    { timeout: 10000 },
  );
  check(true, 'doctor\'s "awaiting vitals" banner clears within 10s (pre-existing behavior, unchanged)');

  // The fix under test: the vitals section must pick up the new
  // reading with NO manual reload, shortly after the banner clears.
  await doctorPage
    .waitForFunction(
      () => document.body.innerText.includes('131') && document.body.innerText.includes('85'),
      { timeout: 5000 },
    )
    .then(
      () => check(true, 'doctor\'s already-open tab shows the new 131/85 reading with no manual reload'),
      () => check(false, 'doctor\'s already-open tab shows the new 131/85 reading with no manual reload'),
    );

  const bodyText = await doctorPage.locator('body').innerText();
  check(bodyText.includes('98.9'), 'the new temperature (98.9°F) also appears, correctly labeled');

  await browser.close();

  console.log('\n--- SUMMARY ---');
  if (errors.length === 0) {
    console.log('ALL CHECKS PASSED');
  } else {
    console.log('FAILURES:', errors);
    process.exit(1);
  }
})();

/**
 * Regression test for the "Doctor Queue misses vitals-staff handoff
 * while the tab is backgrounded" bug (2026-08-30, sibling to
 * e2e/consultation-vitals-refetch.spec.js's mid-consult fix).
 *
 * Root cause (confirmed via direct production database verification —
 * the backend/data side was correct in every case): useMyQueue,
 * useUnassignedQueue (features/consultation/hooks/useConsultation.js)
 * and useVitalsForVisits (features/vitals/hooks/useVitals.js) already
 * poll every 15s, but React Query's own `refetchIntervalInBackground`
 * defaults to `false` — the poll silently pauses the instant the
 * Doctor Queue tab isn't the active/visible one, and this app's global
 * `refetchOnWindowFocus: false` (core/providers/QueryProvider.jsx,
 * untouched by this fix) means nothing catches it up on refocus
 * either. A doctor with this tab open but backgrounded while vitals
 * staff complete an initial (pre-consultation) recording would see the
 * patient sit in "Vitals Pending" indefinitely until a manual reload.
 *
 * Fix: all three hooks now set `refetchIntervalInBackground: true`,
 * scoped to just those hooks (every one of them is only ever consumed
 * by the Doctor Queue page) — no global QueryClient default changed.
 *
 * This test simulates a backgrounded tab the way React Query's own
 * internals actually detect it — overriding `document.visibilityState`
 * to 'hidden' and dispatching a real `visibilitychange` event — rather
 * than literally minimizing the OS window (which Playwright cannot
 * drive across processes anyway). This exercises the exact code path
 * `refetchIntervalInBackground` gates, without relying on the host
 * browser's own separate OS-level timer throttling.
 *
 * Self-contained: seeds its own visit via the API. Requires the local
 * dev stack running (backend on http://127.0.0.1:8000, frontend on
 * http://localhost:3000). Not wired into a CI test runner (no
 * playwright.config.js in this repo) — run directly with `node
 * e2e/doctor-queue-background-poll.spec.js` from `frontend/`.
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

async function registerVisit(receptionToken, doctorUserId, patientName) {
  const resp = await fetch(`${API_BASE}/reception/visits`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${receptionToken}`,
    },
    body: JSON.stringify({
      new_patient: {
        full_name: patientName,
        phone_number: '03005557788',
        age_years: 31,
        gender: 'female',
      },
      procedures: [{ name: 'Pelvic Scan', amount: 1000 }],
      vitals_required: true,
      doctor_user_id: doctorUserId,
      initial_payment_amount: 1000,
      initial_payment_method: 'cash',
    }),
  });
  const body = await resp.json();
  if (!resp.ok || body.error) {
    throw new Error(`Visit registration failed: ${JSON.stringify(body.error ?? body)}`);
  }
  return body.data.visit;
}

/** Makes React Query's own internals believe this tab is hidden — the
 * exact signal `refetchIntervalInBackground` gates on — without
 * needing to actually minimize the OS window. */
async function simulateBackgroundedTab(page) {
  await page.evaluate(() => {
    Object.defineProperty(document, 'visibilityState', {
      configurable: true,
      get: () => 'hidden',
    });
    Object.defineProperty(document, 'hidden', {
      configurable: true,
      get: () => true,
    });
    document.dispatchEvent(new Event('visibilitychange'));
  });
}

async function runScenario(patientName) {
  const errors = [];
  const check = (cond, label) => {
    if (cond) {
      console.log('PASS:', label);
    } else {
      console.log('FAIL:', label);
      errors.push(label);
    }
  };

  const { token: receptionToken } = await login(RECEPTIONIST_EMAIL, RECEPTIONIST_PASSWORD);
  const { userId: doctorUserId } = await login(DOCTOR_EMAIL, DOCTOR_PASSWORD);
  const visit = await registerVisit(receptionToken, doctorUserId, patientName);
  console.log(`Seeded visit ${visit.id} for "${patientName}" (waiting_vitals, assigned to the test doctor).`);

  const browser = await chromium.launch();

  const doctorPage = await browser.newPage();
  await doctorPage.goto(`${APP_BASE}/login`);
  await doctorPage.fill('input[type="email"], input[name="email"]', DOCTOR_EMAIL);
  await doctorPage.fill('input[type="password"], input[name="password"]', DOCTOR_PASSWORD);
  await doctorPage.click('button[type="submit"]');
  await doctorPage.waitForURL('**/doctor', { timeout: 15000 });
  // The patient's own card (not the section header, and not the
  // literal "Vitals Pending" text that also appears as a per-card
  // status badge — both would false-match a naive text search) is the
  // reliable signal that it's actually landed in that section.
  const patientCard = doctorPage
    .locator('div.rounded-md.border-border.bg-card')
    .filter({ hasText: patientName });
  await patientCard.first().waitFor({
    state: 'visible',
    // Generous timeout — this test doctor account accumulates
    // "in_consultation" visits across every session's own testing
    // (useVitalsPendingForDoctor's N+1 useActiveConsultationsForVisits
    // check scales with that count), so the initial load alone can take
    // several seconds on a heavily-used dev database. Not related to
    // the fix under test.
    timeout: 30000,
  });
  await doctorPage.waitForTimeout(500);

  const startedInVitalsPending = (await patientCard.first().innerText()).includes('Vitals Pending');
  check(startedInVitalsPending, 'patient starts in "Vitals Pending" before recording');

  // Simulate the doctor switching away — a backgrounded, no-longer-visible tab.
  await simulateBackgroundedTab(doctorPage);
  console.log('Simulated the doctor\'s tab going to the background (document.visibilityState = "hidden").');

  const vitalsPage = await browser.newPage();
  await vitalsPage.goto(`${APP_BASE}/login`);
  await vitalsPage.fill('input[type="email"], input[name="email"]', VITALS_STAFF_EMAIL);
  await vitalsPage.fill('input[type="password"], input[name="password"]', VITALS_STAFF_PASSWORD);
  await vitalsPage.click('button[type="submit"]');
  await vitalsPage.waitForURL('**/vitals', { timeout: 15000 });
  await vitalsPage.waitForFunction((name) => document.body.innerText.includes(name), patientName, {
    timeout: 15000,
  });
  await vitalsPage.waitForTimeout(500);

  const vitalsCard = vitalsPage.locator('div.rounded-md.border-border.bg-card').filter({ hasText: patientName });
  await vitalsCard.first().locator('button:has-text("Record Vitals")').click();
  await vitalsPage.waitForURL('**/vitals/**', { timeout: 10000 });
  await vitalsPage.waitForTimeout(1000);
  await vitalsPage.fill('input[name="systolic_bp"]', '138');
  await vitalsPage.fill('input[name="diastolic_bp"]', '88');
  await vitalsPage.fill('input[name="pulse_rate"]', '82');
  await vitalsPage.fill('input[name="temperature"]', '98.8');
  await vitalsPage.fill('input[name="spo2_percent"]', '97');
  await vitalsPage.click('button[type="submit"]');
  await vitalsPage.waitForTimeout(2000);
  console.log('Vitals staff recorded initial vitals (138/88, 98.8°F) in a separate session.');

  // Doctor's tab is STILL simulated-hidden and has NOT been reloaded.
  // Wait past one full 15s poll cycle and check whether it picked up
  // the change anyway.
  console.log('Waiting ~20s with the doctor\'s tab still backgrounded and never reloaded...');
  // "Start Consultation" only appears on a QueueCard (the "Waiting for
  // You"/"Unclaimed Visits" shape) — VitalsPendingCard has no action
  // button at all — so this is an unambiguous signal the patient's own
  // card has switched shape, without needing to reason about section
  // boundaries in raw page text (the same ambiguity fixed above).
  let sawUpdate = false;
  for (let elapsed = 0; elapsed <= 20; elapsed += 4) {
    const cardText = await patientCard.first().innerText().catch(() => '');
    if (cardText.includes('Start Consultation')) {
      sawUpdate = true;
      break;
    }
    await doctorPage.waitForTimeout(4000);
  }
  check(
    sawUpdate,
    'patient moves to "Waiting for You" within ~20s while tab is backgrounded, with no manual reload',
  );

  if (sawUpdate) {
    // The card switching shape (QueueCard) and its own useVitalsForVisits
    // fetch resolving are two separate async events — give the badge's
    // own request a moment to settle past its "…" loading placeholder.
    await doctorPage.waitForFunction(
      (name) => {
        const cards = [...document.querySelectorAll('div.rounded-md.border-border.bg-card')];
        const target = cards.find((el) => el.innerText.includes(name));
        return target && !target.innerText.includes('Vitals:\n…');
      },
      patientName,
      { timeout: 10000 },
    );
    const cardText = await patientCard.first().innerText().catch(() => '');
    check(/mild|critical|normal/i.test(cardText), 'vitals severity badge is populated (not stuck on "—")');
    console.log('Card contents:', cardText.replace(/\n/g, ' | '));
  }

  await browser.close();
  return errors;
}

(async () => {
  const suffix = Date.now();
  const errors = await runScenario(`Background Poll Fix Verify ${suffix}`);

  console.log('\n--- SUMMARY ---');
  if (errors.length === 0) {
    console.log('ALL CHECKS PASSED');
  } else {
    console.log('FAILURES:', errors);
    process.exit(1);
  }
})();

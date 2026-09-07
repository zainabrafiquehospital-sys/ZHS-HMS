import { manualPatientSchema } from '../schemas/pharmacySchemas';

/**
 * Medicine Billing's patient linkage, factored out of
 * MedicineBillingWorkspace.jsx so the "may this bill be finalized, and
 * with what patient attached" decision is one pure, tested function
 * rather than inline form-handler logic.
 *
 * Background: a MedicineBill links to a patient only through
 * `visit_id -> Visit -> Patient` (there is no `patient_id` column on
 * the bill — see backend/app/modules/pharmacy/models.py's `MedicineBill`
 * docstring). Before this change the finalize handler sent
 * `visit_id: selectedVisit ? selectedVisit.id : null` with no floor, so
 * a receptionist who searched/selected a patient but never clicked one
 * of their visits still finalized a fully anonymous bill (visit_id null,
 * no manual fields). `resolveMedicineBillLinkage` is the hard gate that
 * makes that impossible; `autoLinkVisit` removes the need for the second
 * click in the common single-open-visit case.
 */

/**
 * Visit lifecycle states that mean the visit is over. A medicine sale
 * normally attaches to a still-active visit, so these are excluded when
 * auto-picking one. Mirrors app/modules/visits/models.py's `VisitStatus`
 * terminal members (confirmed against source, not guessed).
 */
export const TERMINAL_VISIT_STATUSES = ['completed', 'cancelled'];

/** The subset of `visits` that are still in motion (not completed/cancelled). */
export function openVisits(visits) {
  return (visits ?? []).filter((visit) => !TERMINAL_VISIT_STATUSES.includes(visit?.status));
}

/**
 * The single visit to auto-link when a receptionist picks a patient in
 * Medicine Billing: only when the patient has exactly one open
 * (non-terminal) visit. More than one → the receptionist disambiguates
 * in the picker; none → nothing to auto-link (they pick a past visit
 * from the full list, or switch to Manual Entry). Never guesses.
 */
export function autoLinkVisit(visits) {
  const open = openVisits(visits);
  return open.length === 1 ? open[0] : null;
}

export const MEDICINE_BILL_PATIENT_REQUIRED_MESSAGE =
  "Link this bill to the patient's visit above, or switch to Manual Entry and fill in their name, age, and contact number.";

/**
 * Single source of truth for finalizing a medicine bill's patient
 * linkage. Returns either:
 *   { ok: true, visitId, manualPayload }  — safe to submit
 *   { ok: false, error }                   — blocked, show `error` inline
 *
 *  - Manual Entry mode → all three manual fields must parse
 *    (`manualPatientSchema`); returned as `manualPayload`, `visitId` null.
 *  - otherwise          → a visit must be selected; its id is `visitId`,
 *    `manualPayload` empty.
 *  - neither             → { ok: false } (a bill can no longer be saved
 *    fully anonymous by accident).
 */
export function resolveMedicineBillLinkage({
  linkMode,
  selectedVisit,
  manualName,
  manualAge,
  manualPhone,
}) {
  if (linkMode === 'manual') {
    const parsed = manualPatientSchema.safeParse({
      manual_patient_name: manualName,
      manual_patient_age: manualAge,
      manual_patient_phone: manualPhone,
    });
    if (!parsed.success) {
      return {
        ok: false,
        error: parsed.error.issues[0]?.message ?? 'Manual patient details are incomplete.',
      };
    }
    return { ok: true, visitId: null, manualPayload: parsed.data };
  }

  if (selectedVisit?.id) {
    return { ok: true, visitId: selectedVisit.id, manualPayload: {} };
  }

  return { ok: false, error: MEDICINE_BILL_PATIENT_REQUIRED_MESSAGE };
}

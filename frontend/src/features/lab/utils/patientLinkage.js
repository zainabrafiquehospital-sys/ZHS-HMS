import { labManualPatientSchema } from '../schemas/labSchemas';

/**
 * Laboratory Billing's patient linkage, factored out of
 * LabBillingWorkspace.jsx for the same reason as Pharmacy's own
 * `resolveMedicineBillLinkage` (see that file's docstring) — one pure,
 * tested "may this bill be finalized, and with what patient attached"
 * function instead of inline form-handler logic.
 *
 * Difference from Pharmacy: a LabBill links to a patient through a
 * direct `patient_id` column (there is deliberately no `visit_id` on
 * lab_bill — see backend/app/modules/lab/models.py's `LabBill`
 * docstring), so the "linked" branch here checks `selectedPatient`, not
 * a visit. Manual Entry mode is otherwise identical.
 */

export const LAB_BILL_PATIENT_REQUIRED_MESSAGE =
  'Search & link a patient above, or switch to Manual Entry and fill in their name, age, and contact number.';

/**
 * Single source of truth for finalizing a lab bill's patient linkage.
 * Returns either:
 *   { ok: true, patientId, manualPayload }  — safe to submit
 *   { ok: false, error }                     — blocked, show `error` inline
 *
 *  - Manual Entry mode → all three manual fields must parse
 *    (`labManualPatientSchema`); returned as `manualPayload`, `patientId` null.
 *  - otherwise          → a patient must be selected; its id is `patientId`.
 *  - neither             → { ok: false } (a lab bill can no longer be
 *    saved fully anonymous by accident).
 */
export function resolveLabBillLinkage({
  linkMode,
  selectedPatient,
  manualName,
  manualAge,
  manualPhone,
}) {
  if (linkMode === 'manual') {
    const parsed = labManualPatientSchema.safeParse({
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
    return { ok: true, patientId: null, manualPayload: parsed.data };
  }

  if (selectedPatient?.id) {
    return { ok: true, patientId: selectedPatient.id, manualPayload: {} };
  }

  return { ok: false, error: LAB_BILL_PATIENT_REQUIRED_MESSAGE };
}

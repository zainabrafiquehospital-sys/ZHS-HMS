/**
 * The vitals state a Doctor-dashboard patient card should display,
 * derived purely from data the backend can actually distinguish:
 *   - whether ANY VitalsRecord exists for the visit (records array), and
 *   - Visit.vitals_required.
 *
 * Three states, no invented ones:
 *   - collected     : at least one vitals reading is on file for the visit
 *   - pending       : none on file yet, but the visit was flagged
 *                     vitals-required at registration
 *   - not_required  : none on file, and the visit was not flagged
 *
 * The mid-consultation "Vitals Pending" detour card on the dashboard is
 * a separate surface (useVitalsPendingForDoctor) and is unaffected by
 * this helper.
 */

export const VITALS_STATUS = {
  COLLECTED: 'collected',
  PENDING: 'pending',
  NOT_REQUIRED: 'not_required',
};

export function deriveVitalsStatus(records, vitalsRequired) {
  if (records && records.length > 0) return VITALS_STATUS.COLLECTED;
  return vitalsRequired ? VITALS_STATUS.PENDING : VITALS_STATUS.NOT_REQUIRED;
}

export const VITALS_STATUS_LABEL = {
  [VITALS_STATUS.COLLECTED]: 'Vitals Collected',
  [VITALS_STATUS.PENDING]: 'Vitals Pending',
  [VITALS_STATUS.NOT_REQUIRED]: 'Not Required',
};

export const VITALS_STATUS_BADGE_VARIANT = {
  [VITALS_STATUS.COLLECTED]: 'success',
  [VITALS_STATUS.PENDING]: 'warning',
  [VITALS_STATUS.NOT_REQUIRED]: 'outline',
};

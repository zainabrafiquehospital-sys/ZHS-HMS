/**
 * Every Visit Lifecycle state (visits/models.py's VisitStatus,
 * confirmed against source, not guessed) mapped to a Badge variant —
 * originally built for Admin Overview's status-count badges, extracted
 * here so every other status-badge in the app (Doctor Queue's "Vitals
 * Pending" indicator included) reuses the exact same color convention
 * instead of a one-off. Terminal success/failure states get their own
 * color; everything still in motion reads as neutral/secondary.
 */
export const VISIT_STATUS_BADGE_VARIANT = {
  registered: 'outline',
  waiting_vitals: 'outline',
  waiting_doctor: 'secondary',
  in_consultation: 'secondary',
  waiting_billing: 'warning',
  payment_pending: 'warning',
  completed: 'success',
  cancelled: 'destructive',
};

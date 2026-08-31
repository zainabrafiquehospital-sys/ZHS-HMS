import { RequirePermission } from '@/features/auth/components/RequirePermission';

// A top-level route, gated on the new `patients:history:read` permission
// — deliberately not reusing `patients:read` (the /patients Patient
// Directory's own gate), which is a different, broader capability (bulk
// directory browsing) already held by a different set of roles. See
// backend/app/modules/patients/constants.py's own docstring on
// `PERMISSION_PATIENTS_HISTORY_READ` for the full reasoning, and
// backend/app/modules/patient_history/router.py for how each section of
// the page's own data is additionally scoped per-actor beyond this one
// route-level gate.
export default function PatientHistoryLayout({ children }) {
  return <RequirePermission permission="patients:history:read">{children}</RequirePermission>;
}

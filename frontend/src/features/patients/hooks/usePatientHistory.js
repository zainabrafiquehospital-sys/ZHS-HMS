'use client';

import { useQuery } from '@tanstack/react-query';
import { patientsService } from '@/features/patients/api/patientsService';

/** Backs the Patient History search page's own result view, once a
 * patient has been picked — see patientsService.getHistory's own
 * docstring for the underlying `GET /patients/{id}/history` endpoint.
 *
 * Every section (`vitals`/`consultations`/`invoices`/`lab_bills`/
 * `pharmacy_bills`) comes back from the backend as either `null` (the
 * caller's role doesn't hold that section's own other permission —
 * see backend/app/modules/patient_history/router.py's docstring for
 * exactly which) or an array (`[]` included — the caller can see this
 * section, this patient just has no records of that type). This hook
 * passes that distinction straight through rather than defaulting
 * `null` to `[]` the way most of this codebase's other list-backed
 * hooks do — PatientHistorySearch.jsx needs to tell "not visible to
 * me" apart from "visible, but empty" to decide whether to render the
 * section at all. */
export function usePatientHistory(patientId) {
  const query = useQuery({
    queryKey: ['patients', 'history', patientId],
    queryFn: () => patientsService.getHistory(patientId).then((res) => res.data),
    enabled: Boolean(patientId),
  });
  return { ...query, history: query.data ?? null };
}

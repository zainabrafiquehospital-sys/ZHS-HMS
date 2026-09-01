'use client';

import { keepPreviousData, useQuery } from '@tanstack/react-query';
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

/** The Patient History page's own always-visible, hospital-wide,
 * server-paginated feed — backed by `patientsService.listHistoryVisits`
 * (see that method's docstring). Unified across Visit/MedicineBill/
 * LabBill (2026-09 redesign): each row is `{record_type, queue_token,
 * created_at, patient_id, visit, medicine_bill, lab_bill}`, with
 * exactly one of `visit`/`medicine_bill`/`lab_bill` populated per
 * `record_type` — the frontend's own mirror of `PatientHistoryRecordOut`
 * (see backend/app/modules/patient_history/schemas.py's own docstring
 * for why each type's existing shape is reused unchanged rather than
 * redefined). `keepPreviousData` keeps the current page's rows on
 * screen while the next page/search/date-range fetches, the same
 * pattern usePatientDirectory (Admin) already uses for its own
 * paginated table. */
export function useHistoryRecordList({ page, pageSize, search, startDate, endDate }) {
  const query = useQuery({
    queryKey: ['patients', 'history', 'records', { page, pageSize, search, startDate, endDate }],
    queryFn: () =>
      patientsService
        .listHistoryVisits({ page, pageSize, search, startDate, endDate })
        .then((res) => ({ records: res.data, meta: res.meta })),
    placeholderData: keepPreviousData,
  });
  return {
    ...query,
    records: query.data?.records ?? [],
    meta: query.data?.meta ?? null,
  };
}

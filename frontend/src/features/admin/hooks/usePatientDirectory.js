'use client';

import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { patientsService } from '@/features/patients/api/patientsService';
import { visitsService } from '@/features/visits/api/visitsService';

/** The Admin Patient Directory's full, paginated/sortable/searchable
 * listing — backed by `patientsService.list`'s real server-side
 * pagination (see that method's docstring), never a "fetch N recent +
 * filter client-side" shortcut like `useAdminRecentVisits` (Admin
 * Overview's Visits tab) uses. `keepPreviousData` keeps the current
 * page's rows on screen (not a loading flash) while the next page/
 * search/sort fetches, the same pattern TanStack Query v5 recommends
 * for any paginated table. */
export function usePatientDirectory({ page, pageSize, search, sortBy, sortOrder }) {
  const query = useQuery({
    queryKey: ['admin', 'patients', 'directory', { page, pageSize, search, sortBy, sortOrder }],
    queryFn: () =>
      patientsService
        .list({ page, pageSize, search, sortBy, sortOrder })
        .then((res) => ({ patients: res.data, meta: res.meta })),
    placeholderData: keepPreviousData,
  });
  return {
    ...query,
    patients: query.data?.patients ?? [],
    meta: query.data?.meta ?? null,
  };
}

/** One patient's visit history — backs the Patient Directory's
 * per-patient "view history / reprint slip" panel. Reuses
 * `visitsService.listForPatient`'s existing server-side `patient_id`
 * filter (see that method's docstring — the one other caller is
 * Pharmacy's "link to visit" picker), the same real endpoint already
 * used elsewhere, not a new one. `page_size: 20` there is already
 * enough for any patient's realistic visit count in this codebase's
 * current volume; not raised further here for the same reason. */
export function usePatientVisitHistory(patientId) {
  const query = useQuery({
    queryKey: ['admin', 'patients', 'visit-history', patientId],
    queryFn: () => visitsService.listForPatient(patientId).then((res) => res.data),
    enabled: Boolean(patientId),
  });
  return { ...query, visits: query.data ?? [] };
}

'use client';

import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { patientsService } from '@/features/patients/api/patientsService';

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

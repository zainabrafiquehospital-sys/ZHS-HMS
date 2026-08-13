'use client';

import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { adminUsersService } from '@/features/admin/api/adminUsersService';
import { adminStatsService } from '@/features/admin/api/adminStatsService';
import { mergeEmployeeStats, toLookup } from '@/features/admin/utils/employeeStats';

/** The Admin "Employee Accounts & Stats" page's full, paginated/
 * sortable/searchable user listing — backed by `adminUsersService.list`
 * (a thin wrapper around `GET /users`, unfiltered by status), never a
 * "fetch N + filter client-side" shortcut. Same `keepPreviousData`
 * pagination shape as `usePatientDirectory`. */
export function useEmployeeAccountsList({ page, pageSize, search, sortBy, sortOrder }) {
  const query = useQuery({
    queryKey: ['admin', 'users', 'directory', { page, pageSize, search, sortBy, sortOrder }],
    queryFn: () =>
      adminUsersService
        .list({ page, pageSize, search, sortBy, sortOrder })
        .then((res) => ({ users: res.data, meta: res.meta })),
    placeholderData: keepPreviousData,
  });
  return {
    ...query,
    users: query.data?.users ?? [],
    meta: query.data?.meta ?? null,
  };
}

/** Every user's real, role-appropriate activity counts (visits
 * registered, medicine bills created + revenue billed, consultations
 * completed, vitals recorded) — one `GROUP BY` query per module,
 * server-side (see adminStatsService's four methods), never one request
 * per user on this page's user list. Computed unconditionally for every
 * user rather than gated by role name: this codebase's actual seeded
 * roles (Receptionist/Vitals/admin, plus demo-only roles) don't cleanly
 * map to a fixed "which stat belongs to which role" table, so every
 * user simply gets their real counts — 0 wherever a category doesn't
 * apply to what they actually did. Returns a lookup keyed by user id,
 * each value shaped `{ visits, bills, revenue, consultations, vitals }`
 * — callers default missing entries to 0, the same convention the
 * backend's own aggregate endpoints use for "no rows for this user". */
export function useEmployeeActivityStats() {
  const visitStats = useQuery({
    queryKey: ['admin', 'stats', 'visits-by-creator'],
    queryFn: () => adminStatsService.getVisitStatsByCreator().then((res) => res.data),
  });
  const billStats = useQuery({
    queryKey: ['admin', 'stats', 'bills-by-creator'],
    queryFn: () => adminStatsService.getMedicineBillStatsByCreator().then((res) => res.data),
  });
  const consultationStats = useQuery({
    queryKey: ['admin', 'stats', 'consultations-by-doctor'],
    queryFn: () => adminStatsService.getConsultationStatsByDoctor().then((res) => res.data),
  });
  const vitalsStats = useQuery({
    queryKey: ['admin', 'stats', 'vitals-by-creator'],
    queryFn: () => adminStatsService.getVitalsStatsByCreator().then((res) => res.data),
  });

  const isLoading =
    visitStats.isLoading || billStats.isLoading || consultationStats.isLoading || vitalsStats.isLoading;
  const isError = visitStats.isError || billStats.isError || consultationStats.isError || vitalsStats.isError;
  const error = visitStats.error ?? billStats.error ?? consultationStats.error ?? vitalsStats.error;

  const visitsByUser = toLookup(visitStats.data, ['count']);
  const billsByUser = toLookup(billStats.data, ['count', 'revenue']);
  const consultationsByUser = toLookup(consultationStats.data, ['count']);
  const vitalsByUser = toLookup(vitalsStats.data, ['count']);

  function statsFor(userId) {
    return mergeEmployeeStats({
      userId,
      visitsByUser,
      billsByUser,
      consultationsByUser,
      vitalsByUser,
    });
  }

  return { isLoading, isError, error, statsFor };
}

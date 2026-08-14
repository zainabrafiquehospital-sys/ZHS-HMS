'use client';

import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
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

function invalidateEmployeeAccounts(queryClient) {
  // Broad ['admin', 'users'] prefix, not just ['admin', 'users',
  // 'directory'] — a status change is also relevant to anything else
  // reading a user by id in the same session (e.g. useReceptionistsForVisits'
  // per-id cache), matching useReception.js's identical broad-prefix
  // invalidation rationale.
  queryClient.invalidateQueries({ queryKey: ['admin', 'users'] });
}

/** Deactivates (soft-delete, status -> INACTIVE) a user account — see
 * adminUsersService.deactivate's docstring for what the backend already
 * enforces (self-guard, last-admin guard, session revocation, audit
 * log). This hook only wires the mutation + cache invalidation; it adds
 * no client-side policy of its own. */
export function useDeactivateUser() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (userId) => adminUsersService.deactivate(userId),
    onSuccess: () => invalidateEmployeeAccounts(queryClient),
  });
}

/** Reactivates a previously-deactivated account (status -> ACTIVE). */
export function useActivateUser() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (userId) => adminUsersService.activate(userId),
    onSuccess: () => invalidateEmployeeAccounts(queryClient),
  });
}

/** Deletes (soft-delete via deleted_at) a still-pending/rejected user
 * account — see adminUsersService.deleteUser's docstring for what the
 * backend already enforces (self-guard, session revocation, audit
 * log). This hook only wires the mutation + cache invalidation; it adds
 * no client-side policy of its own. */
export function useDeleteUser() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (userId) => adminUsersService.deleteUser(userId),
    onSuccess: () => invalidateEmployeeAccounts(queryClient),
  });
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

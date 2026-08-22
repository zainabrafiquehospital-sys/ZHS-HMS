'use client';

import { useMutation, useQueries, useQuery, useQueryClient } from '@tanstack/react-query';
import { visitsService } from '@/features/visits/api/visitsService';
import { adminUsersService } from '@/features/admin/api/adminUsersService';
import { receptionService } from '@/features/reception/api/receptionService';

export { usePatientsForVisits } from '@/features/patients/hooks/usePatientsForVisits';

/** Every Visit registered on `dayKey` (a `displayDayKey`-shaped
 * "YYYY-MM-DD" string, DISPLAY_TIMEZONE), hospital-wide — the Admin
 * Overview's day-scoped view, backed by `GET /visits`'s real
 * server-side `date` filter (see visitsService.listForDay and
 * backend/app/modules/visits/repository.py's `search`), not a "fetch
 * 100 recent + filter client-side" approximation. That older approach
 * could silently under-count a day's visits once hospital-wide volume
 * grew past 100 registrations since that day — this is now a real,
 * always-accurate query regardless of volume. */
export function useAdminVisitsForDay(dayKey) {
  const query = useQuery({
    queryKey: ['visits', 'admin', 'day', dayKey],
    queryFn: () => visitsService.listForDay({ date: dayKey }).then((res) => res.data),
    enabled: Boolean(dayKey),
    refetchInterval: 20000,
  });
  return { ...query, visits: query.data ?? [] };
}

/** All-time outstanding balance across every currently partially-paid
 * visit, hospital-wide (2026-08-22 addition) — deliberately NOT scoped
 * to `selectedDate` like the other revenue tiles/`useAdminVisitsForDay`
 * above: a balance left over from a visit registered weeks ago must
 * still show up today (see visitsService.getPendingRevenue's own
 * docstring). Its own query key/short refetch interval, independent of
 * the day-scoped visits query the other three revenue tiles read from. */
export function usePendingRevenue() {
  const query = useQuery({
    queryKey: ['visits', 'pending-revenue'],
    queryFn: () => visitsService.getPendingRevenue().then((res) => res.data),
    refetchInterval: 20000,
  });
  return query.data?.pending_revenue ?? '0.00';
}

/** Joins each Visit's `created_by` (VisitOut, see visits/schemas.py) to
 * the registering user's name, for the "Booked By" column — same
 * cached-lookup-per-unique-id join pattern as `usePatientsForVisits`,
 * reusing the already-permission-gated `GET /users/{id}` (admin holds
 * `users:read` via the full permission catalog) rather than a new
 * backend endpoint. `created_by` is nullable (BaseEntity's audit column
 * is `ON DELETE SET NULL`), so visits with no recorded actor are simply
 * skipped, not queried. */
export function useReceptionistsForVisits(visits) {
  const uniqueUserIds = [
    ...new Set((visits ?? []).map((visit) => visit.created_by).filter(Boolean)),
  ];
  const results = useQueries({
    queries: uniqueUserIds.map((userId) => ({
      queryKey: ['admin', 'users', userId],
      queryFn: () => adminUsersService.getById(userId).then((res) => res.data),
      enabled: Boolean(userId),
    })),
  });
  const byId = {};
  uniqueUserIds.forEach((id, index) => {
    byId[id] = results[index]?.data;
  });
  return byId;
}

/** Admin-only "Edit Slip" — corrects a visit's own procedure/amount
 * and/or its linked patient's identity fields in one call (see
 * receptionService.updateVisit's docstring). Invalidates every cached
 * day-scoped admin visit list (`['visits', 'admin', 'day']` is a
 * prefix match, not one specific day — the edited visit could be
 * showing on whichever day is currently selected) and every cached
 * Patient lookup (`usePatientsForVisits`'s `['patients', id]` keys) so
 * the corrected name/phone appear immediately without a manual
 * refresh. */
export function useUpdateVisit() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ visitId, updates }) => receptionService.updateVisit(visitId, updates),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['visits', 'admin', 'day'] });
      queryClient.invalidateQueries({ queryKey: ['patients'] });
    },
  });
}

/** Admin-only visit deletion (see receptionService.deleteVisit's
 * docstring) — same invalidation shape as useUpdateVisit above; the
 * deleted visit simply stops appearing in the next day-scoped fetch
 * (the backend already excludes soft-deleted visits from every query). */
export function useDeleteVisit() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (visitId) => receptionService.deleteVisit(visitId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['visits', 'admin', 'day'] });
    },
  });
}

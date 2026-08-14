'use client';

import { useQueries, useQuery } from '@tanstack/react-query';
import { visitsService } from '@/features/visits/api/visitsService';
import { adminUsersService } from '@/features/admin/api/adminUsersService';
import { displayDayKey, isWithinCurrentShiftWindow } from '@/utils/timezone';

export { usePatientsForVisits } from '@/features/patients/hooks/usePatientsForVisits';

/** Every Visit registered on `dayKey` (a `displayDayKey`-shaped
 * "YYYY-MM-DD" string, DISPLAY_TIMEZONE) — the Admin overview's
 * hospital-wide equivalent of Reception's own `useTodaysRegistrations`
 * (features/reception/hooks/useReception.js), same fetch shape and
 * same GET /visits reuse, but parameterized by an admin-selected day
 * rather than hardcoded to today, and read via `visits:read` (which
 * the admin role holds, same as every other permission in the full
 * catalog) rather than being scoped to what Reception itself submitted.
 *
 * Same GET /visits limitation as Reception's hook: no server-side date
 * filter exists (see visits/router.py), so this fetches the 100 most
 * recent Visits sorted newest-first and filters to `dayKey` client-side
 * — complete for any single day with ≤100 registrations, same
 * documented follow-up (real server-side date filtering) as Reception's
 * identical hook. Deliberately not a separate query per day: one
 * "recent visits" fetch (kept warm by the same 20s poll Reception's
 * table uses) is filtered against whichever day is currently selected,
 * so flipping between days the already-fetched window covers is
 * instant, no extra network round trip. */
export function useAdminRecentVisits() {
  return useQuery({
    queryKey: ['visits', 'admin', 'recent'],
    queryFn: () =>
      visitsService.list({ pageSize: 100, sortOrder: 'desc' }).then((res) => res.data),
    refetchInterval: 20000,
  });
}

export function useAdminVisitsForDay(dayKey) {
  const query = useAdminRecentVisits();
  const visits = (query.data ?? []).filter((visit) => displayDayKey(visit.created_at) === dayKey);
  return { ...query, visits };
}

/** Every Visit registered hospital-wide during the CURRENTLY-ACTIVE
 * shift's real window — the Admin Overview's shift-aware sibling of
 * `useAdminVisitsForDay`, added alongside it rather than replacing it.
 * Reuses the exact same `useAdminRecentVisits()` fetch: that feed is
 * already unscoped by calendar date (the 100 most recent Visits
 * hospital-wide), so it already covers a Night shift's pre-midnight
 * portion without any second network call — the same reasoning
 * Reception's `useTodaysRegistrations` shift figure relies on (see
 * that hook's docstring). `isWithinCurrentShiftWindow` (utils/
 * timezone.js) is real-start/end-instant based, not hour-of-day
 * bucketing, so this is correct across the midnight rollover. */
export function useAdminVisitsForCurrentShift() {
  const query = useAdminRecentVisits();
  const visits = (query.data ?? []).filter((visit) => isWithinCurrentShiftWindow(visit.created_at));
  return { ...query, visits };
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

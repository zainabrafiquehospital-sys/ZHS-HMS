'use client';

import { useQueries, useQuery } from '@tanstack/react-query';
import { visitsService } from '@/features/visits/api/visitsService';
import { adminUsersService } from '@/features/admin/api/adminUsersService';

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

import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { receptionService } from '@/features/reception/api/receptionService';
import { visitsService } from '@/features/visits/api/visitsService';
import { adminStatsService } from '@/features/admin/api/adminStatsService';
import { useAuth } from '@/features/auth/hooks/useAuth';
import { openAndPrintHtml } from '@/utils/printWindow';

export { usePatientsForVisits } from '@/features/patients/hooks/usePatientsForVisits';

export function useRegisterVisit() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload) => receptionService.registerVisit(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['queue'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard'] });
      // Broad ['visits'] prefix, not just ['visits', 'reception'] — a
      // newly registered/cancelled Visit is relevant to every visits-
      // consuming view in the same browser session (Admin overview's
      // ['visits', 'admin', 'recent'], Billing/Vitals worklists), not
      // only Reception's own table. TanStack Query matches invalidation
      // by prefix, so this one call covers all of them.
      queryClient.invalidateQueries({ queryKey: ['visits'] });
    },
  });
}

export function useCancelVisit() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ visitId, reason }) => receptionService.cancelVisit(visitId, reason),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['queue'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard'] });
      // Broad ['visits'] prefix, not just ['visits', 'reception'] — a
      // newly registered/cancelled Visit is relevant to every visits-
      // consuming view in the same browser session (Admin overview's
      // ['visits', 'admin', 'recent'], Billing/Vitals worklists), not
      // only Reception's own table. TanStack Query matches invalidation
      // by prefix, so this one call covers all of them.
      queryClient.invalidateQueries({ queryKey: ['visits'] });
    },
  });
}

/** Every Visit *this receptionist has ever personally registered* — the
 * Reception page's own worklist — distinct from the Dashboard's
 * `visits_by_status`/`queue_waiting_by_destination` aggregate counts
 * (app/modules/dashboard/schemas.py), which summarize but never list
 * individual rows.
 *
 * Filtered ONLY by `created_by === current_user.id` — no date or shift
 * restriction at all, a deliberate simplification (this previously
 * tried a calendar-day filter, then a shift-window filter on top of
 * that; both were removed — see git history if that reasoning is ever
 * needed again — in favor of "everything I've ever registered", the
 * simplest and only version of this that can never silently drop a
 * receptionist's own slip for a date/shift-boundary reason). A real
 * server-side filter (`GET /visits?created_by=`, see
 * visitsService.listForCreator and backend/app/modules/visits/
 * repository.py's `search`), not a client-side approximation over a
 * capped "recent visits" fetch — real pagination, so this stays
 * correct and fast regardless of how many visits this receptionist
 * has ever registered. */
export function useMyRegistrations({ page, pageSize }) {
  const { user } = useAuth();
  const query = useQuery({
    queryKey: ['visits', 'reception', 'own', user?.id, { page, pageSize }],
    queryFn: () =>
      visitsService
        .listForCreator({ createdBy: user.id, page, pageSize })
        .then((res) => ({ visits: res.data, meta: res.meta })),
    enabled: Boolean(user?.id),
    placeholderData: keepPreviousData,
    refetchInterval: 20000,
  });
  return {
    ...query,
    visits: query.data?.visits ?? [],
    meta: query.data?.meta ?? null,
  };
}

/** This receptionist's own all-time revenue + slip count — the "My
 * Revenue"/"My Slips" tiles. A real server-side aggregate (`GET
 * /visits/stats/by-creator`, this receptionist's own row looked up by
 * their own user id — see adminStatsService.getVisitStatsByCreator and
 * backend/app/modules/visits/repository.py's
 * `count_and_revenue_by_creator`), never derived by summing a
 * paginated page of `useMyRegistrations` client-side, which would only
 * ever reflect whatever page happens to be on screen. Reuses the exact
 * same endpoint the Admin "Employee Accounts & Stats" page already
 * calls (gated on `visits:read`, which every receptionist already
 * holds) rather than adding a second one. */
export function useMyRevenueStats() {
  const { user } = useAuth();
  const query = useQuery({
    queryKey: ['visits', 'stats', 'by-creator'],
    queryFn: () => adminStatsService.getVisitStatsByCreator().then((res) => res.data),
  });
  const own = query.data?.find((row) => row.user_id === user?.id);
  return {
    ...query,
    revenue: own?.revenue ?? '0.00',
    count: own?.count ?? 0,
  };
}

/** Fetches the registration slip as an HTML document and opens it in a
 * new tab for printing, mirroring the Billing receipt print flow — see
 * receptionService.fetchRegistrationSlipHtml's docstring. Printing
 * failures never affect the already-successful registration: this is
 * a read-only fetch triggered by its own "Print Slip" button, callable
 * again at any time to reprint. */
export function usePrintRegistrationSlip() {
  return useMutation({
    mutationFn: async (visitId) => {
      const html = await receptionService.fetchRegistrationSlipHtml(visitId);
      await openAndPrintHtml(html);
    },
  });
}

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { receptionService } from '@/features/reception/api/receptionService';
import { visitsService } from '@/features/visits/api/visitsService';
import { useAuth } from '@/features/auth/hooks/useAuth';
import { selectOwnSlipsToday } from '@/features/reception/utils/ownSlips';
import { todayDisplayDayKey } from '@/utils/timezone';
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

/** Every Visit *this receptionist personally registered today* (Phase
 * 6's registration-slip record), for the Reception page's own
 * worklist — distinct from the Dashboard's `visits_by_status`/
 * `queue_waiting_by_destination` aggregate counts
 * (app/modules/dashboard/schemas.py), which summarize but never list
 * individual rows. No module owns a "list visits by this receptionist
 * today" endpoint, so this reuses the existing, already-permission-gated
 * `GET /visits` (visits:read) exactly like the Vitals/Billing/Doctor
 * worklists already do (see visitsService.js), rather than adding a new
 * backend endpoint for what's fundamentally the same data with a
 * different filter.
 *
 * Filtered by `created_by === current_user.id AND displayDayKey(
 * created_at) === today` — both real fields on the fetched Visit rows,
 * compared against the live authenticated session's own id
 * (`useAuth()`) and the current calendar day (utils/timezone.js). This
 * is deliberately never derived from session/counter/"submit-then-
 * clear" state: every render re-fetches (or reads the already-fetched
 * TanStack Query cache) and re-filters from scratch, so a logout/login,
 * a closed tab, or a lost page all show exactly what a fresh query
 * would show — there is nothing here that accumulates and nothing here
 * that a browser event could reset independently of the underlying
 * data. (This previously used a shift-window filter instead of a
 * calendar-day one — see git history if that reasoning is ever needed
 * again; per-receptionist "my slips today" made the shift concept the
 * wrong axis entirely, since a receptionist's own workday isn't
 * required to align with the hospital's shift boundaries.)
 *
 * `GET /visits` has no server-side date filter (see visits/router.py) —
 * every filter it exposes is patient_id/doctor_user_id/unassigned_only/
 * status, none of them date- or creator-based. This fetches the 100
 * most recent Visits (the API's own page_size cap) sorted newest-first
 * and filters client-side, in DISPLAY_TIMEZONE (not the browser's local
 * zone — see utils/timezone.js). Since results are already newest-
 * first, this is complete for any receptionist with ≤100 registrations
 * hospital-wide today; a very high-volume day across all receptionists
 * combined could silently lose this receptionist's earliest rows off
 * the list — a documented follow-up (add real server-side date +
 * created_by filtering to GET /visits) rather than a problem worth a
 * multi-page client-side fetch loop for today's expected volume.
 *
 * The actual filter is `selectOwnSlipsToday` (features/reception/
 * utils/ownSlips.js) — a plain, dependency-free function so it's
 * directly unit-testable for the two properties that actually matter
 * here (scoped to creator+today, provably unaffected by session
 * state) without any React/DOM test machinery. */
export function useTodaysRegistrations() {
  const { user } = useAuth();
  const query = useQuery({
    queryKey: ['visits', 'reception', 'recent'],
    queryFn: () => visitsService.list({ pageSize: 100, sortOrder: 'desc' }).then((res) => res.data),
    refetchInterval: 20000,
  });

  const visits = selectOwnSlipsToday(query.data, user?.id, todayDisplayDayKey());

  return { ...query, visits };
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

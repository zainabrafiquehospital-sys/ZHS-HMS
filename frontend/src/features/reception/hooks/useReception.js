import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { receptionService } from '@/features/reception/api/receptionService';
import { visitsService } from '@/features/visits/api/visitsService';
import { displayDayKey, todayDisplayDayKey } from '@/utils/timezone';
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

/** Every Visit registered "today" (Phase 6's registration-slip record),
 * for the Reception page's own worklist — distinct from the Dashboard's
 * `visits_by_status`/`queue_waiting_by_destination` aggregate counts
 * (app/modules/dashboard/schemas.py), which summarize but never list
 * individual rows. No module owns a "list visits by Reception today"
 * endpoint, so this reuses the existing, already-permission-gated
 * `GET /visits` (visits:read) exactly like the Vitals/Billing/Doctor
 * worklists already do (see visitsService.js), rather than adding a new
 * backend endpoint for what's fundamentally the same data with a
 * different filter.
 *
 * `GET /visits` has no server-side date filter (see visits/router.py) —
 * every filter it exposes is patient_id/doctor_user_id/unassigned_only/
 * status, none of them date-based. This fetches the 100 most recent
 * Visits (the API's own page_size cap) sorted newest-first and filters
 * to "today" client-side, in DISPLAY_TIMEZONE (not the browser's local
 * zone — see utils/timezone.js). Since results are already newest-first,
 * this is complete for any day with ≤100 registrations; a day that
 * exceeds that would silently lose its earliest rows off this list —
 * a documented follow-up (add real server-side date filtering to
 * GET /visits) rather than a problem worth a multi-page client-side
 * fetch loop for today's expected volume. */
export function useTodaysRegistrations() {
  const query = useQuery({
    queryKey: ['visits', 'reception', 'recent'],
    queryFn: () =>
      visitsService
        .list({ pageSize: 100, sortOrder: 'desc' })
        .then((res) => res.data),
    refetchInterval: 20000,
  });

  const today = todayDisplayDayKey();
  const todaysVisits = (query.data ?? []).filter(
    (visit) => displayDayKey(visit.created_at) === today,
  );

  return { ...query, visits: todaysVisits };
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

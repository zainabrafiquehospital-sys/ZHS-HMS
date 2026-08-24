import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { receptionService } from '@/features/reception/api/receptionService';
import { visitsService } from '@/features/visits/api/visitsService';
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

/** This receptionist's own revenue — visits and medicine bills broken
 * out separately, plus a combined total — always capped to roughly the
 * last 24 hours (2026-08-19 fix; originally "since her last Clear
 * Revenue action, or all-time if she's never cleared", which in
 * practice meant an ever-growing cumulative total for receptionists
 * who never pressed Clear Revenue day to day). `clearedAt` reflects
 * the effective window start — `max(last manual clear, now - 24h)` —
 * computed server-side on every request, so it is always a real, recent
 * timestamp. `refetchInterval` keeps the tiles live without requiring a
 * manual reload: the 24h auto-clear needs no button press and no
 * background job (see ReceptionService.get_own_revenue's own
 * docstring), but the browser still only *sees* that recomputed value
 * the next time this query runs.
 *
 * Backed by `GET /reception/revenue` (see receptionService.getMyRevenue),
 * which is hard-scoped server-side to the calling receptionist — there
 * is no user id involved on the frontend at all, unlike the old
 * implementation, which fetched *every* receptionist's row from `GET
 * /visits/stats/by-creator` and picked out one client-side (the same
 * endpoint any receptionist could otherwise call directly to see
 * everyone else's revenue too). */
export function useMyRevenue() {
  const { user } = useAuth();
  const query = useQuery({
    queryKey: ['reception', 'revenue', 'own', user?.id],
    queryFn: () => receptionService.getMyRevenue().then((res) => res.data),
    enabled: Boolean(user?.id),
    refetchInterval: 30000,
  });
  return {
    ...query,
    visitsCount: query.data?.visits_count ?? 0,
    visitsRevenue: query.data?.visits_revenue ?? '0.00',
    medicineBillCount: query.data?.medicine_bill_count ?? 0,
    medicineRevenue: query.data?.medicine_revenue ?? '0.00',
    totalRevenue: query.data?.total_revenue ?? '0.00',
    clearedAt: query.data?.cleared_at ?? null,
  };
}

/** "Clear Revenue" (2026-08-19 addition) — resets the calling
 * receptionist's own `useMyRevenue` display to zero going forward; see
 * receptionService.clearMyRevenue's and the backend's
 * ReceptionService.clear_own_revenue's docstrings for the full
 * mechanism (an audit-log entry, never a deletion — every underlying
 * visit/medicine bill stays completely untouched). Requires the
 * caller's own explicit confirmation step in the UI before this is
 * ever invoked — see MyRegistrations.jsx's ConfirmDialog usage. */
export function useClearMyRevenue() {
  const queryClient = useQueryClient();
  const { user } = useAuth();
  return useMutation({
    mutationFn: () => receptionService.clearMyRevenue(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['reception', 'revenue', 'own', user?.id] });
    },
  });
}

/** Doctors eligible for RegisterVisitForm.jsx's optional "Assign to
 * Doctor" dropdown, each tagged `is_online` (backend: ReceptionRepository.
 * list_doctors_for_selection — the identical online definition
 * find_least_busy_available_doctor's own auto-assignment already uses,
 * see that method's docstring). Short refetch interval, matching the
 * Doctor queue's own 15s polling (DoctorQueueList.jsx) — online status
 * is a live, session-based signal that can flip at any moment as
 * doctors log in/out, so a stale list would misrepresent who Reception
 * can actually reach right now more than most other cached reads
 * would. */
export function useDoctorsForSelection() {
  const query = useQuery({
    queryKey: ['reception', 'doctors'],
    queryFn: () => receptionService.listDoctorsForSelection().then((res) => res.data),
    refetchInterval: 15000,
  });
  return { ...query, doctors: query.data ?? [] };
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

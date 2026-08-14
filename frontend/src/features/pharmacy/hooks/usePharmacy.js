'use client';

import { useMutation, useQueries, useQuery, useQueryClient } from '@tanstack/react-query';
import { pharmacyService } from '@/features/pharmacy/api/pharmacyService';
import { adminUsersService } from '@/features/admin/api/adminUsersService';
import { visitsService } from '@/features/visits/api/visitsService';
import { openAndPrintHtml } from '@/utils/printWindow';
import {
  displayDayKey,
  getCurrentShiftWindow,
  isWithinCurrentShiftWindow,
  todayDisplayDayKey,
} from '@/utils/timezone';

/** Admin management listing — every medicine, active and inactive alike
 * (see pharmacyService.listMedicines's docstring). */
export function useMedicines() {
  return useQuery({
    queryKey: ['pharmacy', 'medicines', 'admin'],
    queryFn: () => pharmacyService.listMedicines().then((res) => res.data),
  });
}

function invalidateMedicines(queryClient) {
  queryClient.invalidateQueries({ queryKey: ['pharmacy', 'medicines'] });
}

export function useCreateMedicine() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload) => pharmacyService.createMedicine(payload),
    onSuccess: () => invalidateMedicines(queryClient),
  });
}

export function useUpdateMedicine() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ medicineId, payload }) => pharmacyService.updateMedicine(medicineId, payload),
    onSuccess: () => invalidateMedicines(queryClient),
  });
}

export function useCreateMedicineBill() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload) => pharmacyService.createBill(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['pharmacy', 'bills'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard'] });
    },
  });
}

/** Records a payment against a just-finalized (UNPAID/PARTIALLY_PAID)
 * medicine bill — same shape as billing/hooks/useBilling.js's
 * useRecordPayment. */
export function useRecordMedicineBillPayment() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ billId, amount }) => pharmacyService.recordPayment(billId, amount),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['pharmacy', 'bills'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard'] });
    },
  });
}

/** Every medicine bill created on `dayKey`'s UTC calendar date — the
 * Admin Overview's Medicine Bills tab. Unlike the Visit listing's own
 * client-side "today" filter (see useAdminOverview.js's docstring), this
 * is a real server-side date filter (`GET /pharmacy/bills?date=`), so
 * there is no ≤100-rows-per-day caveat here.
 *
 * `dayKey` is a DISPLAY_TIMEZONE (Asia/Karachi) calendar day, passed
 * straight through as the backend's `date` query param, which the
 * repository interprets as a UTC calendar day (see
 * app/modules/pharmacy/repository.py's `list_for_day` docstring) — the
 * same documented simplification `InvoiceRepository.get_today_summary`
 * already carries, not a new gap this hook introduces. A bill created
 * in the first/last few hours of a Karachi calendar day (UTC+5) can
 * therefore appear to be listed under the adjacent day near midnight. */
export function useMedicineBillsForDay(dayKey) {
  return useQuery({
    queryKey: ['pharmacy', 'bills', 'day', dayKey],
    queryFn: () => pharmacyService.listBillsForDay(dayKey).then((res) => res.data),
    enabled: Boolean(dayKey),
  });
}

/** Every medicine bill created hospital-wide during the CURRENTLY-
 * ACTIVE shift's real window — the Admin Overview's shift-aware
 * sibling of `useMedicineBillsForDay`, added alongside it rather than
 * replacing it. Unlike Visits (one undated "100 most recent" fetch
 * already covers any shift — see useAdminOverview.js's
 * `useAdminVisitsForCurrentShift`), `GET /pharmacy/bills` has no such
 * feed: it only ever filters by one real server-side calendar `date`
 * at a time. A Night shift's pre-midnight portion can fall on
 * *yesterday's* DISPLAY_TIMEZONE date relative to "now", so this always
 * fetches today's bills and — only when the current shift's own start
 * instant actually falls on a different DISPLAY_TIMEZONE date than
 * today (i.e. "now" is in the post-midnight half of an overnight
 * shift) — additionally fetches yesterday's, merges both, and filters
 * the combined set by `isWithinCurrentShiftWindow`. For Morning/Evening
 * (never wraps) or the late half of Night (started earlier today),
 * today's own fetch alone is always sufficient — the second fetch is
 * genuinely conditional, not a standing cost. `now` is a single
 * snapshot for the whole hook body so the shift-window calculation and
 * the eventual filter agree with each other even if a render happens to
 * straddle a real clock tick.
 *
 * `enabled` (default `true`) lets a caller that only ever displays
 * this when a day-picker is on today (e.g. Admin Overview — see that
 * component's own "current shift" concept doesn't apply to a past day)
 * skip firing these fetches at all while viewing a different day,
 * rather than fetching data it won't render. */
export function useMedicineBillsForCurrentShift({ enabled = true } = {}) {
  const now = new Date();
  const todayKey = todayDisplayDayKey();
  const { startsAt } = getCurrentShiftWindow(now);
  const startDayKey = displayDayKey(startsAt.toISOString());
  const needsYesterday = startDayKey !== todayKey;

  const todayQuery = useQuery({
    queryKey: ['pharmacy', 'bills', 'day', todayKey],
    queryFn: () => pharmacyService.listBillsForDay(todayKey).then((res) => res.data),
    enabled,
  });
  const yesterdayQuery = useQuery({
    queryKey: ['pharmacy', 'bills', 'day', startDayKey],
    queryFn: () => pharmacyService.listBillsForDay(startDayKey).then((res) => res.data),
    enabled: enabled && needsYesterday,
  });

  const combined = [
    ...(todayQuery.data ?? []),
    ...(needsYesterday ? (yesterdayQuery.data ?? []) : []),
  ];
  const bills = combined.filter((bill) => isWithinCurrentShiftWindow(bill.created_at, now));

  return {
    bills,
    isLoading: todayQuery.isLoading || (needsYesterday && yesterdayQuery.isLoading),
    isError: todayQuery.isError || (needsYesterday && yesterdayQuery.isError),
    error: todayQuery.error ?? (needsYesterday ? yesterdayQuery.error : null),
  };
}

/** Enriches a list of medicine bills with their linked Visit (only for
 * bills that have one — `visit_id` is nullable, see
 * app/modules/pharmacy/models.py's `MedicineBill` docstring), the same
 * cached-lookup-per-unique-id join pattern as
 * features/patients/hooks/usePatientsForVisits.js. Feed the result into
 * `usePatientsForVisits` to go one hop further, from Visit to Patient. */
export function useVisitsForMedicineBills(bills) {
  const uniqueVisitIds = [...new Set((bills ?? []).map((bill) => bill.visit_id).filter(Boolean))];
  const results = useQueries({
    queries: uniqueVisitIds.map((visitId) => ({
      queryKey: ['visits', visitId],
      queryFn: () => visitsService.getById(visitId).then((res) => res.data),
      enabled: Boolean(visitId),
    })),
  });
  const byId = {};
  uniqueVisitIds.forEach((id, index) => {
    byId[id] = results[index]?.data;
  });
  return byId;
}

/** Joins each medicine bill's `created_by` (MedicineBillSummaryOut, see
 * pharmacy/schemas.py — the inherited `BaseEntity` audit column, not a
 * separate receptionist column; see MedicineBill's own docstring) to the
 * billing user's name, for the Admin Overview's "Billed By" column —
 * identical join pattern to `useReceptionistsForVisits`
 * (features/admin/hooks/useAdminOverview.js), reusing the same
 * already-permission-gated `GET /users/{id}`. */
export function useUsersForMedicineBills(bills) {
  const uniqueUserIds = [...new Set((bills ?? []).map((bill) => bill.created_by).filter(Boolean))];
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

/** Recent visits for one patient, newest first — powers the
 * receptionist's optional "link to visit" picker in
 * MedicineBillingWorkspace. No dedicated visit-search endpoint exists;
 * this composes patientsService.search's result (a patient id) with
 * `GET /visits?patient_id=`, the same server-side filter
 * visitsService.listForDoctor already exercises (with a different
 * column). */
export function useVisitsForPatient(patientId) {
  return useQuery({
    queryKey: ['visits', 'patient', patientId],
    queryFn: () => visitsService.listForPatient(patientId).then((res) => res.data),
    enabled: Boolean(patientId),
  });
}

/** Fetches the medicine bill slip as an HTML document and opens it in a
 * new tab for printing — see billingService.fetchInvoiceReceiptHtml's
 * docstring for why this can't be a plain <a href>. */
export function usePrintMedicineBill() {
  return useMutation({
    mutationFn: async (billId) => {
      const html = await pharmacyService.fetchMedicineBillReceiptHtml(billId);
      await openAndPrintHtml(html);
    },
  });
}

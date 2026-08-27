'use client';

import { useMutation, useQueries, useQuery, useQueryClient } from '@tanstack/react-query';
import { labService } from '@/features/lab/api/labService';
import { adminUsersService } from '@/features/admin/api/adminUsersService';
import { patientsService } from '@/features/patients/api/patientsService';
import { useAuth } from '@/features/auth/hooks/useAuth';
import { openAndPrintHtml } from '@/utils/printWindow';

/** Admin management listing — every test, active and inactive alike
 * (see labService.listTests's docstring). */
export function useLabTests() {
  return useQuery({
    queryKey: ['lab', 'tests', 'admin'],
    queryFn: () => labService.listTests().then((res) => res.data),
  });
}

function invalidateTests(queryClient) {
  queryClient.invalidateQueries({ queryKey: ['lab', 'tests'] });
}

export function useCreateLabTest() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload) => labService.createTest(payload),
    onSuccess: () => invalidateTests(queryClient),
  });
}

export function useUpdateLabTest() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ labTestId, payload }) => labService.updateTest(labTestId, payload),
    onSuccess: () => invalidateTests(queryClient),
  });
}

export function useCreateLabBill() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload) => labService.createBill(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['lab', 'bills'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard'] });
    },
  });
}

/** Records a payment against a just-finalized (UNPAID/PARTIALLY_PAID)
 * lab bill — same shape as usePharmacy.js's useRecordMedicineBillPayment. */
export function useRecordLabBillPayment() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ billId, amount, paymentMethod }) =>
      labService.recordPayment(billId, amount, paymentMethod),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['lab', 'bills'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard'] });
    },
  });
}

/** Every lab bill created on `dayKey`'s UTC calendar date — the Admin
 * Overview's Lab Bills tab. Same UTC-calendar-day caveat as
 * usePharmacy.js's identical useMedicineBillsForDay — see that hook's
 * own docstring. */
export function useLabBillsForDay(dayKey) {
  return useQuery({
    queryKey: ['lab', 'bills', 'day', dayKey],
    queryFn: () => labService.listBillsForDay(dayKey).then((res) => res.data),
    enabled: Boolean(dayKey),
  });
}

/** Full detail for one bill (manual_patient_age/_phone, discount_reason
 * — not present on `useLabBillsForDay`'s lighter summary rows) —
 * fetched on demand to pre-fill the admin "Edit Bill" dialog. */
export function useLabBillDetail(billId) {
  return useQuery({
    queryKey: ['lab', 'bills', 'detail', billId],
    queryFn: () => labService.getBill(billId).then((res) => res.data),
    enabled: Boolean(billId),
  });
}

/** Admin-only "Edit Bill" — corrects a mistakenly-created bill's manual
 * patient details and/or discount (see labService.updateBill's
 * docstring). Same invalidation shape as usePharmacy.js's
 * useUpdateMedicineBill. */
export function useUpdateLabBill() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ billId, updates }) => labService.updateBill(billId, updates),
    onSuccess: (_data, { billId }) => {
      queryClient.invalidateQueries({ queryKey: ['lab', 'bills', 'day'] });
      queryClient.invalidateQueries({ queryKey: ['lab', 'bills', 'detail', billId] });
    },
  });
}

/** Admin-only lab bill deletion (see labService.deleteBill's docstring)
 * — same invalidation shape as usePharmacy.js's useDeleteMedicineBill. */
export function useDeleteLabBill() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (billId) => labService.deleteBill(billId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['lab', 'bills', 'day'] });
    },
  });
}

/** Every lab bill this receptionist has personally created, newest
 * first, no date restriction — the lab-bill sibling of usePharmacy.js's
 * useMyMedicineBills: a real, unbounded server-side filter (`GET
 * /lab/bills/mine`, hard-scoped to the caller), fetched as one
 * generously-sized page for the UI to search/display-paginate over
 * client-side. */
export function useMyLabBills({ page, pageSize }) {
  const { user } = useAuth();
  const query = useQuery({
    queryKey: ['lab', 'bills', 'mine', user?.id, { page, pageSize }],
    queryFn: () =>
      labService.listMyBills({ page, pageSize }).then((res) => ({
        bills: res.data,
        meta: res.meta,
      })),
    enabled: Boolean(user?.id),
    refetchInterval: 20000,
  });
  return {
    ...query,
    bills: query.data?.bills ?? [],
    meta: query.data?.meta ?? null,
  };
}

/** Enriches a list of lab bills with their linked Patient (only for
 * bills that have one — `patient_id` is nullable, see app/modules/lab/
 * models.py's `LabBill` docstring: a direct Patient link, never
 * Visit-mediated, so this is a single-hop join — unlike Pharmacy's own
 * two-hop `useVisitsForMedicineBills` + `usePatientsForVisits`). */
export function usePatientsForLabBills(bills) {
  const uniquePatientIds = [
    ...new Set((bills ?? []).map((bill) => bill.patient_id).filter(Boolean)),
  ];
  const results = useQueries({
    queries: uniquePatientIds.map((patientId) => ({
      queryKey: ['patients', patientId],
      queryFn: () => patientsService.getById(patientId).then((res) => res.data),
      enabled: Boolean(patientId),
    })),
  });
  const byId = {};
  uniquePatientIds.forEach((id, index) => {
    byId[id] = results[index]?.data;
  });
  return byId;
}

/** Joins each lab bill's `created_by` to the billing user's name, for
 * the Admin Overview's "Billed By" column — identical join pattern to
 * usePharmacy.js's useUsersForMedicineBills. */
export function useUsersForLabBills(bills) {
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

/** Read-only aggregate for the Admin "Employee Accounts & Stats" page
 * — one row per user who has created at least one lab bill. */
export function useLabBillStatsByCreator() {
  return useQuery({
    queryKey: ['lab', 'bills', 'stats-by-creator'],
    queryFn: () => labService.getBillStatsByCreator().then((res) => res.data),
  });
}

/** Fetches the lab bill slip as an HTML document and opens it in a new
 * tab for printing — see usePharmacy.js's usePrintMedicineBill's
 * identical docstring. */
export function usePrintLabBill() {
  return useMutation({
    mutationFn: async (billId) => {
      const html = await labService.fetchLabBillReceiptHtml(billId);
      await openAndPrintHtml(html);
    },
  });
}

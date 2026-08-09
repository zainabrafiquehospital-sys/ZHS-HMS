'use client';

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { billingService } from '@/features/billing/api/billingService';
import { visitsService } from '@/features/visits/api/visitsService';
import { openAndPrintHtml } from '@/utils/printWindow';

export { usePatientsForVisits } from '@/features/patients/hooks/usePatientsForVisits';

/** Billing has no Queue destination (Phase 6 §5.1/§5.2 — billing happens
 * at the Reception counter, not a routed physical location), so the
 * worklist is a plain Visit-status filter rather than a queue worklist,
 * unlike Vitals/Doctor Queue. Visits become billable once WAITING_BILLING
 * (first invoice) and can return via PAYMENT_PENDING (a later invoice
 * reopened after COMPLETED — Phase 6 §4.1/§7.4). */
export function useBillingWorklist() {
  const waitingBilling = useQuery({
    queryKey: ['visits', 'billing', 'waiting_billing'],
    queryFn: () => visitsService.list({ status: 'waiting_billing' }).then((res) => res.data),
    refetchInterval: 15000,
  });
  const paymentPending = useQuery({
    queryKey: ['visits', 'billing', 'payment_pending'],
    queryFn: () => visitsService.list({ status: 'payment_pending' }).then((res) => res.data),
    refetchInterval: 15000,
  });
  const visits = [...(waitingBilling.data ?? []), ...(paymentPending.data ?? [])];
  return {
    visits,
    isLoading: waitingBilling.isLoading || paymentPending.isLoading,
  };
}

export function useVisit(visitId) {
  return useQuery({
    queryKey: ['visits', visitId],
    queryFn: () => visitsService.getById(visitId).then((res) => res.data),
    enabled: Boolean(visitId),
  });
}

export function usePendingItems(visitId) {
  return useQuery({
    queryKey: ['billing', 'pending-items', visitId],
    queryFn: () => billingService.listPendingItems(visitId).then((res) => res.data),
    enabled: Boolean(visitId),
  });
}

export function useInvoicesForVisit(visitId) {
  return useQuery({
    queryKey: ['billing', 'invoices', 'visit', visitId],
    queryFn: () => billingService.listInvoicesForVisit(visitId).then((res) => res.data),
    enabled: Boolean(visitId),
  });
}

function invalidateVisitBilling(queryClient, visitId) {
  queryClient.invalidateQueries({ queryKey: ['billing', 'pending-items', visitId] });
  queryClient.invalidateQueries({ queryKey: ['billing', 'invoices', 'visit', visitId] });
  queryClient.invalidateQueries({ queryKey: ['visits', visitId] });
  queryClient.invalidateQueries({ queryKey: ['visits', 'billing'] });
  queryClient.invalidateQueries({ queryKey: ['dashboard'] });
}

export function useApprovePendingItem(visitId) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (itemId) => billingService.approvePendingItem(itemId),
    onSuccess: () => invalidateVisitBilling(queryClient, visitId),
  });
}

export function useRejectPendingItem(visitId) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (itemId) => billingService.rejectPendingItem(itemId),
    onSuccess: () => invalidateVisitBilling(queryClient, visitId),
  });
}

export function useGenerateInvoice(visitId) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload) => billingService.generateInvoice(payload),
    onSuccess: () => invalidateVisitBilling(queryClient, visitId),
  });
}

export function useRecordPayment(visitId) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ invoiceId, amount }) => billingService.recordPayment(invoiceId, amount),
    onSuccess: () => invalidateVisitBilling(queryClient, visitId),
  });
}

/** Fetches the invoice receipt as an HTML document and opens it in a new
 * tab for printing — see billingService.fetchInvoiceReceiptHtml's
 * docstring for why this can't be a plain <a href>. */
export function usePrintInvoice() {
  return useMutation({
    mutationFn: async (invoiceId) => {
      const html = await billingService.fetchInvoiceReceiptHtml(invoiceId);
      await openAndPrintHtml(html);
    },
  });
}

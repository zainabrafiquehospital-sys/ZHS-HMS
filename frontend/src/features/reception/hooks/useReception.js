import { useMutation, useQueryClient } from '@tanstack/react-query';
import { receptionService } from '@/features/reception/api/receptionService';

export function useRegisterVisit() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload) => receptionService.registerVisit(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['queue'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard'] });
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
    },
  });
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
      const printWindow = window.open('', '_blank');
      if (!printWindow) {
        throw new Error('Unable to open print window — check your browser popup settings.');
      }
      printWindow.document.write(html);
      printWindow.document.close();
      printWindow.focus();
      printWindow.print();
    },
  });
}

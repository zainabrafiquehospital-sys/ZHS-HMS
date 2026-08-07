import { httpClient } from '@/services/api/httpClient';

export const receptionService = {
  registerVisit(payload) {
    return httpClient.post('/reception/visits', payload);
  },

  cancelVisit(visitId, reason) {
    return httpClient.post(`/reception/visits/${visitId}/cancel`, { reason: reason ?? null });
  },

  // Returns a raw HTML document (not the JSON envelope) — see
  // billingService.fetchInvoiceReceiptHtml's identical docstring for
  // why this is fetched rather than a plain <a href>.
  fetchRegistrationSlipHtml(visitId) {
    return httpClient.get(`/reception/visits/${visitId}/slip/print`, { responseType: 'text' });
  },
};

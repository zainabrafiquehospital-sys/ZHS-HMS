import { httpClient } from '@/services/api/httpClient';

export const receptionService = {
  registerVisit(payload) {
    return httpClient.post('/reception/visits', payload);
  },

  cancelVisit(visitId, reason) {
    return httpClient.post(`/reception/visits/${visitId}/cancel`, { reason: reason ?? null });
  },

  // Admin-only (reception:update_visit / reception:delete_visit — never
  // granted to Receptionist, see backend/app/modules/reception/
  // constants.py) — added 2026-08-19 so a mistakenly-entered slip (e.g.
  // garbage test data) can actually be corrected or removed. Only ever
  // called from the Admin Overview visit table
  // (features/admin/components/AdminOverview.jsx) — never expose these
  // from any Receptionist-facing screen.
  updateVisit(visitId, payload) {
    return httpClient.patch(`/reception/visits/${visitId}`, payload);
  },

  deleteVisit(visitId) {
    return httpClient.delete(`/reception/visits/${visitId}`);
  },

  // Returns a raw HTML document (not the JSON envelope) — see
  // billingService.fetchInvoiceReceiptHtml's identical docstring for
  // why this is fetched rather than a plain <a href>.
  fetchRegistrationSlipHtml(visitId) {
    return httpClient.get(`/reception/visits/${visitId}/slip/print`, { responseType: 'text' });
  },
};

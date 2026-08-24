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

  // "My Revenue" (2026-08-19 addition) — always the calling
  // receptionist's own figures; there is no user-id parameter on
  // either call, matching how the backend hard-scopes both to
  // `actor.id` (see backend/app/modules/reception/router.py).
  getMyRevenue() {
    return httpClient.get('/reception/revenue');
  },

  clearMyRevenue() {
    return httpClient.post('/reception/revenue/clear');
  },

  // Returns a raw HTML document (not the JSON envelope) — see
  // billingService.fetchInvoiceReceiptHtml's identical docstring for
  // why this is fetched rather than a plain <a href>.
  fetchRegistrationSlipHtml(visitId) {
    return httpClient.get(`/reception/visits/${visitId}/slip/print`, { responseType: 'text' });
  },

  // Doctor-selection dropdown (2026-08-24 addition) — RegisterVisitForm.jsx's
  // optional "Assign to Doctor" field. Minimal shape only (id/full_name/
  // is_online) — see backend DoctorSelectionOut's own docstring for why
  // this is a purpose-built endpoint, not the admin GET /users list.
  listDoctorsForSelection() {
    return httpClient.get('/reception/doctors');
  },
};

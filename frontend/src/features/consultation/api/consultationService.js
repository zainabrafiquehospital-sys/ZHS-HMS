import { httpClient } from '@/services/api/httpClient';

export const consultationService = {
  start(visitId) {
    return httpClient.post('/consultations', { visit_id: visitId });
  },

  getActiveForVisit(visitId) {
    return httpClient.get(`/consultations/visits/${visitId}/active`);
  },

  getById(consultationId) {
    return httpClient.get(`/consultations/${consultationId}`);
  },

  // "My Consultations" (2026-09-03) — every consultation the calling
  // doctor has completed, newest first, real server-side pagination
  // (GET /consultations/mine, hard-scoped to the actor). Same shape as
  // vitalsService.listMine / the "My Registrations" endpoint.
  listMine({ page = 1, pageSize = 20 } = {}) {
    return httpClient.get('/consultations/mine', { params: { page, page_size: pageSize } });
  },

  sendToVitals(consultationId, reason) {
    return httpClient.post(`/consultations/${consultationId}/send-to-vitals`, {
      reason: reason || null,
    });
  },

  complete(consultationId, updates) {
    return httpClient.post(`/consultations/${consultationId}/complete`, updates);
  },

  // "View Slip" (2026-08-25 addition) — DoctorQueueList.jsx's own
  // registration-slip button, reusing Reception's exact print endpoint
  // (`reception:view_slip` now satisfies its permission gate alongside
  // Reception's own `reception:register_visit` — see backend
  // reception/dependencies.py's `require_any_permission`). Returns a
  // raw HTML document (not the JSON envelope), same as
  // receptionService.fetchRegistrationSlipHtml's identical shape.
  fetchRegistrationSlipHtml(visitId) {
    return httpClient.get(`/reception/visits/${visitId}/slip/print`, { responseType: 'text' });
  },

  // "Print Prescription" (2026-09-03) — the doctor's prescription slip,
  // a full-page layout meant to overprint paper already bearing the
  // hospital's letterhead (see backend render_prescription_slip). Same
  // raw-HTML shape as fetchRegistrationSlipHtml above; gated server-side
  // on `consultation:read`, which every Doctor already holds.
  fetchPrescriptionSlipHtml(consultationId) {
    return httpClient.get(`/consultations/${consultationId}/slip/print`, { responseType: 'text' });
  },
};

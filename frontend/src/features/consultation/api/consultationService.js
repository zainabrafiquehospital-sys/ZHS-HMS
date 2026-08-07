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

  sendToVitals(consultationId, reason) {
    return httpClient.post(`/consultations/${consultationId}/send-to-vitals`, {
      reason: reason || null,
    });
  },

  complete(consultationId, updates) {
    return httpClient.post(`/consultations/${consultationId}/complete`, updates);
  },
};

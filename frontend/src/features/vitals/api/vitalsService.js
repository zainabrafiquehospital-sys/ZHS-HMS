import { httpClient } from '@/services/api/httpClient';

export const queueService = {
  worklist({ destination, status }) {
    return httpClient.get('/queue/worklist', {
      params: { destination, status, page: 1, page_size: 50 },
    });
  },
};

export const vitalsService = {
  record(payload) {
    return httpClient.post('/vitals', payload);
  },

  listForVisit(visitId) {
    return httpClient.get(`/vitals/visits/${visitId}`);
  },
};

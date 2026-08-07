import { httpClient } from '@/services/api/httpClient';

export const patientsService = {
  search(query) {
    return httpClient.get('/patients', { params: { search: query, page: 1, page_size: 10 } });
  },

  getById(patientId) {
    return httpClient.get(`/patients/${patientId}`);
  },
};

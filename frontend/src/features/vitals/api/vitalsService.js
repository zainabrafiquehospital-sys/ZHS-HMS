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

  // `data` is null (not a 404) when the patient has no prior vitals on
  // any other visit — see backend/app/modules/vitals/router.py's
  // `get_latest_for_patient` docstring.
  latestForPatient(patientId, excludeVisitId) {
    return httpClient.get(`/vitals/patients/${patientId}/latest`, {
      params: { exclude_visit_id: excludeVisitId },
    });
  },
};

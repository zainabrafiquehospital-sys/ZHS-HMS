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

  // Every vitals record ever recorded for this patient, across every
  // visit, newest first — backs the "Show Details" cross-visit history
  // view. `data` is `[]` (never null) when none exist — see
  // backend/app/modules/vitals/router.py's `list_for_patient` docstring.
  historyForPatient(patientId) {
    return httpClient.get(`/vitals/patients/${patientId}/history`);
  },

  // "My Vitals Records" — every vitals record this staff member has
  // personally recorded, newest first, real server-side pagination, no
  // date restriction. The Vitals sibling of visitsService.listForCreator
  // (Reception's "My Registrations"), always the calling user's own
  // records — see backend/app/modules/vitals/router.py's
  // `list_my_records` docstring.
  listMine({ page = 1, pageSize = 20 }) {
    return httpClient.get('/vitals/records/mine', {
      params: { page, page_size: pageSize },
    });
  },
};

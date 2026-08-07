import { httpClient } from '@/services/api/httpClient';

export const visitsService = {
  listForDoctor({ doctorUserId, status }) {
    return httpClient.get('/visits', {
      params: {
        doctor_user_id: doctorUserId,
        status,
        page: 1,
        page_size: 50,
        sort_by: 'created_at',
        sort_order: 'asc',
      },
    });
  },

  // Unscoped listing (no doctor_user_id) — used by worklists that aren't
  // owned by a single doctor, e.g. Billing's Reception-counter worklist,
  // or the Doctor Queue's "unclaimed pool" of fast-registration Visits
  // Reception couldn't auto-assign (unassignedOnly: true).
  list({ status, unassignedOnly }) {
    return httpClient.get('/visits', {
      params: {
        status,
        unassigned_only: unassignedOnly || undefined,
        page: 1,
        page_size: 50,
        sort_by: 'created_at',
        sort_order: 'asc',
      },
    });
  },

  getById(visitId) {
    return httpClient.get(`/visits/${visitId}`);
  },
};

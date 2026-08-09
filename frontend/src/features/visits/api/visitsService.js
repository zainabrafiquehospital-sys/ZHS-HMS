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
  //
  // `pageSize`/`sortOrder` are overridable (default 50/asc, unchanged for
  // existing callers) because Reception's "Today's Registrations" list
  // needs the newest visits first at the API's max page size — GET /visits
  // has no server-side date filter (see useReception.js's
  // useTodaysRegistrations docstring), so fetching the most recent 100
  // and filtering to "today" client-side is the only way to get a
  // complete same-day list without a backend change.
  list({ status, unassignedOnly, pageSize = 50, sortOrder = 'asc' }) {
    return httpClient.get('/visits', {
      params: {
        status,
        unassigned_only: unassignedOnly || undefined,
        page: 1,
        page_size: pageSize,
        sort_by: 'created_at',
        sort_order: sortOrder,
      },
    });
  },

  getById(visitId) {
    return httpClient.get(`/visits/${visitId}`);
  },
};

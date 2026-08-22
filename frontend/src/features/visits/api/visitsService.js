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

  // Unscoped listing (no doctor_user_id/created_by) — used by worklists
  // that aren't owned by a single doctor or receptionist, e.g. Billing's
  // Reception-counter worklist, or the Doctor Queue's "unclaimed pool"
  // of fast-registration Visits Reception couldn't auto-assign
  // (unassignedOnly: true). `pageSize`/`sortOrder` are overridable
  // (default 50/asc) for callers that need a different page/order.
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

  // Recent visits for one patient, newest first — powers the Medicine
  // Billing workspace's optional "link to visit" picker (see
  // features/pharmacy/hooks/usePharmacy.js's useVisitsForPatient), the
  // one caller of GET /visits' server-side patient_id filter.
  listForPatient(patientId) {
    return httpClient.get('/visits', {
      params: {
        patient_id: patientId,
        page: 1,
        page_size: 20,
        sort_by: 'created_at',
        sort_order: 'desc',
      },
    });
  },

  // Every visit a specific user has ever registered, newest first — a
  // real server-side filter (GET /visits?created_by=), never a "fetch
  // N recent + filter client-side" approximation that could silently
  // drop older rows once hospital-wide volume grows. Powers Reception's
  // own "My Registrations" list — every visit that receptionist has
  // ever created, no date/shift restriction, only creator. Real
  // pagination (page/pageSize), not a fixed cap.
  listForCreator({ createdBy, page = 1, pageSize = 20 }) {
    return httpClient.get('/visits', {
      params: {
        created_by: createdBy,
        page,
        page_size: pageSize,
        sort_by: 'created_at',
        sort_order: 'desc',
      },
    });
  },

  // Every visit created on `date` (a "YYYY-MM-DD" string), hospital-
  // wide — a real server-side filter (GET /visits?date=), interpreted
  // as a UTC calendar day (see backend/app/modules/visits/repository.py's
  // `search` docstring — the same convention `GET /pharmacy/bills?date=`
  // already uses). Powers the Admin Overview day-view, replacing the
  // previous "fetch 100 recent + filter client-side" approach, which
  // could silently miss a day's own visits once hospital-wide volume
  // grew past 100 since that day. `pageSize` defaults generously since
  // this is meant to return a whole day's visits in one call, the same
  // shape `useMedicineBillsForDay` already has for medicine bills.
  listForDay({ date, pageSize = 100 }) {
    return httpClient.get('/visits', {
      params: {
        date,
        page: 1,
        page_size: pageSize,
        sort_by: 'created_at',
        sort_order: 'desc',
      },
    });
  },

  // All-time aggregate — the sum of outstanding balances across every
  // currently partially-paid visit, hospital-wide (2026-08-22
  // addition). Deliberately not day-scoped, unlike listForDay above:
  // an outstanding balance from a visit registered weeks ago must
  // still count today. Powers the Admin Overview's "Pending Revenue"
  // tile.
  getPendingRevenue() {
    return httpClient.get('/visits/pending-revenue-summary');
  },
};

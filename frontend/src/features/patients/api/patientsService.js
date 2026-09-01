import { httpClient } from '@/services/api/httpClient';

export const patientsService = {
  // The quick-lookup search backing every "find an existing patient"
  // picker in the app (Reception's Register Visit form, Pharmacy's
  // Link to Visit panel) — deliberately NOT the plain `GET /patients`
  // default (sort_by=created_at, sort_order=desc), which is a "recent
  // patients" list-view ordering, not a name lookup one. Left at that
  // default, a search term matching more than page_size patients
  // silently drops everyone except the most-recently-registered/active
  // matches — indistinguishable, in practice, from "only patients with
  // activity today show up", even though the backend query itself has
  // no date or created_by restriction at all (app/modules/patients/
  // repository.py's `search` is unconditionally unscoped). Sorting by
  // full_name instead mirrors app/modules/pharmacy/repository.py's
  // `search_active` (the medicine autocomplete), which orders
  // alphabetically for the exact same reason — a lookup search's
  // relevant order is the name being typed, never recency.
  search(query) {
    return httpClient.get('/patients', {
      params: {
        search: query,
        page: 1,
        page_size: 20,
        sort_by: 'full_name',
        sort_order: 'asc',
      },
    });
  },

  getById(patientId) {
    return httpClient.get(`/patients/${patientId}`);
  },

  // The Patient History search's own aggregated-timeline fetch, once a
  // patient has been picked — backed by `GET /patients/{id}/history`
  // (see backend/app/modules/patient_history/router.py). Every section
  // in the response may independently be `null` (the caller's role
  // doesn't hold that section's own other permission) or `[]` (it
  // does, this patient just has none) — see that endpoint's own
  // docstring; usePatientHistory (features/patients/hooks/
  // usePatientHistory.js) is what tells the two apart for rendering.
  getHistory(patientId) {
    return httpClient.get(`/patients/${patientId}/history`);
  },

  // Exact phone-number match — backs Reception's returning-patient
  // prompt (RegisterVisitForm.jsx, on the phone number field's blur).
  // Deliberately NOT `search` above (a fuzzy, multi-field ILIKE), see
  // backend/app/modules/patients/repository.py's
  // `list_by_phone_number` docstring. Always returns an array — zero,
  // one, or (family members sharing a household number) more than one
  // match, never a 404.
  findByPhoneNumber(phoneNumber) {
    return httpClient.get('/patients/lookup/by-phone', {
      params: { phone_number: phoneNumber },
    });
  },

  // The Admin Patient Directory's full, real server-side paginated/
  // sortable/searchable listing — deliberately distinct from `search`
  // above (a name-lookup autocomplete, always page_size=20/sorted by
  // name) and from any "fetch N recent + filter client-side" pattern:
  // every page/sort/search param is passed straight through to
  // `GET /patients`'s own real pagination (see backend/app/modules/
  // patients/router.py's `list_patients`), so this scales correctly
  // regardless of how many patients exist.
  list({ page = 1, pageSize = 20, search, sortBy = 'created_at', sortOrder = 'desc' } = {}) {
    return httpClient.get('/patients', {
      params: {
        page,
        page_size: pageSize,
        search: search || undefined,
        sort_by: sortBy,
        sort_order: sortOrder,
      },
    });
  },

  // The Patient History page's own always-visible, hospital-wide feed
  // — backed by `GET /patients/history/visits` (see backend/app/
  // modules/patient_history/router.py). Unified across Visit/
  // MedicineBill/LabBill (2026-09 redesign) — every real Token # in
  // the hospital is drawn from one shared sequence across all three,
  // so this returns them genuinely interleaved, not Visit rows alone.
  // Real server-side search (name/MR/phone/CNIC, resolved to patients
  // first, OR a direct Token # substring match against all three
  // tables' own token columns) + date range + pagination, mirroring
  // visitsService.list's own shape but never the client-filtered-over-
  // a-capped-fetch pattern MyRegistrations.jsx uses (that one is
  // acceptable only because it's scoped to one receptionist's own
  // bounded lifetime volume — this list is hospital-wide and
  // unbounded). No `search`/`startDate`/`endDate` means no filter at
  // all — every record, newest first — this endpoint's own default
  // state, deliberately never empty.
  listHistoryVisits({ page = 1, pageSize = 20, search, startDate, endDate } = {}) {
    return httpClient.get('/patients/history/visits', {
      params: {
        page,
        page_size: pageSize,
        search: search || undefined,
        start_date: startDate || undefined,
        end_date: endDate || undefined,
      },
    });
  },
};

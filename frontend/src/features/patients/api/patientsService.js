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
};

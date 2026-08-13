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
};

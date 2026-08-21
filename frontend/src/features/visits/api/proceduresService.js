import { httpClient } from '@/services/api/httpClient';

// The admin-managed procedure catalog (2026-08-21 addition) — mirrors
// features/pharmacy/api/pharmacyService.js's Medicine-catalog methods
// almost exactly (no category). Lives under /visits/procedures/* since
// the backend's own Procedure/VisitProcedureItem models live in the
// visits module (see backend/app/modules/visits/models.py's module
// docstring) — the catalog and its usage stay together, the same way
// Medicine and MedicineBill do inside the pharmacy module.
export const proceduresService = {
  // Active-only, case-insensitive partial-name match — feeds the
  // receptionist's procedure autocomplete at registration time
  // (SearchSelect). Unpaginated by design, mirrors
  // pharmacyService.searchMedicines's identical shape.
  searchProcedures(term) {
    return httpClient.get('/visits/procedures/search', { params: { search: term } });
  },

  // Admin management listing — every procedure, active and inactive
  // alike.
  listProcedures() {
    return httpClient.get('/visits/procedures', { params: { page: 1, page_size: 100 } });
  },

  createProcedure(payload) {
    return httpClient.post('/visits/procedures', payload);
  },

  updateProcedure(procedureId, payload) {
    return httpClient.patch(`/visits/procedures/${procedureId}`, payload);
  },

  // Unlike Medicine (activate/deactivate only), the procedure catalog
  // also supports a genuine delete — see backend/app/modules/visits/
  // models.py's `Procedure` docstring for why that's safe.
  deleteProcedure(procedureId) {
    return httpClient.delete(`/visits/procedures/${procedureId}`);
  },
};

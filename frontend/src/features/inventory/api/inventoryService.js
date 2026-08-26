import { httpClient } from '@/services/api/httpClient';

// Thin wrapper over backend/app/modules/inventory/router.py — see that
// file's own module docstring for the permission split
// (inventory:read/manage/record_usage/request_restock) each endpoint
// requires. Print endpoints are deliberately not here yet — see this
// module's own Step 6 (report-style PDF, a different mechanism than
// this codebase's existing thermal-receipt print pipeline).
export const inventoryService = {
  // Catalog — every item, active and inactive alike (mirrors
  // pharmacyService.listMedicines's identical "admin management
  // listing" shape).
  listItems({ category, lowStockOnly } = {}) {
    return httpClient.get('/inventory/items', {
      params: {
        page: 1,
        page_size: 100,
        category: category || undefined,
        low_stock_only: lowStockOnly || undefined,
      },
    });
  },

  createItem(payload) {
    return httpClient.post('/inventory/items', payload);
  },

  updateItem(itemId, payload) {
    return httpClient.patch(`/inventory/items/${itemId}`, payload);
  },

  receiveStock(itemId, payload) {
    return httpClient.post(`/inventory/items/${itemId}/receive`, payload);
  },

  transferStock(itemId, payload) {
    return httpClient.post(`/inventory/items/${itemId}/transfer`, payload);
  },

  listReceipts({ itemId, startDate, endDate, page = 1, pageSize = 50 } = {}) {
    return httpClient.get('/inventory/receipts', {
      params: {
        item_id: itemId || undefined,
        start_date: startDate || undefined,
        end_date: endDate || undefined,
        page,
        page_size: pageSize,
      },
    });
  },

  listTransfers({ itemId, startDate, endDate, page = 1, pageSize = 50 } = {}) {
    return httpClient.get('/inventory/transfers', {
      params: {
        item_id: itemId || undefined,
        start_date: startDate || undefined,
        end_date: endDate || undefined,
        page,
        page_size: pageSize,
      },
    });
  },

  listUsageEntries({ itemId, startDate, endDate, page = 1, pageSize = 50 } = {}) {
    return httpClient.get('/inventory/usage', {
      params: {
        item_id: itemId || undefined,
        start_date: startDate || undefined,
        end_date: endDate || undefined,
        page,
        page_size: pageSize,
      },
    });
  },

  listRequests({ status, page = 1, pageSize = 50 } = {}) {
    return httpClient.get('/inventory/requests', {
      params: { status: status || undefined, page, page_size: pageSize },
    });
  },

  fulfillRequest(requestId, payload) {
    return httpClient.post(`/inventory/requests/${requestId}/fulfill`, payload);
  },

  rejectRequest(requestId, payload) {
    return httpClient.post(`/inventory/requests/${requestId}/reject`, payload);
  },

  getStats() {
    return httpClient.get('/inventory/stats');
  },

  // Vitals' own two write actions (step 4) — record_usage/
  // request_restock, never inventory:manage's catalog/receipt/transfer/
  // fulfillment actions above.
  recordUsage(payload) {
    return httpClient.post('/inventory/usage', payload);
  },

  raiseRestockRequest(payload) {
    return httpClient.post('/inventory/requests', payload);
  },

  // The usage-entry screen's read-only "MR number + most recent
  // registered procedure" preview once a patient is picked — see
  // backend/app/modules/inventory/service.py's get_patient_context
  // docstring. `latest_visit: null` is a normal outcome (a genuine
  // ward/emergency patient with no OPD visit on file), never an error.
  getPatientContext(patientId) {
    return httpClient.get(`/inventory/patients/${patientId}/context`);
  },
};

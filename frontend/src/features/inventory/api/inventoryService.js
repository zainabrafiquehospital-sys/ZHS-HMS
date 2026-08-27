import { httpClient } from '@/services/api/httpClient';

// Thin wrapper over backend/app/modules/inventory/router.py — see that
// file's own module docstring for the permission split
// (inventory:read/manage/record_usage/request_restock) each endpoint
// requires.
export const inventoryService = {
  // Active-only, case-insensitive partial-name match — feeds the
  // item-picker SearchSelect on Receive Stock/Transfer to Emergency/
  // Record Usage/Raise Restock Request (2026-08-27 addition; the
  // backend endpoint already existed, this is the first frontend
  // caller). Same shape as pharmacyService.searchMedicines.
  searchItems(term) {
    return httpClient.get('/inventory/items/search', { params: { search: term } });
  },

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

  // Print (step 6) — report-style A4 documents, raw HTML (not the JSON
  // envelope) — see billingService.fetchInvoiceReceiptHtml's identical
  // docstring for why this is fetched rather than a plain <a href>.
  // Inventory Manager-only (inventory:manage) — prints whichever
  // History sub-tab and filter is currently active.
  fetchHistoryLogHtml({ logType, itemId, startDate, endDate }) {
    return httpClient.get('/inventory/history/print', {
      params: {
        log_type: logType,
        item_id: itemId || undefined,
        start_date: startDate || undefined,
        end_date: endDate || undefined,
      },
      responseType: 'text',
    });
  },

  // Vitals-only (inventory:record_usage) — always the calling user's
  // own day, same actor-scoping as `listUsageEntries`'s `mine` sibling.
  fetchDailyUsageSlipHtml(date) {
    return httpClient.get('/inventory/usage/mine/print', {
      params: { date },
      responseType: 'text',
    });
  },
};

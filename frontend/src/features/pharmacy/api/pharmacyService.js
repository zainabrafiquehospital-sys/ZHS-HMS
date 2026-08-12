import { httpClient } from '@/services/api/httpClient';

export const pharmacyService = {
  // Active-only, case-insensitive partial-name match — feeds the
  // receptionist's medicine autocomplete (SearchSelect). Unpaginated by
  // design, mirrors patientsService.search's shape.
  searchMedicines(term) {
    return httpClient.get('/pharmacy/medicines/search', { params: { search: term } });
  },

  // Admin management listing — every medicine, active and inactive alike.
  listMedicines() {
    return httpClient.get('/pharmacy/medicines', { params: { page: 1, page_size: 100 } });
  },

  createMedicine(payload) {
    return httpClient.post('/pharmacy/medicines', payload);
  },

  updateMedicine(medicineId, payload) {
    return httpClient.patch(`/pharmacy/medicines/${medicineId}`, payload);
  },

  createBill(payload) {
    return httpClient.post('/pharmacy/bills', payload);
  },

  recordPayment(billId, amount) {
    return httpClient.post(`/pharmacy/bills/${billId}/pay`, { amount });
  },

  listBillsForDay(date) {
    return httpClient.get('/pharmacy/bills', { params: { date } });
  },

  // Raw HTML document (not the JSON envelope) — see
  // billingService.fetchInvoiceReceiptHtml's identical docstring for why
  // this is fetched rather than a plain <a href>.
  fetchMedicineBillReceiptHtml(billId) {
    return httpClient.get(`/pharmacy/bills/${billId}/print`, { responseType: 'text' });
  },
};

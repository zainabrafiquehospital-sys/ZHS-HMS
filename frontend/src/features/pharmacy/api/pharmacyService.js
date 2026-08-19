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

  recordPayment(billId, amount, paymentMethod) {
    return httpClient.post(`/pharmacy/bills/${billId}/pay`, {
      amount,
      payment_method: paymentMethod,
    });
  },

  listBillsForDay(date) {
    return httpClient.get('/pharmacy/bills', { params: { date } });
  },

  // The calling receptionist's own medicine bills, newest first, real
  // server-side pagination — no date restriction. Hard-scoped
  // server-side to the caller (see app/modules/pharmacy/router.py's
  // `list_my_bills` docstring); there is no user id parameter here.
  listMyBills({ page, pageSize }) {
    return httpClient.get('/pharmacy/bills/mine', { params: { page, page_size: pageSize } });
  },

  // Raw HTML document (not the JSON envelope) — see
  // billingService.fetchInvoiceReceiptHtml's identical docstring for why
  // this is fetched rather than a plain <a href>.
  fetchMedicineBillReceiptHtml(billId) {
    return httpClient.get(`/pharmacy/bills/${billId}/print`, { responseType: 'text' });
  },
};

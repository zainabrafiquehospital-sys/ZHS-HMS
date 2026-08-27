import { httpClient } from '@/services/api/httpClient';

export const labService = {
  // Active-only, case-insensitive partial-name match — feeds the
  // receptionist's lab test autocomplete (SearchSelect). Unpaginated by
  // design, mirrors pharmacyService.searchMedicines's identical shape.
  searchTests(term) {
    return httpClient.get('/lab/tests/search', { params: { search: term } });
  },

  // Admin management listing — every test, active and inactive alike.
  listTests() {
    return httpClient.get('/lab/tests', { params: { page: 1, page_size: 100 } });
  },

  createTest(payload) {
    return httpClient.post('/lab/tests', payload);
  },

  updateTest(labTestId, payload) {
    return httpClient.patch(`/lab/tests/${labTestId}`, payload);
  },

  createBill(payload) {
    return httpClient.post('/lab/bills', payload);
  },

  recordPayment(billId, amount, paymentMethod) {
    return httpClient.post(`/lab/bills/${billId}/pay`, {
      amount,
      payment_method: paymentMethod,
    });
  },

  listBillsForDay(date) {
    return httpClient.get('/lab/bills', { params: { date } });
  },

  // Full bill detail (manual_patient_age/_phone, discount_reason — not
  // present on the day-list's lighter LabBillSummaryOut rows) — fetched
  // on demand to pre-fill the admin "Edit Bill" dialog.
  getBill(billId) {
    return httpClient.get(`/lab/bills/${billId}`);
  },

  // Admin-only (lab:update_bill / lab:delete_bill — never granted to
  // Receptionist, see backend/app/modules/lab/constants.py) — a
  // mistakenly-created bill's manual patient details/discount can be
  // corrected, or the bill removed entirely, the lab-bill sibling of
  // pharmacyService.updateBill/deleteBill. Only ever called from the
  // Admin Overview Lab Bills tab — never expose these from any
  // Receptionist-facing screen (LabBillingWorkspace.jsx).
  updateBill(billId, payload) {
    return httpClient.patch(`/lab/bills/${billId}`, payload);
  },

  deleteBill(billId) {
    return httpClient.delete(`/lab/bills/${billId}`);
  },

  // The calling receptionist's own lab bills, newest first, real
  // server-side pagination — no date restriction. Hard-scoped
  // server-side to the caller (see app/modules/lab/router.py's
  // `list_my_bills` docstring); there is no user id parameter here.
  listMyBills({ page, pageSize }) {
    return httpClient.get('/lab/bills/mine', { params: { page, page_size: pageSize } });
  },

  getBillStatsByCreator() {
    return httpClient.get('/lab/bills/stats/by-creator');
  },

  // Raw HTML document (not the JSON envelope) — see
  // pharmacyService.fetchMedicineBillReceiptHtml's identical docstring
  // for why this is fetched rather than a plain <a href>.
  fetchLabBillReceiptHtml(billId) {
    return httpClient.get(`/lab/bills/${billId}/print`, { responseType: 'text' });
  },
};

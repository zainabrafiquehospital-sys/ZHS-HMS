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

  // Full bill detail (manual_patient_age/_phone, discount_reason — not
  // present on the day-list's lighter MedicineBillSummaryOut rows) —
  // fetched on demand to pre-fill the admin "Edit Bill" dialog.
  getBill(billId) {
    return httpClient.get(`/pharmacy/bills/${billId}`);
  },

  // Admin-only (pharmacy:update_bill / pharmacy:delete_bill — never
  // granted to Receptionist, see backend/app/modules/pharmacy/
  // constants.py) — added 2026-08-20 so a mistakenly-created bill's
  // manual patient details/discount can be corrected, or the bill
  // removed entirely, the medicine-bill sibling of
  // receptionService.updateVisit/deleteVisit. Only ever called from the
  // Admin Overview Medicine Bills tab
  // (features/admin/components/AdminOverview.jsx) — never expose these
  // from any Receptionist-facing screen (MedicineBillingWorkspace.jsx).
  updateBill(billId, payload) {
    return httpClient.patch(`/pharmacy/bills/${billId}`, payload);
  },

  deleteBill(billId) {
    return httpClient.delete(`/pharmacy/bills/${billId}`);
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

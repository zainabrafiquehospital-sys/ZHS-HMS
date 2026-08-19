import { httpClient } from '@/services/api/httpClient';

export const billingService = {
  // Doctor-side (`billing:submit_charge`) — see backend/app/modules/
  // billing/router.py's `submit_pending_item`. Added in the 2026-08-19
  // audit fix pass: the endpoint and Reception's approve/reject screen
  // both already existed, but nothing in the frontend ever called this
  // one — a doctor had no way to actually request an additional charge.
  submitPendingItem({ visitId, description, amount }) {
    return httpClient.post('/billing/pending-items', {
      visit_id: visitId,
      description,
      amount,
    });
  },

  listPendingItems(visitId, status) {
    return httpClient.get(`/billing/visits/${visitId}/pending-items`, { params: { status } });
  },

  approvePendingItem(itemId) {
    return httpClient.post(`/billing/pending-items/${itemId}/approve`);
  },

  rejectPendingItem(itemId) {
    return httpClient.post(`/billing/pending-items/${itemId}/reject`);
  },

  generateInvoice(payload) {
    return httpClient.post('/billing/invoices', payload);
  },

  getInvoice(invoiceId) {
    return httpClient.get(`/billing/invoices/${invoiceId}`);
  },

  listInvoicesForVisit(visitId) {
    return httpClient.get(`/billing/visits/${visitId}/invoices`);
  },

  recordPayment(invoiceId, amount) {
    return httpClient.post(`/billing/invoices/${invoiceId}/pay`, { amount });
  },

  // The print endpoint returns a raw HTML document (Content-Type:
  // text/html), not the JSON envelope — it's meant to be rendered/printed
  // directly, not consumed as API data. Fetched here (rather than a plain
  // <a href>) because the access token lives in memory only (never a
  // cookie), so the request needs httpClient's Authorization header.
  fetchInvoiceReceiptHtml(invoiceId) {
    return httpClient.get(`/billing/invoices/${invoiceId}/print`, { responseType: 'text' });
  },
};

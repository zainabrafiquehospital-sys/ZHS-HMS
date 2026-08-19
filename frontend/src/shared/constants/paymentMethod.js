/**
 * The shared payment-method vocabulary (app/shared/payment_method.py's
 * PaymentMethod enum, confirmed against source) — recorded manually by
 * staff at the moment they confirm a payment was made (cash handed
 * over, or a bank transfer/JazzCash/EasyPaisa/card payment the patient
 * made separately). Not a payment gateway integration — nothing here
 * initiates or processes an actual transaction.
 *
 * Extracted here (mirrors visitStatus.js's identical shape) so every
 * payment-recording form — Billing's Generate Invoice/Record Payment,
 * Pharmacy's Finalize & Print, Admin Overview's "top up" dialog —
 * reuses the exact same option list/labels instead of four separate
 * copies drifting apart.
 */
export const PAYMENT_METHODS = ['cash', 'bank_transfer', 'jazzcash', 'easypaisa', 'card'];

export const PAYMENT_METHOD_LABELS = {
  cash: 'Cash',
  bank_transfer: 'Bank Transfer',
  jazzcash: 'JazzCash',
  easypaisa: 'EasyPaisa',
  card: 'Card',
};

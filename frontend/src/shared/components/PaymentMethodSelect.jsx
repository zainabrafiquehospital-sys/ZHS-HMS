'use client';

import { Label } from '@/shared/components/ui/Label';
import { Select } from '@/shared/components/ui/Select';
import { PAYMENT_METHODS, PAYMENT_METHOD_LABELS } from '@/shared/constants/paymentMethod';

/** The payment-method dropdown shared by every payment-recording form
 * (2026-08-19 addition) — Billing's Generate Invoice "Advance
 * Received" and its separate "Record Payment" top-up row, Pharmacy's
 * Finalize & Print "Advance Received", and Admin Overview's medicine-
 * bill "top up" dialog. See app/shared/payment_method.py's module
 * docstring for the shared backend vocabulary this mirrors — cash,
 * bank transfer, JazzCash, EasyPaisa, or card, manually confirmed by
 * staff, never a payment gateway integration.
 *
 * A plain `<select>` registered into the caller's own react-hook-form
 * instance via `registration` (whatever `register('field_name')`
 * returns) — this component owns no form state itself, matching every
 * other field in these forms. */
export function PaymentMethodSelect({ id, label = 'Payment Method', registration, error }) {
  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={id}>{label}</Label>
      <Select id={id} {...registration}>
        <option value="">Select method</option>
        {PAYMENT_METHODS.map((method) => (
          <option key={method} value={method}>
            {PAYMENT_METHOD_LABELS[method]}
          </option>
        ))}
      </Select>
      {error ? <p className="text-xs text-destructive">{error.message}</p> : null}
    </div>
  );
}

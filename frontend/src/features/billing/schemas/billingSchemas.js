import { z } from 'zod';

const positiveAmount = z
  .union([z.string(), z.number()])
  .transform((value) => Number(value))
  .refine((value) => Number.isFinite(value) && value > 0, {
    message: 'Amount must be greater than 0',
  });

// Blank/zero/untouched all mean the same thing for both of the
// optional fields below (discount, advance received): "not applicable
// right now" — never a hidden second meaning for the same blank
// value (e.g. blank never means "pay in full"; that's typed in
// explicitly, same number as the total).
const nonNegativeAmount = z
  .union([z.string(), z.number()])
  .transform((value) => (value === '' || value === null || value === undefined ? 0 : Number(value)))
  .refine((value) => Number.isFinite(value) && value >= 0, {
    message: 'Amount must be zero or greater',
  });

// A non-zero discount always requires a reason — same cross-field rule
// as the backend's BillingService.generate_invoice (schemas here only
// enforce per-field shape everywhere else; this is the one exception,
// because catching it client-side before the request is a materially
// better UX than a round-trip 422 for a receptionist mid-checkout).
// `initial_payment_amount` ("Advance Received") has no equivalent
// client-side ceiling check against the total — the frontend doesn't
// know the full subtotal (base amount + any approved doctor-requested
// charges) at the point of typing, only the backend does, so an
// over-the-limit advance is caught there (PAYMENT_EXCEEDS_BALANCE),
// same as an over-the-limit discount already is.
export const generateInvoiceSchema = z
  .object({
    base_description: z.string().min(1, 'Description is required').max(200),
    base_amount: positiveAmount,
    discount_amount: nonNegativeAmount,
    discount_reason: z.string().max(200).optional(),
    initial_payment_amount: nonNegativeAmount,
  })
  .refine((values) => values.discount_amount === 0 || Boolean(values.discount_reason?.trim()), {
    message: 'A reason is required when a discount is applied',
    path: ['discount_reason'],
  });

export const recordPaymentSchema = z.object({
  amount: positiveAmount,
});

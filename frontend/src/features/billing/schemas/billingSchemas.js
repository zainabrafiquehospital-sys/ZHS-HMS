import { z } from 'zod';

const positiveAmount = z
  .union([z.string(), z.number()])
  .transform((value) => Number(value))
  .refine((value) => Number.isFinite(value) && value > 0, {
    message: 'Amount must be greater than 0',
  });

const nonNegativeAmount = z
  .union([z.string(), z.number()])
  .transform((value) => (value === '' || value === null || value === undefined ? 0 : Number(value)))
  .refine((value) => Number.isFinite(value) && value >= 0, {
    message: 'Discount must be zero or greater',
  });

// A non-zero discount always requires a reason — same cross-field rule
// as the backend's BillingService.generate_invoice (schemas here only
// enforce per-field shape everywhere else; this is the one exception,
// because catching it client-side before the request is a materially
// better UX than a round-trip 422 for a receptionist mid-checkout).
export const generateInvoiceSchema = z
  .object({
    base_description: z.string().min(1, 'Description is required').max(200),
    base_amount: positiveAmount,
    discount_amount: nonNegativeAmount,
    discount_reason: z.string().max(200).optional(),
  })
  .refine((values) => values.discount_amount === 0 || Boolean(values.discount_reason?.trim()), {
    message: 'A reason is required when a discount is applied',
    path: ['discount_reason'],
  });

export const recordPaymentSchema = z.object({
  amount: positiveAmount,
});

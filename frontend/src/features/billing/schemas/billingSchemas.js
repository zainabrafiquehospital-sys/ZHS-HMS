import { z } from 'zod';

const positiveAmount = z
  .union([z.string(), z.number()])
  .transform((value) => Number(value))
  .refine((value) => Number.isFinite(value) && value > 0, {
    message: 'Amount must be greater than 0',
  });

export const generateInvoiceSchema = z.object({
  base_description: z.string().min(1, 'Description is required').max(200),
  base_amount: positiveAmount,
});

export const recordPaymentSchema = z.object({
  amount: positiveAmount,
});

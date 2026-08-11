import { z } from 'zod';

const positivePrice = z
  .union([z.string(), z.number()])
  .transform((value) => Number(value))
  .refine((value) => Number.isFinite(value) && value > 0, {
    message: 'Unit price must be greater than 0',
  });

export const MEDICINE_CATEGORIES = ['sachet', 'drops', 'tablet', 'injection'];

export const medicineFormSchema = z.object({
  name: z.string().min(1, 'Medicine name is required').max(150),
  category: z.enum(MEDICINE_CATEGORIES, { errorMap: () => ({ message: 'Select a category' }) }),
  unit_price: positivePrice,
});

export const billLineItemSchema = z.object({
  quantity: z
    .union([z.string(), z.number()])
    .transform((value) => Number(value))
    .refine((value) => Number.isInteger(value) && value > 0 && value <= 1000, {
      message: 'Quantity must be a whole number between 1 and 1000',
    }),
});

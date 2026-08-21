import { z } from 'zod';

// Mirrors features/pharmacy/schemas/pharmacySchemas.js's
// `medicineFormSchema` exactly, minus category — nothing about a
// procedure needs one.
const positivePrice = z
  .union([z.string(), z.number()])
  .transform((value) => Number(value))
  .refine((value) => Number.isFinite(value) && value > 0, {
    message: 'Price must be greater than 0',
  });

export const procedureFormSchema = z.object({
  name: z.string().min(1, 'Procedure name is required').max(200),
  price: positivePrice,
});

import { z } from 'zod';

// Admin-only "Edit Slip" form (2026-08-19 addition) — see
// receptionService.updateVisit's docstring. Every field optional
// (PATCH-style) and blank means "leave unchanged", not "clear this
// field" — mirrors backend/app/modules/reception/schemas.py's
// AdminUpdateVisitRequest exactly, both halves (Patient identity +
// Visit's own procedure/amount) in one flat form for the same reason
// that schema is flat: no field-name collision between the two.
const positiveAmount = z
  .union([z.string(), z.number()])
  .transform((value) => (value === '' || value === undefined ? undefined : Number(value)))
  .refine((value) => value === undefined || (Number.isFinite(value) && value > 0), {
    message: 'Enter an amount greater than 0',
  });

export const adminUpdateVisitSchema = z.object({
  full_name: z.string().min(1, 'Full name cannot be blank').max(150).optional().or(z.literal('')),
  guardian_name: z.string().max(150).optional().or(z.literal('')),
  gender: z.enum(['female', 'male', 'other']).optional().or(z.literal('')),
  age_years: z
    .union([z.string(), z.number()])
    .transform((value) => (value === '' || value === undefined ? undefined : Number(value)))
    .refine(
      (value) => value === undefined || (Number.isInteger(value) && value >= 0 && value <= 150),
      { message: 'Enter a valid age in years (0-150)' },
    ),
  phone_number: z.string().min(6, 'Enter a valid phone number').max(20).optional().or(z.literal('')),
  cnic: z.string().max(20).optional().or(z.literal('')),
  address: z.string().max(2000).optional().or(z.literal('')),
  procedure: z.string().min(1, 'Procedure cannot be blank').max(200).optional().or(z.literal('')),
  amount: positiveAmount,
});

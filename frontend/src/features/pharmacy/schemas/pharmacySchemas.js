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

// Same shape as billing/schemas/billingSchemas.js's recordPaymentSchema —
// a partial-payment amount, validated client-side before it ever reaches
// the server's own "exceeds remaining balance" check. Used by the
// Admin Overview "record an additional payment" action (a later
// top-up on an already-created bill), not by the finalize step itself.
// `payment_method` (2026-08-19 addition) is required, same as Billing's
// identical field.
export const recordMedicineBillPaymentSchema = z.object({
  amount: z
    .union([z.string(), z.number()])
    .transform((value) => Number(value))
    .refine((value) => Number.isFinite(value) && value > 0, {
      message: 'Amount must be greater than 0',
    }),
  payment_method: z.string().min(1, 'Select a payment method'),
});

// Blank/zero/untouched all mean the same thing for every optional
// money field below (advance received, discount): "not applicable
// right now" — same convention billing/schemas/billingSchemas.js's
// identical `nonNegativeAmount` documents (duplicated locally rather
// than imported cross-feature, matching this codebase's per-feature
// schema-file independence).
const nonNegativeAmount = z
  .union([z.string(), z.number()])
  .transform((value) => (value === '' || value === null || value === undefined ? 0 : Number(value)))
  .refine((value) => Number.isFinite(value) && value >= 0, {
    message: 'Amount must be zero or greater',
  });

// The Finalize & Print form's optional fields: "Advance Received"
// (unchanged, its own payment method added 2026-08-19 — required
// whenever initial_payment_amount > 0, mirroring the backend's
// MedicineBillPaymentMethodRequiredError) and an optional flat
// discount. Unlike billing/schemas/billingSchemas.js's
// generateInvoiceSchema, there is deliberately no cross-field "reason
// required when discount_amount > 0" refine here: a medicine-bill
// discount's reason is always optional, a product decision distinct
// from Invoice's own discount (see app/modules/pharmacy/service.py's
// create_bill docstring). Whether the discount fields are shown/
// applied at all is owned by the "Apply Discount" checkbox in
// MedicineBillingWorkspace.jsx, not by this schema — discount_amount
// stays 0 whenever that checkbox is off, mirroring
// RegisterVisitForm.jsx's vitalsRequired toggle shape.
export const finalizeBillSchema = z
  .object({
    initial_payment_amount: nonNegativeAmount,
    initial_payment_method: z.string().optional(),
    discount_amount: nonNegativeAmount,
    discount_reason: z.string().max(200).optional(),
  })
  .refine(
    (values) => values.initial_payment_amount === 0 || Boolean(values.initial_payment_method),
    {
      message: 'Select a payment method to record this payment',
      path: ['initial_payment_method'],
    },
  );

// Manual Entry mode's three fields (VisitLinkPanel) — same per-field
// shape as app/modules/patients/schemas.py's CreatePatientRequest
// (full_name/age_years/phone_number), validated client-side before
// the request ever reaches the server's own all-or-nothing check.
// Unlike discount/advance-received, these are never individually
// optional once Manual Entry mode is active — all three or none.
export const manualPatientSchema = z.object({
  manual_patient_name: z.string().min(1, 'Name is required').max(150),
  manual_patient_age: z
    .union([z.string(), z.number()])
    .transform((value) => Number(value))
    .refine((value) => Number.isInteger(value) && value >= 0 && value <= 150, {
      message: 'Age must be a whole number between 0 and 150',
    }),
  manual_patient_phone: z.string().min(6, 'Contact number is required').max(20),
});

// Admin-only "Edit Bill" form (2026-08-20 addition) — see
// pharmacyService.updateBill's docstring. Every field optional
// (PATCH-style) and blank means "leave unchanged", not "clear this
// field" — mirrors features/reception/schemas/adminUpdateVisitSchema.js
// exactly. `discount_amount` is the one field where 0 is itself a
// meaningful, explicit value ("no discount"), not "leave unchanged" —
// AdminMedicineBillDialog only includes it in the submitted payload
// when the admin actually edited it (see that component's own
// docstring), the same distinction the backend's `exclude_unset`
// PATCH semantics already draw.
export const adminUpdateMedicineBillSchema = z.object({
  manual_patient_name: z.string().min(1, 'Name cannot be blank').max(150).optional().or(z.literal('')),
  manual_patient_age: z
    .union([z.string(), z.number()])
    .transform((value) => (value === '' || value === undefined ? undefined : Number(value)))
    .refine(
      (value) => value === undefined || (Number.isInteger(value) && value >= 0 && value <= 150),
      { message: 'Enter a valid age in years (0-150)' },
    ),
  manual_patient_phone: z
    .string()
    .min(6, 'Enter a valid contact number')
    .max(20)
    .optional()
    .or(z.literal('')),
  discount_amount: z
    .union([z.string(), z.number()])
    .transform((value) => (value === '' || value === undefined ? undefined : Number(value)))
    .refine((value) => value === undefined || (Number.isFinite(value) && value >= 0), {
      message: 'Discount must be zero or greater',
    }),
  discount_reason: z.string().max(200).optional().or(z.literal('')),
});

import { z } from 'zod';

const positivePrice = z
  .union([z.string(), z.number()])
  .transform((value) => Number(value))
  .refine((value) => Number.isFinite(value) && value > 0, {
    message: 'Price must be greater than 0',
  });

export const LAB_TEST_CATEGORIES = ['pathology', 'radiology'];

export const labTestFormSchema = z.object({
  name: z.string().min(1, 'Test name is required').max(150),
  category: z.enum(LAB_TEST_CATEGORIES, { errorMap: () => ({ message: 'Select a category' }) }),
  price: positivePrice,
});

// No per-line quantity schema here (unlike pharmacySchemas.js's
// billLineItemSchema) — confirmed design: a lab test has no quantity
// at all (see backend/app/modules/lab/models.py's LabBillItem
// docstring), so adding a line only ever needs a selected test, never
// a numeric field to validate.

// Same shape as billing/schemas/billingSchemas.js's recordPaymentSchema
// — a partial-payment amount, validated client-side before it ever
// reaches the server's own "exceeds remaining balance" check. Used by
// the Admin Overview "record an additional payment" action, not by the
// finalize step itself.
export const recordLabBillPaymentSchema = z.object({
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
// right now" — same convention pharmacySchemas.js's identical
// nonNegativeAmount documents (duplicated locally rather than imported
// cross-feature, matching this codebase's per-feature schema-file
// independence).
const nonNegativeAmount = z
  .union([z.string(), z.number()])
  .transform((value) => (value === '' || value === null || value === undefined ? 0 : Number(value)))
  .refine((value) => Number.isFinite(value) && value >= 0, {
    message: 'Amount must be zero or greater',
  });

// The Finalize & Print form's optional fields — identical shape to
// pharmacySchemas.js's finalizeBillSchema: "Advance Received" (its own
// payment method required whenever initial_payment_amount > 0,
// mirroring the backend's LabBillPaymentMethodRequiredError) and an
// optional flat discount, always with an optional reason (same
// deliberate product decision as Pharmacy's own discount — see
// backend/app/modules/lab/service.py's create_bill docstring). Whether
// the discount fields are shown/applied at all is owned by the "Apply
// Discount" checkbox in LabBillingWorkspace.jsx, not by this schema.
export const finalizeLabBillSchema = z
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

// Manual Entry mode's three fields (LabPatientLinkPanel) — same
// per-field shape as pharmacySchemas.js's identical manualPatientSchema
// (duplicated locally rather than imported cross-feature, matching
// this codebase's own per-feature schema-file independence).
export const labManualPatientSchema = z.object({
  manual_patient_name: z.string().min(1, 'Name is required').max(150),
  manual_patient_age: z
    .union([z.string(), z.number()])
    .transform((value) => Number(value))
    .refine((value) => Number.isInteger(value) && value >= 0 && value <= 150, {
      message: 'Age must be a whole number between 0 and 150',
    }),
  manual_patient_phone: z.string().min(6, 'Contact number is required').max(20),
});

// Admin-only "Edit Bill" form — see labService.updateBill's docstring.
// Every field optional (PATCH-style) and blank means "leave
// unchanged" — mirrors pharmacySchemas.js's identical
// adminUpdateMedicineBillSchema exactly.
export const adminUpdateLabBillSchema = z.object({
  manual_patient_name: z
    .string()
    .min(1, 'Name cannot be blank')
    .max(150)
    .optional()
    .or(z.literal('')),
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

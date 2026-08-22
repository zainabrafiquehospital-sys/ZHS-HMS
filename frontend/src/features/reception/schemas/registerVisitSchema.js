import { z } from 'zod';

// Only full_name/age_years/phone_number are compulsory (Phase 6
// fast-registration §2) — guardian_name/gender/cnic/address are never
// removed from the system, just optional at registration time.
const newPatientSchema = z.object({
  full_name: z.string().min(1, 'Full name is required').max(150),
  guardian_name: z.string().max(150).optional().or(z.literal('')),
  gender: z.enum(['female', 'male', 'other']).optional().or(z.literal('')),
  age_years: z
    .union([z.string(), z.number()])
    .transform((value) => (value === '' || value === undefined ? undefined : Number(value)))
    .refine((value) => value !== undefined && Number.isInteger(value) && value >= 0 && value <= 150, {
      message: 'Enter a valid age in years (0-150)',
    }),
  phone_number: z.string().min(6, 'Enter a valid phone number').max(20),
  cnic: z.string().max(20).optional().or(z.literal('')),
  address: z.string().max(2000).optional().or(z.literal('')),
});

// Blank/zero/untouched all mean "no discount" — same convention as
// features/pharmacy/schemas/pharmacySchemas.js's identical
// nonNegativeAmount (duplicated locally rather than imported cross-
// feature, matching this codebase's per-feature schema-file
// independence).
const nonNegativeAmount = z
  .union([z.string(), z.number()])
  .transform((value) => (value === '' || value === null || value === undefined ? 0 : Number(value)))
  .refine((value) => Number.isFinite(value) && value >= 0, {
    message: 'Amount must be zero or greater',
  });

// No doctor-selection field at all — doctor assignment is always
// automatic (Phase 6 fast-registration §4), never a receptionist choice.
// discountAmount/discountReason (2026-08-19 addition) — an optional
// flat discount off the procedures' combined total, applied at
// registration time; reason is always optional here, same product
// decision as the medicine-bill discount (no cross-field "reason
// required" refine, unlike Billing's own generateInvoiceSchema).
// Whether these fields are shown/applied at all is owned by the
// "Apply Discount" checkbox in RegisterVisitForm.jsx, not by this
// schema.
//
// `procedure`/`amount` (2026-08-21 removal) are gone from this schema
// entirely — replaced by the itemized `procedureItems` list, which is
// plain local state in RegisterVisitForm.jsx (not a registered form
// field here), the same way `applyDiscount`/the discount fields'
// visibility is already handled ad hoc rather than through this
// schema. See ProcedureItemsEditor.jsx's own docstring.
//
// `paymentMethod`/`advanceAmount` (2026-08-22 addition) — a real
// payment (full or partial) is always collected at registration; see
// RegisterVisitForm.jsx's own "Partial Payment" checkbox docstring.
// `paymentMethod` is always required (a payment method is meaningless
// without an amount, and an amount is always being sent). `advanceAmount`
// is only meaningful — and only validated here — while the "Partial
// Payment" checkbox is ticked; when it isn't, the full net total is
// sent instead (computed in the component, not this schema), so this
// field is optional at the schema level and its "required, > 0" rule
// is enforced by the component itself only while the checkbox is on
// (see handlePartialPaymentToggle).
export const registerVisitSchema = z
  .object({
    patientMode: z.enum(['new', 'existing']),
    existingPatientId: z.string().optional(),
    existingPatientLabel: z.string().optional(),
    newPatient: newPatientSchema.optional(),
    vitalsRequired: z.boolean().default(false),
    discountAmount: nonNegativeAmount,
    discountReason: z.string().max(200).optional(),
    paymentMethod: z.string().min(1, 'Select a payment method'),
    advanceAmount: z.union([z.string(), z.number()]).optional(),
  })
  .refine((data) => data.patientMode !== 'existing' || Boolean(data.existingPatientId), {
    message: 'Search and select an existing patient',
    path: ['existingPatientId'],
  })
  .refine((data) => data.patientMode !== 'new' || Boolean(data.newPatient), {
    message: 'Fill in the new patient details',
    path: ['newPatient'],
  });

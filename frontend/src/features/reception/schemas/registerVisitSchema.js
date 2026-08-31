import { z } from 'zod';

// Only full_name/age_years/phone_number are compulsory (Phase 6
// fast-registration §2) — guardian_name/gender/cnic/address are never
// removed from the system, just optional at registration time.
//
// Every field here is schema-level optional/lenient — the real
// "these three are required" rule lives in the top-level `superRefine`
// below instead, gated on `patientMode === 'new'`. This shape alone
// (unconditionally requiring full_name/age_years/phone_number) used to
// sit directly on `newPatient` — harmless while every trigger that
// switches into Existing Patient mode also happened to have those
// fields either genuinely filled in or never touched — until
// RegisterVisitForm.jsx's own name-based suggestion feature started
// switching modes the instant a name alone is typed, well before
// age/phone exist. RHF's `defaultValues` means `newPatient` is never
// actually `undefined` (only `.optional()` at the wrapper level, which
// this schema still had), so that leftover partial object kept
// getting fully validated regardless of `patientMode` — silently
// failing `handleSubmit` with no visible error, since the New Patient
// fields that would render it aren't even on screen in Existing
// Patient mode. See handleUseExistingPatient's own docstring for the
// matching fix on the component side (resetting `newPatient` back to
// blank on every switch) — this schema change is what actually makes
// that blank state valid to submit.
const newPatientSchema = z.object({
  full_name: z.string().max(150).optional().or(z.literal('')),
  guardian_name: z.string().max(150).optional().or(z.literal('')),
  gender: z.enum(['female', 'male', 'other']).optional().or(z.literal('')),
  age_years: z
    .union([z.string(), z.number()])
    .optional()
    .transform((value) => (value === '' || value === undefined ? undefined : Number(value))),
  phone_number: z.string().max(20).optional().or(z.literal('')),
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

// doctorUserId (2026-08-24 addition) — optional; blank (the default and
// still the common case) preserves auto-assignment exactly as before
// (Phase 6 fast-registration §4). An explicit selection, from
// RegisterVisitForm.jsx's doctor dropdown, bypasses it. No format/
// presence validation here beyond "a string" — an invalid or stale id
// is rejected server-side (DoctorNotAvailableForAssignmentError), the
// same "let the backend be the source of truth" convention
// existingPatientId's own id already follows.
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
    doctorUserId: z.string().optional(),
    discountAmount: nonNegativeAmount,
    discountReason: z.string().max(200).optional(),
    paymentMethod: z.string().min(1, 'Select a payment method'),
    advanceAmount: z.union([z.string(), z.number()]).optional(),
  })
  // Replaces the two simpler `.refine` calls this used to be (one per
  // mode) — needed once `newPatientSchema` itself stopped enforcing
  // full_name/age_years/phone_number unconditionally (see that
  // schema's own docstring): those three rules now live here instead,
  // gated on `patientMode === 'new'` specifically, each with its own
  // field-level `path` so the existing `errors.newPatient?.full_name`/
  // `.age_years`/`.phone_number` display logic in RegisterVisitForm.jsx
  // keeps working unchanged.
  .superRefine((data, ctx) => {
    if (data.patientMode === 'existing') {
      if (!data.existingPatientId) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          message: 'Search and select an existing patient',
          path: ['existingPatientId'],
        });
      }
      return;
    }

    const newPatient = data.newPatient;
    if (!newPatient?.full_name || newPatient.full_name.trim().length === 0) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: 'Full name is required',
        path: ['newPatient', 'full_name'],
      });
    }
    const ageYears = newPatient?.age_years;
    if (ageYears === undefined || !Number.isInteger(ageYears) || ageYears < 0 || ageYears > 150) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: 'Enter a valid age in years (0-150)',
        path: ['newPatient', 'age_years'],
      });
    }
    if (!newPatient?.phone_number || newPatient.phone_number.length < 6) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: 'Enter a valid phone number',
        path: ['newPatient', 'phone_number'],
      });
    }
  });

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

const positiveAmount = z
  .union([z.string(), z.number()])
  .transform((value) => (value === '' || value === undefined ? undefined : Number(value)))
  .refine((value) => value !== undefined && Number.isFinite(value) && value > 0, {
    message: 'Enter an amount greater than 0',
  });

// No doctor-selection field at all — doctor assignment is always
// automatic (Phase 6 fast-registration §4), never a receptionist choice.
export const registerVisitSchema = z
  .object({
    patientMode: z.enum(['new', 'existing']),
    existingPatientId: z.string().optional(),
    existingPatientLabel: z.string().optional(),
    newPatient: newPatientSchema.optional(),
    procedure: z.string().min(1, 'Procedure is required').max(200),
    amount: positiveAmount,
    vitalsRequired: z.boolean().default(false),
  })
  .refine((data) => data.patientMode !== 'existing' || Boolean(data.existingPatientId), {
    message: 'Search and select an existing patient',
    path: ['existingPatientId'],
  })
  .refine((data) => data.patientMode !== 'new' || Boolean(data.newPatient), {
    message: 'Fill in the new patient details',
    path: ['newPatient'],
  });

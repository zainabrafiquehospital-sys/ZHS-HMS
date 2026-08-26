import { z } from 'zod';

// Mirrors backend/app/modules/auth/constants.py's PASSWORD_MIN_LENGTH (12)
// — kept in sync manually since the frontend has no way to read backend
// constants at build time; the backend re-validates regardless (this is
// a UX nicety, never the actual enforcement boundary).
const PASSWORD_MIN_LENGTH = 12;

export const signupSchema = z
  .object({
    fullName: z.string().min(1, 'Full name is required').max(150),
    email: z.string().min(1, 'Email is required').email('Enter a valid email address'),
    phoneNumber: z.string().min(7, 'Enter a valid phone number').max(20),
    password: z
      .string()
      .min(PASSWORD_MIN_LENGTH, `Password must be at least ${PASSWORD_MIN_LENGTH} characters`),
    // Optional at the schema level — required for every role except the
    // shift-less ones, enforced below via superRefine rather than a
    // plain z.enum() the way it used to be. Mirrors backend/app/modules/
    // auth/signup_schemas.py's SignupRequest.
    // _shift_required_unless_shiftless_role exactly: those roles have no
    // shift concept in this system (see that validator's own docstring),
    // so this field simply doesn't apply to them rather than accepting
    // a meaningless value.
    shift: z.enum(['morning', 'night']).optional().or(z.literal('')),
    // Mirrors backend/app/modules/auth/signup_schemas.py's SignupRole
    // exactly — keep in sync if a fifth self-service role is ever added.
    role: z.enum(['receptionist', 'vitals', 'doctor', 'inventory_manager'], {
      errorMap: () => ({ message: 'Select which role you are signing up for' }),
    }),
  })
  .superRefine((data, ctx) => {
    // Mirrors backend's `_SHIFTLESS_SIGNUP_ROLES` exactly.
    const isShiftless = data.role === 'doctor' || data.role === 'inventory_manager';
    if (!isShiftless && !data.shift) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: 'Select a shift',
        path: ['shift'],
      });
    }
  });

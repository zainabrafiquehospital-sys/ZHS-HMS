import { z } from 'zod';

// Mirrors backend/app/modules/auth/constants.py's PASSWORD_MIN_LENGTH (12)
// — kept in sync manually since the frontend has no way to read backend
// constants at build time; the backend re-validates regardless (this is
// a UX nicety, never the actual enforcement boundary).
const PASSWORD_MIN_LENGTH = 12;

export const signupSchema = z.object({
  fullName: z.string().min(1, 'Full name is required').max(150),
  email: z.string().min(1, 'Email is required').email('Enter a valid email address'),
  phoneNumber: z.string().min(7, 'Enter a valid phone number').max(20),
  password: z
    .string()
    .min(PASSWORD_MIN_LENGTH, `Password must be at least ${PASSWORD_MIN_LENGTH} characters`),
  shift: z.enum(['morning', 'night'], { errorMap: () => ({ message: 'Select a shift' }) }),
  // Mirrors backend/app/modules/auth/signup_schemas.py's SignupRole
  // exactly — keep in sync if a third self-service role is ever added.
  role: z.enum(['receptionist', 'vitals'], {
    errorMap: () => ({ message: 'Select which role you are signing up for' }),
  }),
});

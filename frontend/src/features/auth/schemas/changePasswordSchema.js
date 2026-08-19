import { z } from 'zod';

// Mirrors backend/app/modules/auth/constants.py's PASSWORD_MIN_LENGTH (12)
// — same manually-kept-in-sync convention as signupSchema.js/otpSchema.js's
// resetPasswordSchema; the backend re-validates the full policy regardless,
// this is only a UX nicety.
const PASSWORD_MIN_LENGTH = 12;

export const changePasswordSchema = z
  .object({
    currentPassword: z.string().min(1, 'Enter your current password'),
    newPassword: z
      .string()
      .min(PASSWORD_MIN_LENGTH, `Password must be at least ${PASSWORD_MIN_LENGTH} characters`),
    confirmPassword: z.string().min(1, 'Confirm your new password'),
  })
  .refine((data) => data.newPassword === data.confirmPassword, {
    message: 'Passwords do not match',
    path: ['confirmPassword'],
  })
  .refine((data) => data.newPassword !== data.currentPassword, {
    message: 'Your new password must be different from your current one',
    path: ['newPassword'],
  });

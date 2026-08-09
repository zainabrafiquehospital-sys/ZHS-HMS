import { z } from 'zod';

export const otpSchema = z.object({
  code: z
    .string()
    .length(6, 'Enter the 6-digit code')
    .regex(/^\d{6}$/, 'Code must be 6 digits'),
});

export const resetPasswordSchema = z
  .object({
    newPassword: z.string().min(12, 'Password must be at least 12 characters'),
    confirmPassword: z.string().min(1, 'Confirm your new password'),
  })
  .refine((data) => data.newPassword === data.confirmPassword, {
    message: 'Passwords do not match',
    path: ['confirmPassword'],
  });

'use client';

import { useMutation } from '@tanstack/react-query';
import { authService } from '@/features/auth/api/authService';

/**
 * Separate from useSignup.js's mutation hooks on purpose — those are all
 * public/unauthenticated (see that file's own docstring); this one
 * requires an already-authenticated user (the Authorization header
 * httpClient.js attaches automatically). Backs ChangePasswordForm.jsx,
 * used both for the ordinary "Settings" self-service case and the
 * forced must_change_password flow AuthGuard traps a user in.
 */
export function useChangePassword() {
  return useMutation({
    mutationFn: (payload) => authService.changePassword(payload),
  });
}

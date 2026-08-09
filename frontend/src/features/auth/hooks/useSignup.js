'use client';

import { useMutation } from '@tanstack/react-query';
import { authService } from '@/features/auth/api/authService';

// All of these are public, unauthenticated mutations — no query
// invalidation needed (nothing about the signed-in session's cache is
// affected until an actual login happens, handled by useAuth's own
// login()).

export function useSignup() {
  return useMutation({
    mutationFn: (payload) => authService.signup(payload),
  });
}

export function useVerifyEmail() {
  return useMutation({
    mutationFn: (payload) => authService.verifyEmail(payload),
  });
}

export function useResendSignupOtp() {
  return useMutation({
    mutationFn: (payload) => authService.resendSignupOtp(payload),
  });
}

export function useForgotPassword() {
  return useMutation({
    mutationFn: (payload) => authService.forgotPassword(payload),
  });
}

export function useVerifyResetOtp() {
  return useMutation({
    mutationFn: (payload) => authService.verifyResetOtp(payload),
  });
}

export function useResetPassword() {
  return useMutation({
    mutationFn: (payload) => authService.resetPassword(payload),
  });
}

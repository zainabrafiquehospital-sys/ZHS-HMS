'use client';

import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { useRouter } from 'next/navigation';
import { z } from 'zod';
import { KeyRound } from 'lucide-react';
import { otpSchema, resetPasswordSchema } from '@/features/auth/schemas/otpSchema';
import {
  useForgotPassword,
  useVerifyResetOtp,
  useResetPassword,
} from '@/features/auth/hooks/useSignup';
import { OtpCodeInput } from '@/features/auth/components/OtpCodeInput';
import { ROUTES } from '@/core/constants/routes';
import { Button } from '@/shared/components/ui/Button';
import { Input } from '@/shared/components/ui/Input';
import { Label } from '@/shared/components/ui/Label';
import { Card, CardContent, CardHeader, CardTitle } from '@/shared/components/ui/Card';

const emailSchema = z.object({
  email: z.string().min(1, 'Email is required').email('Enter a valid email address'),
});

// Every account gets the exact same response from the backend
// regardless of whether the email matched one (see AuthService.
// request_password_reset's docstring) — this step always advances,
// never shows "no such account".
const GENERIC_STEP1_MESSAGE =
  "If an account exists for this email, we've sent a 6-digit reset code.";

/**
 * Three-step forgot-password flow: email -> OTP (reuses OtpCodeInput,
 * same as SignupOtpForm) -> new password. A single component with
 * internal step state, not three routes — the code entered in step 2
 * is needed again by step 3's own API call (see AuthService.
 * verify_reset_otp's docstring for why the OTP isn't consumed until
 * the final reset), so keeping all three steps in one component's
 * state is simpler than threading it through query params across
 * page navigations.
 */
export function ForgotPasswordForm() {
  const router = useRouter();
  const [step, setStep] = useState('email');
  const [email, setEmail] = useState('');
  const [code, setCode] = useState('');
  const [stepError, setStepError] = useState(null);

  const forgotPassword = useForgotPassword();
  const verifyResetOtp = useVerifyResetOtp();
  const resetPassword = useResetPassword();

  const emailForm = useForm({
    resolver: zodResolver(emailSchema),
    defaultValues: { email: '' },
  });
  const otpForm = useForm({
    resolver: zodResolver(otpSchema),
    defaultValues: { code: '' },
  });
  const passwordForm = useForm({
    resolver: zodResolver(resetPasswordSchema),
    defaultValues: { newPassword: '', confirmPassword: '' },
  });

  async function onSubmitEmail(values) {
    setStepError(null);
    try {
      await forgotPassword.mutateAsync({ email: values.email });
      setEmail(values.email);
      setStep('otp');
    } catch (error) {
      // Still generic — a validation/rate-limit error is the only thing
      // that can surface here, never "no such account".
      setStepError(error.message || 'Unable to process this request right now.');
    }
  }

  async function onSubmitOtp(values) {
    setStepError(null);
    try {
      await verifyResetOtp.mutateAsync({ email, code: values.code });
      setCode(values.code);
      setStep('password');
    } catch (error) {
      setStepError(error.message || 'Unable to verify this code. Please try again.');
    }
  }

  async function handleResend() {
    setStepError(null);
    try {
      await forgotPassword.mutateAsync({ email });
    } catch (error) {
      setStepError(error.message || 'Unable to resend a code right now.');
    }
  }

  async function onSubmitPassword(values) {
    setStepError(null);
    try {
      await resetPassword.mutateAsync({ email, code, newPassword: values.newPassword });
      router.push(`${ROUTES.LOGIN}?reset=success`);
    } catch (error) {
      setStepError(error.message || 'Unable to reset your password. Please try again.');
    }
  }

  return (
    <Card className="w-full max-w-sm">
      <CardHeader className="flex-row items-center gap-2">
        <KeyRound className="h-4 w-4 text-muted-foreground" />
        <CardTitle>
          {step === 'email'
            ? 'Forgot Password'
            : step === 'otp'
              ? 'Enter Reset Code'
              : 'Set New Password'}
        </CardTitle>
      </CardHeader>
      <CardContent>
        {step === 'email' ? (
          <form
            onSubmit={emailForm.handleSubmit(onSubmitEmail)}
            className="flex flex-col gap-4"
          >
            <p className="text-sm text-muted-foreground">
              Enter your account email and we&apos;ll send you a code to reset your password.
            </p>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="email">Email</Label>
              <Input
                id="email"
                type="email"
                autoFocus
                autoComplete="email"
                {...emailForm.register('email')}
              />
              {emailForm.formState.errors.email ? (
                <p className="text-xs text-destructive">
                  {emailForm.formState.errors.email.message}
                </p>
              ) : null}
            </div>
            {stepError ? (
              <p className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
                {stepError}
              </p>
            ) : null}
            <Button type="submit" disabled={emailForm.formState.isSubmitting} className="w-full">
              {emailForm.formState.isSubmitting ? 'Sending…' : 'Send Reset Code'}
            </Button>
          </form>
        ) : null}

        {step === 'otp' ? (
          <form onSubmit={otpForm.handleSubmit(onSubmitOtp)} className="flex flex-col gap-4">
            <p className="rounded-md bg-muted/50 px-3 py-2 text-xs text-muted-foreground">
              {GENERIC_STEP1_MESSAGE}
            </p>
            <OtpCodeInput
              control={otpForm.control}
              error={otpForm.formState.errors.code}
              email={email}
              onResend={handleResend}
              isResending={forgotPassword.isPending}
            />
            {stepError ? (
              <p className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
                {stepError}
              </p>
            ) : null}
            <Button type="submit" disabled={otpForm.formState.isSubmitting} className="w-full">
              {otpForm.formState.isSubmitting ? 'Verifying…' : 'Verify Code'}
            </Button>
          </form>
        ) : null}

        {step === 'password' ? (
          <form
            onSubmit={passwordForm.handleSubmit(onSubmitPassword)}
            className="flex flex-col gap-4"
          >
            <p className="text-sm text-muted-foreground">Choose a new password for your account.</p>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="newPassword">New Password</Label>
              <Input
                id="newPassword"
                type="password"
                autoComplete="new-password"
                placeholder="At least 12 characters"
                {...passwordForm.register('newPassword')}
              />
              {passwordForm.formState.errors.newPassword ? (
                <p className="text-xs text-destructive">
                  {passwordForm.formState.errors.newPassword.message}
                </p>
              ) : null}
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="confirmPassword">Confirm Password</Label>
              <Input
                id="confirmPassword"
                type="password"
                autoComplete="new-password"
                {...passwordForm.register('confirmPassword')}
              />
              {passwordForm.formState.errors.confirmPassword ? (
                <p className="text-xs text-destructive">
                  {passwordForm.formState.errors.confirmPassword.message}
                </p>
              ) : null}
            </div>
            {stepError ? (
              <p className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
                {stepError}
              </p>
            ) : null}
            <Button type="submit" disabled={passwordForm.formState.isSubmitting} className="w-full">
              {passwordForm.formState.isSubmitting ? 'Saving…' : 'Reset Password'}
            </Button>
          </form>
        ) : null}
      </CardContent>
    </Card>
  );
}

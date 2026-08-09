'use client';

import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { useRouter, useSearchParams } from 'next/navigation';
import Link from 'next/link';
import { CheckCircle2 } from 'lucide-react';
import { useAuth } from '@/features/auth/hooks/useAuth';
import { loginSchema } from '@/features/auth/schemas/loginSchema';
import { resolveLandingRoute } from '@/core/constants/access';
import { ROUTES } from '@/core/constants/routes';
import { Button } from '@/shared/components/ui/Button';
import { Input } from '@/shared/components/ui/Input';
import { Label } from '@/shared/components/ui/Label';

export function LoginForm() {
  const { login } = useAuth();
  const router = useRouter();
  const searchParams = useSearchParams();
  const resetSucceeded = searchParams.get('reset') === 'success';
  const [submitError, setSubmitError] = useState(null);
  // Set only for ACCOUNT_PENDING_EMAIL_VERIFICATION — lets the error
  // banner below offer a direct way back into the OTP step rather than
  // leaving the receptionist stuck re-typing a password that was never
  // the problem (see AuthService.login's status-check ordering: this
  // error means email verification was never finished, not "wrong
  // password").
  const [pendingVerificationEmail, setPendingVerificationEmail] = useState(null);
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm({
    resolver: zodResolver(loginSchema),
    defaultValues: { email: '', password: '', rememberMe: false },
  });

  async function onSubmit(values) {
    setSubmitError(null);
    setPendingVerificationEmail(null);
    try {
      const loggedInUser = await login(values);
      // Every user logs in from this one page and is routed straight to
      // their own module — never a generic landing page they then have
      // to navigate away from (Phase 6 fast-registration §1).
      router.push(resolveLandingRoute(loggedInUser.permissions ?? []));
    } catch (error) {
      setSubmitError(error.message || 'Unable to sign in. Check your credentials and try again.');
      if (error.code === 'ACCOUNT_PENDING_EMAIL_VERIFICATION') {
        setPendingVerificationEmail(values.email);
      }
    }
  }

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="flex w-full max-w-sm flex-col gap-4">
      {resetSucceeded ? (
        <div className="flex items-center gap-2 rounded-md bg-emerald-600/10 px-3 py-2 text-sm text-emerald-700">
          <CheckCircle2 className="h-4 w-4 shrink-0" />
          Password reset. Please sign in with your new password.
        </div>
      ) : null}

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="email">Email</Label>
        <Input
          id="email"
          type="email"
          autoComplete="username"
          placeholder="you@hospital.com"
          {...register('email')}
        />
        {errors.email ? <p className="text-xs text-destructive">{errors.email.message}</p> : null}
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="password">Password</Label>
        <Input
          id="password"
          type="password"
          autoComplete="current-password"
          placeholder="••••••••••••"
          {...register('password')}
        />
        {errors.password ? (
          <p className="text-xs text-destructive">{errors.password.message}</p>
        ) : null}
      </div>

      <div className="flex items-center justify-between">
        <label className="flex items-center gap-2 text-sm text-muted-foreground">
          <input
            type="checkbox"
            className="h-4 w-4 rounded border-input"
            {...register('rememberMe')}
          />
          Remember me on this device
        </label>
        <Link
          href={ROUTES.FORGOT_PASSWORD}
          className="text-sm text-muted-foreground underline-offset-4 hover:underline"
        >
          Forgot password?
        </Link>
      </div>

      {submitError ? (
        <div className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
          <p>{submitError}</p>
          {pendingVerificationEmail ? (
            <Link
              href={`${ROUTES.VERIFY_EMAIL}?email=${encodeURIComponent(pendingVerificationEmail)}`}
              className="mt-1 inline-block font-medium underline-offset-4 hover:underline"
            >
              Continue email verification
            </Link>
          ) : null}
        </div>
      ) : null}

      <Button type="submit" disabled={isSubmitting} className="w-full">
        {isSubmitting ? 'Signing in…' : 'Sign in'}
      </Button>

      <p className="text-center text-sm text-muted-foreground">
        New staff member?{' '}
        <Link
          href={ROUTES.SIGNUP}
          className="font-medium text-foreground underline-offset-4 hover:underline"
        >
          Create an account
        </Link>
      </p>
    </form>
  );
}

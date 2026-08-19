'use client';

import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { useRouter } from 'next/navigation';
import { ShieldAlert } from 'lucide-react';
import { changePasswordSchema } from '@/features/auth/schemas/changePasswordSchema';
import { useChangePassword } from '@/features/auth/hooks/useChangePassword';
import { useAuth } from '@/features/auth/hooks/useAuth';
import { ROUTES } from '@/core/constants/routes';
import { Button } from '@/shared/components/ui/Button';
import { Input } from '@/shared/components/ui/Input';
import { Label } from '@/shared/components/ui/Label';
import { Card, CardContent, CardHeader, CardTitle } from '@/shared/components/ui/Card';

/**
 * The forced side of `must_change_password` enforcement (2026-08-19
 * audit fix pass) — AuthGuard.jsx routes here, and traps the user here,
 * whenever their account has this flag set (an admin-issued temporary
 * password, or an admin-forced change). Every permission-gated endpoint
 * already rejects them with `PASSWORD_CHANGE_REQUIRED` regardless (see
 * backend/app/modules/auth/dependencies.py's `require_permission`) —
 * this screen is purely what lets them clear it.
 *
 * `AuthService.change_password` revokes every refresh token/session for
 * the account on success, including the one that made this call (see
 * that method's own docstring) — so success here is a forced logout by
 * design, not a bug to route around: this immediately clears the local
 * session and sends the user to /login to sign back in with their new
 * password, reusing the exact same `?reset=success` banner
 * ForgotPasswordForm's reset flow already shows on LoginForm.
 */
export function ChangePasswordForm() {
  const router = useRouter();
  const { clearSession } = useAuth();
  const changePassword = useChangePassword();
  const [submitError, setSubmitError] = useState(null);

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm({
    resolver: zodResolver(changePasswordSchema),
    defaultValues: { currentPassword: '', newPassword: '', confirmPassword: '' },
  });

  async function onSubmit(values) {
    setSubmitError(null);
    try {
      await changePassword.mutateAsync({
        currentPassword: values.currentPassword,
        newPassword: values.newPassword,
      });
      clearSession();
      router.push(`${ROUTES.LOGIN}?reset=success`);
    } catch (error) {
      setSubmitError(error.message || 'Unable to change your password. Please try again.');
    }
  }

  return (
    <Card className="w-full max-w-sm">
      <CardHeader className="flex-row items-center gap-2">
        <ShieldAlert className="h-4 w-4 text-muted-foreground" />
        <CardTitle>Change Your Password</CardTitle>
      </CardHeader>
      <CardContent>
        <p className="mb-4 text-sm text-muted-foreground">
          For your account&apos;s security, you must set a new password before continuing.
        </p>
        <form onSubmit={handleSubmit(onSubmit)} className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="currentPassword">Current Password</Label>
            <Input
              id="currentPassword"
              type="password"
              autoFocus
              autoComplete="current-password"
              {...register('currentPassword')}
            />
            {errors.currentPassword ? (
              <p className="text-xs text-destructive">{errors.currentPassword.message}</p>
            ) : null}
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="newPassword">New Password</Label>
            <Input
              id="newPassword"
              type="password"
              autoComplete="new-password"
              placeholder="At least 12 characters"
              {...register('newPassword')}
            />
            {errors.newPassword ? (
              <p className="text-xs text-destructive">{errors.newPassword.message}</p>
            ) : null}
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="confirmPassword">Confirm New Password</Label>
            <Input
              id="confirmPassword"
              type="password"
              autoComplete="new-password"
              {...register('confirmPassword')}
            />
            {errors.confirmPassword ? (
              <p className="text-xs text-destructive">{errors.confirmPassword.message}</p>
            ) : null}
          </div>
          {submitError ? (
            <div className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
              {submitError}
            </div>
          ) : null}
          <Button type="submit" disabled={isSubmitting} className="w-full">
            {isSubmitting ? 'Saving…' : 'Change Password'}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}

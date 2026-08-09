'use client';

import { useEffect, useState } from 'react';
import { Controller } from 'react-hook-form';
import { Input } from '@/shared/components/ui/Input';
import { Label } from '@/shared/components/ui/Label';
import { Button } from '@/shared/components/ui/Button';

/**
 * The 6-digit-code entry step shared by every OTP-driven flow this app
 * has (signup email verification, forgot-password) — see
 * SignupOtpForm.jsx and ForgotPasswordForm.jsx, both of which render
 * this with their own surrounding submit/resend logic rather than this
 * component owning any flow-specific API call itself. Kept generic on
 * purpose: a plain digit input (no per-box-splitting library), matching
 * this app's established "no new dependency for a solved-by-native-HTML
 * problem" convention (see SearchSelect.jsx).
 */
export function OtpCodeInput({
  control,
  error,
  email,
  onResend,
  isResending,
  resendCooldownSeconds = 60,
}) {
  const [cooldown, setCooldown] = useState(0);

  useEffect(() => {
    if (cooldown <= 0) return undefined;
    const timer = setInterval(() => setCooldown((seconds) => Math.max(0, seconds - 1)), 1000);
    return () => clearInterval(timer);
  }, [cooldown]);

  async function handleResend() {
    // `onResend` (SignupOtpForm / ForgotPasswordForm) already catches its
    // own request failure to show a toast/inline error and never rethrows
    // — so `await` alone can't tell success from failure here. Without
    // checking the returned boolean, a failed resend would still start
    // this 60s cooldown as if a new code had actually been sent, locking
    // the user out of the resend button for a code that never arrived.
    const didSend = await onResend();
    if (didSend) setCooldown(resendCooldownSeconds);
  }

  return (
    <div className="flex flex-col gap-4">
      <p className="text-sm text-muted-foreground">
        We&apos;ve sent a 6-digit code to <span className="font-medium text-foreground">{email}</span>.
        Enter it below — it expires in 10 minutes.
      </p>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="code">Verification Code</Label>
        <Controller
          control={control}
          name="code"
          render={({ field }) => (
            <Input
              id="code"
              inputMode="numeric"
              autoComplete="one-time-code"
              maxLength={6}
              placeholder="000000"
              className="text-center text-lg tracking-[0.5em]"
              value={field.value}
              onChange={(event) => field.onChange(event.target.value.replace(/\D/g, '').slice(0, 6))}
            />
          )}
        />
        {error ? <p className="text-xs text-destructive">{error.message}</p> : null}
      </div>
      <Button
        type="button"
        variant="ghost"
        size="sm"
        disabled={cooldown > 0 || isResending}
        onClick={handleResend}
        className="self-start px-0"
      >
        {cooldown > 0
          ? `Resend code in ${cooldown}s`
          : isResending
            ? 'Sending…'
            : "Didn't get a code? Resend"}
      </Button>
    </div>
  );
}

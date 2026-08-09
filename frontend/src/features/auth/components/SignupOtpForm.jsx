'use client';

import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { useRouter } from 'next/navigation';
import { CheckCircle2, MailCheck } from 'lucide-react';
import { otpSchema } from '@/features/auth/schemas/otpSchema';
import { useVerifyEmail, useResendSignupOtp } from '@/features/auth/hooks/useSignup';
import { OtpCodeInput } from '@/features/auth/components/OtpCodeInput';
import { ROUTES } from '@/core/constants/routes';
import { Button } from '@/shared/components/ui/Button';
import { Card, CardContent, CardHeader, CardTitle } from '@/shared/components/ui/Card';
import { useToast } from '@/shared/components/toast/ToastProvider';

export function SignupOtpForm({ email }) {
  const router = useRouter();
  const { toast } = useToast();
  const [verified, setVerified] = useState(false);
  const verifyEmail = useVerifyEmail();
  const resendOtp = useResendSignupOtp();
  const {
    control,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm({
    resolver: zodResolver(otpSchema),
    defaultValues: { code: '' },
  });

  async function onSubmit(values) {
    try {
      await verifyEmail.mutateAsync({ email, code: values.code });
      // The "Email Verified" card below is the persistent confirmation
      // of this state change — no success toast on top of it, that
      // would just be noise duplicating what the whole screen already
      // says.
      setVerified(true);
    } catch (error) {
      toast.error({
        title: 'Unable to verify this code',
        description: error.message,
        onRetry: () => onSubmit(values),
      });
    }
  }

  async function handleResend() {
    try {
      await resendOtp.mutateAsync({ email });
      toast.success({ title: 'Code resent', description: `Sent a new code to ${email}.` });
      // Reported to OtpCodeInput so it only starts its resend cooldown
      // once a code has actually gone out — see OtpCodeInput.jsx.
      return true;
    } catch (error) {
      toast.error({
        title: 'Unable to resend a code',
        description: error.message,
        onRetry: handleResend,
      });
      return false;
    }
  }

  if (verified) {
    return (
      <Card className="w-full max-w-sm border-emerald-600/40 bg-emerald-600/5">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-emerald-700">
            <CheckCircle2 className="h-4 w-4" />
            Email Verified
          </CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-4 text-sm">
          <p className="text-foreground">
            Your account is now awaiting admin approval. You&apos;ll receive an email once
            it&apos;s approved — you can close this page.
          </p>
          <Button type="button" className="w-full" onClick={() => router.push(ROUTES.LOGIN)}>
            Back to Sign In
          </Button>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="w-full max-w-sm">
      <CardHeader className="flex-row items-center gap-2">
        <MailCheck className="h-4 w-4 text-muted-foreground" />
        <CardTitle>Verify Your Email</CardTitle>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit(onSubmit)} className="flex flex-col gap-4">
          <OtpCodeInput
            control={control}
            error={errors.code}
            email={email}
            onResend={handleResend}
            isResending={resendOtp.isPending}
          />
          <Button type="submit" disabled={isSubmitting} className="w-full">
            {isSubmitting ? 'Verifying…' : 'Verify Email'}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}

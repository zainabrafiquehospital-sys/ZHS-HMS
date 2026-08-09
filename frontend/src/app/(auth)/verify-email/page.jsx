'use client';

import { useSearchParams } from 'next/navigation';
import Link from 'next/link';
import { SignupOtpForm } from '@/features/auth/components/SignupOtpForm';
import { ROUTES } from '@/core/constants/routes';

export default function VerifyEmailPage() {
  const searchParams = useSearchParams();
  const email = searchParams.get('email');

  if (!email) {
    return (
      <div className="flex w-full max-w-sm flex-col items-center gap-4 text-center">
        <p className="text-sm text-muted-foreground">
          No email address to verify. Start from the sign up page.
        </p>
        <Link
          href={ROUTES.SIGNUP}
          className="text-sm font-medium text-foreground underline-offset-4 hover:underline"
        >
          Go to Sign Up
        </Link>
      </div>
    );
  }

  return <SignupOtpForm email={email} />;
}

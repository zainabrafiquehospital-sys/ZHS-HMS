import Link from 'next/link';
import { SignupForm } from '@/features/auth/components/SignupForm';
import { ROUTES } from '@/core/constants/routes';

export const metadata = {
  title: 'Sign up — Zainab Rafique Hospital',
};

export default function SignupPage() {
  return (
    <div className="flex w-full max-w-sm flex-col items-center gap-6">
      <div className="flex flex-col items-center gap-1 text-center">
        <h1 className="text-lg font-semibold text-foreground">Staff Sign Up</h1>
        <p className="text-sm text-muted-foreground">Create your Reception or Vitals account</p>
      </div>
      <SignupForm />
      <p className="text-sm text-muted-foreground">
        Already have an account?{' '}
        <Link href={ROUTES.LOGIN} className="font-medium text-foreground underline-offset-4 hover:underline">
          Sign in
        </Link>
      </p>
    </div>
  );
}

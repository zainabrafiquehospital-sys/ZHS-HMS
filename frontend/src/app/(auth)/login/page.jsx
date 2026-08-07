import { LoginForm } from '@/features/auth/components/LoginForm';

export const metadata = {
  title: 'Sign in — Gynecology HMS',
};

export default function LoginPage() {
  return (
    <div className="flex w-full max-w-sm flex-col items-center gap-6">
      <div className="flex flex-col items-center gap-1 text-center">
        <h1 className="text-lg font-semibold text-foreground">Gynecology HMS</h1>
        <p className="text-sm text-muted-foreground">Sign in to continue</p>
      </div>
      <LoginForm />
    </div>
  );
}

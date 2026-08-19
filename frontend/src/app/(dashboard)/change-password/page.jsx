import { ChangePasswordForm } from '@/features/auth/components/ChangePasswordForm';

export const metadata = {
  title: 'Change Password — Zainab Rafique Hospital',
};

export default function ChangePasswordPage() {
  return (
    <div className="flex flex-1 items-center justify-center py-10">
      <ChangePasswordForm />
    </div>
  );
}

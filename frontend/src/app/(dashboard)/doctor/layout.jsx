import { RequirePermission } from '@/features/auth/components/RequirePermission';

export default function DoctorLayout({ children }) {
  return <RequirePermission permission="consultation:start">{children}</RequirePermission>;
}

import { RequirePermission } from '@/features/auth/components/RequirePermission';

export default function AdminPatientsLayout({ children }) {
  return <RequirePermission permission="patients:read">{children}</RequirePermission>;
}

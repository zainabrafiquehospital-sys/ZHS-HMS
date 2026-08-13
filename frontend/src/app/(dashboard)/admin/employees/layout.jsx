import { RequirePermission } from '@/features/auth/components/RequirePermission';

export default function AdminEmployeesLayout({ children }) {
  return <RequirePermission permission="users:read">{children}</RequirePermission>;
}

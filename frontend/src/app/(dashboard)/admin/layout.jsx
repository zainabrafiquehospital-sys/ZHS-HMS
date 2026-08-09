import { RequirePermission } from '@/features/auth/components/RequirePermission';

export default function AdminLayout({ children }) {
  return <RequirePermission permission="users:read">{children}</RequirePermission>;
}

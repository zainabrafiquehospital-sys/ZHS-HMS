import { RequirePermission } from '@/features/auth/components/RequirePermission';

export default function AdminProceduresLayout({ children }) {
  return <RequirePermission permission="procedures:manage">{children}</RequirePermission>;
}

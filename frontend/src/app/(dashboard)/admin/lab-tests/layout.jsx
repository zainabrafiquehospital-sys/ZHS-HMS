import { RequirePermission } from '@/features/auth/components/RequirePermission';

export default function AdminLabTestsLayout({ children }) {
  return <RequirePermission permission="lab:manage">{children}</RequirePermission>;
}

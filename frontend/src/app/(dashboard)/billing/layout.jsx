import { RequirePermission } from '@/features/auth/components/RequirePermission';

export default function BillingLayout({ children }) {
  return <RequirePermission permission="billing:read">{children}</RequirePermission>;
}

import { RequirePermission } from '@/features/auth/components/RequirePermission';

export default function VitalsLayout({ children }) {
  return <RequirePermission permission="vitals:read">{children}</RequirePermission>;
}

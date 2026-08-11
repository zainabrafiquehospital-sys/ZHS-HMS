import { RequirePermission } from '@/features/auth/components/RequirePermission';

export default function PharmacyLayout({ children }) {
  return <RequirePermission permission="pharmacy:bill">{children}</RequirePermission>;
}

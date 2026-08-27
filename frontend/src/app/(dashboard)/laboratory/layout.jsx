import { RequirePermission } from '@/features/auth/components/RequirePermission';

export default function LaboratoryLayout({ children }) {
  return <RequirePermission permission="lab:bill">{children}</RequirePermission>;
}

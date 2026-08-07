import { RequirePermission } from '@/features/auth/components/RequirePermission';

export default function ReceptionLayout({ children }) {
  return <RequirePermission permission="reception:register_visit">{children}</RequirePermission>;
}

import { RequirePermission } from '@/features/auth/components/RequirePermission';

export default function AdminMedicineStockLayout({ children }) {
  return <RequirePermission permission="pharmacy:manage">{children}</RequirePermission>;
}

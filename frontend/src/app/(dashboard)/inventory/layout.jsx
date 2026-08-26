import { RequirePermission } from '@/features/auth/components/RequirePermission';

export default function InventoryLayout({ children }) {
  return <RequirePermission permission="inventory:manage">{children}</RequirePermission>;
}

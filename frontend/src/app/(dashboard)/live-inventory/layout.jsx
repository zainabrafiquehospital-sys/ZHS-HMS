import { RequirePermission } from '@/features/auth/components/RequirePermission';

// A top-level route, gated on `inventory:read` — the one inventory
// permission Inventory Manager, Admin, and Vitals all three hold
// (confirmed against the actual grant migrations), unlike the stricter
// `inventory:manage` gating /inventory itself (unreachable for Vitals).
// Same "own top-level route, single shared permission gate" shape as
// /daily-usage's own layout.jsx. The page underneath
// (LiveInventoryDashboard.jsx) is a read-only, auto-refreshing glance
// at Main + Emergency stock levels and the day's usage — it links into
// /daily-usage for the full searchable/printable per-submission view
// rather than duplicating it.
export default function LiveInventoryLayout({ children }) {
  return <RequirePermission permission="inventory:read">{children}</RequirePermission>;
}

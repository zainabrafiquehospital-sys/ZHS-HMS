import { RequirePermission } from '@/features/auth/components/RequirePermission';

// A top-level route, gated on `inventory:read` — the one inventory
// permission Inventory Manager, Admin, and Vitals all three hold
// (confirmed against the actual grant migrations), unlike the stricter
// `inventory:manage` gating /inventory itself (unreachable for Vitals).
// Same "own top-level route, single shared permission gate" shape as
// /patient-history's own layout.jsx — see that file's docstring for the
// precedent this mirrors. The page underneath (DailyInventoryUsage.jsx)
// shows every actor's Ward/Emergency Inventory usage hospital-wide for
// one selected day, not just the viewing actor's own — deliberately
// different from Vitals' own "My Inventory Usage" list
// (features/vitals/components/MyInventoryUsage.jsx), which stays
// scoped to the calling actor.
export default function DailyInventoryUsageLayout({ children }) {
  return <RequirePermission permission="inventory:read">{children}</RequirePermission>;
}

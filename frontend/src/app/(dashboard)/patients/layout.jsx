import { RequirePermission } from '@/features/auth/components/RequirePermission';

// A top-level route, NOT nested under /admin — that parent route's own
// layout.jsx gates on `users:read` (Admin-only), which would block any
// Receptionist from ever reaching this page even though they hold
// `patients:read` themselves (Next.js layouts nest: a child route is
// wrapped by every ancestor layout, so the stricter parent gate would
// run first and redirect away before this page's own gate is ever
// evaluated — this is exactly why Patient Directory previously
// redirected Receptionist accounts back to /reception). Both Admin (via
// the full permission catalog) and Receptionist (granted `patients:read`
// directly — see backend/scripts/seed_launch_bootstrap.py's
// RECEPTIONIST_PERMISSION_CODES) already hold this permission, so this
// one gate is sufficient — no separate per-role route needed.
export default function PatientsLayout({ children }) {
  return <RequirePermission permission="patients:read">{children}</RequirePermission>;
}

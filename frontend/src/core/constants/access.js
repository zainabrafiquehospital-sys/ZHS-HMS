/**
 * Single source of truth for "which permission unlocks which route" —
 * drives the sidebar (hide items entirely, not just disable them), the
 * per-route guard (block direct navigation to a URL the user has no
 * business on), and the post-login landing route. Mirrors the backend's
 * own permission codes (see each module's own `constants.py` on the
 * backend) — the frontend never invents its own notion of "role", it only
 * ever checks the same permission codes the backend already enforces
 * (see useAuth.js's `hasPermission`: this is a UI-hiding convenience,
 * never the actual authorization boundary).
 */
import { ROUTES } from '@/core/constants/routes';

export const MODULE_ACCESS = [
  // Checked first: an account holding users:read (i.e. an actual admin —
  // see features/admin/hooks/useAdminOverview.js's docstring on why that
  // permission specifically gates this route) lands on the admin overview
  // rather than an OPD module it may also incidentally hold permissions
  // for, since the full permission catalog grants admin literally every
  // code that exists.
  { route: ROUTES.ADMIN, permission: 'users:read', label: 'Admin' },
  { route: ROUTES.RECEPTION, permission: 'reception:register_visit', label: 'Reception' },
  { route: ROUTES.DOCTOR_QUEUE, permission: 'consultation:start', label: 'Doctor Queue' },
  { route: ROUTES.VITALS, permission: 'vitals:read', label: 'Vitals' },
  { route: ROUTES.BILLING, permission: 'billing:read', label: 'Billing' },
];

/** Does `permissions` (the user's effective permission-code list)
 * satisfy the requirement for `route`? Routes with no entry here (e.g.
 * the dashboard root) are open to every authenticated user — each
 * dashboard card independently hides itself per-permission already
 * (see features/dashboard/hooks/useDashboard.js). */
export function canAccessRoute(permissions, route) {
  const entry = MODULE_ACCESS.find((item) => item.route === route);
  if (!entry) return true;
  return permissions.includes(entry.permission);
}

/** Where a user lands immediately after login — first matching module
 * in this priority order, or the dashboard if none match (e.g. an
 * admin-only account with no single OPD-module permission). */
export function resolveLandingRoute(permissions) {
  const match = MODULE_ACCESS.find((item) => permissions.includes(item.permission));
  return match ? match.route : ROUTES.DASHBOARD;
}

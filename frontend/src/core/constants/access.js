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
  // vitals:record, not vitals:read — see app/(dashboard)/vitals/
  // layout.jsx's identical reasoning (2026-08-30 root-cause fix): this
  // entry drives both the post-login landing route and
  // RequirePermission's own redirect-on-denial target, so it must agree
  // with that layout's actual guard, or a Doctor denied elsewhere could
  // be redirected straight into the same unusable Vitals module.
  { route: ROUTES.VITALS, permission: 'vitals:record', label: 'Vitals' },
  { route: ROUTES.BILLING, permission: 'billing:read', label: 'Billing' },
  { route: ROUTES.PHARMACY, permission: 'pharmacy:bill', label: 'Pharmacy' },
  { route: ROUTES.LABORATORY, permission: 'lab:bill', label: 'Laboratory' },
  // Inventory Manager holds inventory:manage but not any of the other
  // module permissions above — without this entry, that role would land
  // on the dashboard root and see "No dashboards are available for your
  // role" (DashboardOverview.jsx only checks reception/doctor/vitals
  // permissions), the same landing-route gap every other module's own
  // entry here already closes.
  { route: ROUTES.INVENTORY, permission: 'inventory:manage', label: 'Inventory' },
  // ADMIN_MEDICINES/ADMIN_PROCEDURES are not listed here — both are
  // Admin sub-screens, not landing modules in their own right;
  // ROUTES.ADMIN (above) already covers "where does an admin-only
  // account land" for anyone holding pharmacy:manage/procedures:manage
  // (each only ever granted alongside the full admin catalog — see
  // scripts/seed_launch_bootstrap.py).
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

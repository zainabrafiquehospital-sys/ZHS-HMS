/**
 * Route-group level path constants only. Feature-specific sub-routes
 * (e.g. a specific visit's detail page) are defined and owned inside
 * each feature module, not here.
 */
export const ROUTE_GROUPS = {
  DASHBOARD: '/',
};

export const ROUTES = {
  LOGIN: '/login',
  SIGNUP: '/signup',
  VERIFY_EMAIL: '/verify-email',
  FORGOT_PASSWORD: '/forgot-password',
  // Authenticated (lives under the (dashboard) route group, behind
  // AuthGuard), unlike the unauthenticated /forgot-password reset flow
  // — this is where AuthGuard traps a user whose account has
  // `must_change_password` set (e.g. straight after an admin-issued
  // temporary password) until they've actually changed it. See
  // AuthGuard.jsx and ChangePasswordForm.jsx.
  CHANGE_PASSWORD: '/change-password',
  DASHBOARD: '/',
  RECEPTION: '/reception',
  DOCTOR_QUEUE: '/doctor',
  VITALS: '/vitals',
  BILLING: '/billing',
  ADMIN: '/admin',
  PHARMACY: '/pharmacy',
  LABORATORY: '/laboratory',
  INVENTORY: '/inventory',
  ADMIN_MEDICINES: '/admin/medicines',
  ADMIN_LAB_TESTS: '/admin/lab-tests',
  ADMIN_PROCEDURES: '/admin/procedures',
  // A top-level route, not nested under /admin — shared by both Admin
  // and Receptionist (both hold `patients:read`). See
  // app/(dashboard)/patients/layout.jsx's own docstring for why it
  // deliberately isn't under the Admin-only /admin/* tree.
  PATIENTS: '/patients',
  ADMIN_EMPLOYEES: '/admin/employees',
};

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
  DASHBOARD: '/',
  RECEPTION: '/reception',
  DOCTOR_QUEUE: '/doctor',
  VITALS: '/vitals',
  BILLING: '/billing',
  ADMIN: '/admin',
  PHARMACY: '/pharmacy',
  ADMIN_MEDICINES: '/admin/medicines',
  // A top-level route, not nested under /admin — shared by both Admin
  // and Receptionist (both hold `patients:read`). See
  // app/(dashboard)/patients/layout.jsx's own docstring for why it
  // deliberately isn't under the Admin-only /admin/* tree.
  PATIENTS: '/patients',
  ADMIN_EMPLOYEES: '/admin/employees',
};

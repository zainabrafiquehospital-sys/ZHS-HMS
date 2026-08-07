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
  DASHBOARD: '/',
  RECEPTION: '/reception',
  DOCTOR_QUEUE: '/doctor',
  VITALS: '/vitals',
  BILLING: '/billing',
};

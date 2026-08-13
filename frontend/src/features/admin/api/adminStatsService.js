import { httpClient } from '@/services/api/httpClient';

/**
 * Read-only per-user activity aggregates for the Admin "Employee
 * Accounts & Stats" page — one call per module's own new `/stats/by-*`
 * endpoint (visits/pharmacy/consultation/vitals), each already a single
 * `GROUP BY` query server-side covering every user in one round trip,
 * never one request per user. A new file rather than additions to
 * `adminUsersService.js`: these calls cross into other modules' own
 * routers (visits/pharmacy/consultations/vitals), not `/users`, so
 * grouping them under the "admin user management" service would misname
 * what they actually are.
 */
export const adminStatsService = {
  // { user_id, count } per receptionist who has registered a Visit.
  getVisitStatsByCreator() {
    return httpClient.get('/visits/stats/by-creator');
  },

  // { user_id, count, revenue } per receptionist who has created a
  // medicine bill — `revenue` is the sum of total_amount billed, not
  // amount actually collected (see backend/app/modules/pharmacy/
  // repository.py's `count_and_revenue_by_creator` docstring).
  getMedicineBillStatsByCreator() {
    return httpClient.get('/pharmacy/bills/stats/by-creator');
  },

  // { user_id, count } per doctor who has completed a Consultation.
  getConsultationStatsByDoctor() {
    return httpClient.get('/consultations/stats/by-doctor');
  },

  // { user_id, count } per user who has recorded a Vitals reading.
  getVitalsStatsByCreator() {
    return httpClient.get('/vitals/stats/by-creator');
  },
};

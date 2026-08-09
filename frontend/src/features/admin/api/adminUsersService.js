import { httpClient } from '@/services/api/httpClient';

/**
 * Admin-only user-management calls the Admin overview needs — currently
 * just the signup-approval slice (list pending, approve, reject). Not a
 * general user-management service: this app has no user CRUD UI yet
 * (see the codebase audit's "Gaps & Risks" finding), so this file only
 * wraps the `GET /users` filter and the two approve/reject-signup
 * endpoints those two features actually use, not the full `/users` API
 * surface.
 */
export const adminUsersService = {
  listPendingApprovals() {
    return httpClient.get('/users', {
      params: { status: 'pending_admin_approval', page: 1, page_size: 50, sort_order: 'asc' },
    });
  },

  approveSignup(userId) {
    return httpClient.post(`/users/${userId}/approve-signup`);
  },

  rejectSignup(userId) {
    return httpClient.post(`/users/${userId}/reject-signup`);
  },

  // Used by the Admin overview's "Booked By" column — joins a Visit's
  // created_by (see visits/schemas.py's VisitOut) to the user's name.
  getById(userId) {
    return httpClient.get(`/users/${userId}`);
  },
};

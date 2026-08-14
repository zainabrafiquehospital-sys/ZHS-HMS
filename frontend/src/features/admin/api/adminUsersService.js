import { httpClient } from '@/services/api/httpClient';

/**
 * Admin-only user-management calls the Admin overview needs — the
 * signup-approval slice (list pending, approve, reject) plus the
 * Employee Accounts & Stats page's full, unfiltered-by-status listing
 * (`list`, added alongside these without touching them). Still not a
 * general user-management service: this app has no user CRUD UI yet
 * (see the codebase audit's "Gaps & Risks" finding), so this file wraps
 * `GET /users` (in its two different call shapes) and the two approve/
 * reject-signup endpoints, not the full `/users` API surface.
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

  // The Employee Accounts & Stats page's full listing — every user
  // account regardless of status (unlike `listPendingApprovals`'s fixed
  // `pending_admin_approval` filter), real server-side pagination/sort/
  // search passed straight through to `GET /users` (see backend/app/
  // modules/auth/user_router.py's `list_users`) — never a "fetch N +
  // filter client-side" shortcut.
  list({ page = 1, pageSize = 20, search, sortBy = 'created_at', sortOrder = 'desc' } = {}) {
    return httpClient.get('/users', {
      params: {
        page,
        page_size: pageSize,
        search: search || undefined,
        sort_by: sortBy,
        sort_order: sortOrder,
      },
    });
  },

  // Soft-deactivation (status -> INACTIVE), not a hard delete — reverses
  // via `activate` below. Backend already handles the self-action guard,
  // immediate session revocation (blocks login right away — see
  // AuthService.login's status check), the last-active-admin lockout
  // guard, and audit logging (see backend/app/modules/auth/user_service.py's
  // `deactivate_user`); this is a thin wrapper around the existing
  // `POST /users/{id}/deactivate` endpoint, not new backend behavior.
  deactivate(userId) {
    return httpClient.post(`/users/${userId}/deactivate`);
  },

  // Reverses `deactivate` — status -> ACTIVE via the existing
  // `POST /users/{id}/activate` endpoint (also already audit-logged).
  activate(userId) {
    return httpClient.post(`/users/${userId}/activate`);
  },
};

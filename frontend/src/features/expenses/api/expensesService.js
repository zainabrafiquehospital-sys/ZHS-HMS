import { httpClient } from '@/services/api/httpClient';

// Thin wrapper over backend/app/modules/expenses/router.py — see that
// file's own module docstring for the permission split
// (expenses:log / expenses:read_all) each endpoint requires and why
// every own-scoped route resolves the target from `actor.id`, never a
// request-suppliable id.
export const expensesService = {
  // Own-scoped (expenses:log) — the calling receptionist's own expenses
  // for one Asia/Karachi day (default: today). No user-id parameter on
  // any of the four own calls below, matching how the backend
  // hard-scopes each to `actor.id`.
  listMine({ date } = {}) {
    return httpClient.get('/expenses/mine', { params: { date: date || undefined } });
  },

  create(payload) {
    return httpClient.post('/expenses', payload);
  },

  // Owner-only, same-day-only server-side (see ExpenseService.update /
  // .delete) — a 409 EXPENSE_EDIT_WINDOW_CLOSED comes back once the
  // expense's Karachi day has rolled over, a 403 if the caller is not
  // the owning receptionist.
  update(expenseId, payload) {
    return httpClient.patch(`/expenses/${expenseId}`, payload);
  },

  remove(expenseId) {
    return httpClient.delete(`/expenses/${expenseId}`);
  },

  // Admin-only (expenses:read_all) — every receptionist's expenses for
  // one day, optionally narrowed to a single receptionist.
  listAll({ date, receptionistId } = {}) {
    return httpClient.get('/expenses', {
      params: { date: date || undefined, receptionist_id: receptionistId || undefined },
    });
  },

  // Admin-only (expenses:read_all) — per-receptionist rollup for one
  // day: `(receptionist, count, total)` rows plus a grand total, names
  // resolved server-side.
  getBreakdown({ date } = {}) {
    return httpClient.get('/expenses/stats', { params: { date: date || undefined } });
  },
};

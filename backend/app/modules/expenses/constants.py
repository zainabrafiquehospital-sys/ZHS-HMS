"""Permission codes for the Expense Tracking module.

Two atomic codes, matching this codebase's "narrow, per-action" RBAC
convention (see app/modules/reception/constants.py's own docstring):

- `expenses:log` — a receptionist's own petty-cash lifecycle: create a
  same-day expense, read their own, and edit/delete their own while the
  Asia/Karachi calendar day is still current. Granted to the
  Receptionist role (and admin, via the "admin holds every permission"
  seed convention).
- `expenses:read_all` — cross-receptionist visibility: list every
  receptionist's expenses for a day and the per-receptionist breakdown.
  Admin only; never granted to Receptionist.

Ownership is enforced in `ExpenseService` (an explicit
`expense.receptionist_id != actor.id` check on every edit/delete, the
same pattern app/modules/consultation/service.py uses), never left to
the router's permission gate alone.
"""

PERMISSION_EXPENSES_LOG = "expenses:log"
PERMISSION_EXPENSES_READ_ALL = "expenses:read_all"

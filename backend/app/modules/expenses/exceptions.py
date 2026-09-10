"""Expense-module client-facing exceptions. All subclass the existing
app/core/exceptions.py hierarchy — never a parallel one, mirroring
app/modules/lab/exceptions.py's identical module docstring."""

from app.core.exceptions import ConflictError, NotFoundError


class ExpenseNotFoundError(NotFoundError):
    code = "EXPENSE_NOT_FOUND"

    def __init__(self) -> None:
        super().__init__("Expense not found.")


class ExpenseEditWindowClosedError(ConflictError):
    """Raised by ExpenseService.update/delete when the owning
    receptionist tries to change an expense whose `expense_date` is no
    longer the current Asia/Karachi calendar day. Same-day-only applies
    to edits and deletes, not just creation: once the day has rolled
    over the record is a closed-day fact. Deliberately a 409 (a state
    conflict), not a 403 — the caller *is* the owner and *does* hold
    the permission; the record has simply aged out of its editable
    window."""

    code = "EXPENSE_EDIT_WINDOW_CLOSED"

    def __init__(self, expense_date: str) -> None:
        super().__init__(
            f"This expense was recorded on {expense_date} and can no longer be edited or "
            "deleted — expenses are only changeable on the day they were logged.",
            {"expense_date": expense_date},
        )

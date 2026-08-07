"""Queue-module client-facing exceptions. All subclass the existing
app/core/exceptions.py hierarchy — never a parallel one."""

from app.core.exceptions import ConflictError, NotFoundError


class QueueEntryNotFoundError(NotFoundError):
    code = "QUEUE_ENTRY_NOT_FOUND"

    def __init__(self) -> None:
        super().__init__("Queue entry not found.")


class NoActiveQueueEntryError(NotFoundError):
    code = "NO_ACTIVE_QUEUE_ENTRY"

    def __init__(self) -> None:
        super().__init__("This visit has no active queue entry.")


class VisitAlreadyQueuedError(ConflictError):
    code = "VISIT_ALREADY_QUEUED"

    def __init__(self) -> None:
        super().__init__("This visit already has an active queue entry.")

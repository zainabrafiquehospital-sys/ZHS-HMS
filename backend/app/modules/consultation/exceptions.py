"""Consultation-module client-facing exceptions. All subclass the
existing app/core/exceptions.py hierarchy — never a parallel one."""

from app.core.exceptions import ConflictError, NotFoundError, ValidationError


class ConsultationNotFoundError(NotFoundError):
    code = "CONSULTATION_NOT_FOUND"

    def __init__(self) -> None:
        super().__init__("Consultation not found.")


class NoActiveConsultationForVisitError(NotFoundError):
    code = "NO_ACTIVE_CONSULTATION_FOR_VISIT"

    def __init__(self) -> None:
        super().__init__("This visit has no active consultation.")


class ConsultationAlreadyActiveError(ConflictError):
    code = "CONSULTATION_ALREADY_ACTIVE"

    def __init__(self) -> None:
        super().__init__("This visit already has an active consultation.")


class InvalidConsultationStatusTransitionError(ValidationError):
    code = "INVALID_CONSULTATION_STATUS_TRANSITION"

    def __init__(self, current: str, target: str) -> None:
        super().__init__(
            f"Cannot move a Consultation from '{current}' to '{target}'.",
            {"current_status": current, "target_status": target},
        )

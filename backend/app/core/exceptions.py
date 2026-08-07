class DomainException(Exception):
    """Base class for all application-raised, client-facing exceptions."""

    code: str = "DOMAIN_ERROR"
    status_code: int = 400

    def __init__(self, message: str, details: dict | None = None) -> None:
        self.message = message
        self.details = details or {}
        super().__init__(message)


class ValidationError(DomainException):
    code = "VALIDATION_ERROR"
    status_code = 422


class NotFoundError(DomainException):
    code = "NOT_FOUND"
    status_code = 404


class ConflictError(DomainException):
    code = "CONFLICT"
    status_code = 409


class PermissionDeniedError(DomainException):
    code = "PERMISSION_DENIED"
    status_code = 403


class RecordLockedError(DomainException):
    code = "RECORD_LOCKED"
    status_code = 423


class AuthenticationError(DomainException):
    code = "AUTHENTICATION_ERROR"
    status_code = 401


class RateLimitExceededError(DomainException):
    code = "RATE_LIMIT_EXCEEDED"
    status_code = 429

    def __init__(
        self,
        retry_after_seconds: int,
        message: str = "Too many requests. Please try again later.",
    ) -> None:
        self.retry_after_seconds = retry_after_seconds
        super().__init__(message, details={"retry_after_seconds": retry_after_seconds})

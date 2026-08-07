from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.exceptions import AuthenticationError, DomainException, RateLimitExceededError
from app.core.logging import get_logger

logger = get_logger(__name__)


def _error_envelope(code: str, message: str, details: dict | None = None) -> dict:
    return {
        "data": None,
        "meta": None,
        "error": {"code": code, "message": message, "details": details or {}},
    }


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AuthenticationError)
    async def authentication_exception_handler(
        request: Request, exc: AuthenticationError
    ) -> JSONResponse:
        # RFC 7235: a 401 response should carry a WWW-Authenticate challenge.
        # Registered ahead of the generic DomainException handler below so
        # this more specific one applies to AuthenticationError instances.
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_envelope(exc.code, exc.message, exc.details),
            headers={"WWW-Authenticate": "Bearer"},
        )

    @app.exception_handler(RateLimitExceededError)
    async def rate_limit_exception_handler(
        request: Request, exc: RateLimitExceededError
    ) -> JSONResponse:
        # RFC 9110 §10.2.3: a 429 response should carry a Retry-After
        # header telling the client how long to back off. Registered
        # ahead of the generic DomainException handler below so this more
        # specific one applies to RateLimitExceededError instances.
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_envelope(exc.code, exc.message, exc.details),
            headers={"Retry-After": str(exc.retry_after_seconds)},
        )

    @app.exception_handler(DomainException)
    async def domain_exception_handler(request: Request, exc: DomainException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_envelope(exc.code, exc.message, exc.details),
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.error("unhandled_exception", path=request.url.path, error=str(exc))
        return JSONResponse(
            status_code=500,
            content=_error_envelope("INTERNAL_ERROR", "An unexpected error occurred."),
        )

"""The standard `{"data": ..., "meta": ..., "error": ...}` success response
shape every endpoint returns (see app/core/exception_handlers.py for the
matching error-response shape). Factored out here once a second router
(auth) needed the exact same envelope `app/api/v1/health.py` already
returns inline, rather than duplicating the literal dict shape."""

from typing import Any


def success_envelope(data: Any, meta: dict | None = None) -> dict:
    return {"data": data, "meta": meta, "error": None}

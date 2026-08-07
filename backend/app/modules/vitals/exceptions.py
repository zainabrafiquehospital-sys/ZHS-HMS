"""Vitals-module client-facing exceptions. All subclass the existing
app/core/exceptions.py hierarchy — never a parallel one."""

from app.core.exceptions import NotFoundError


class VitalsRecordNotFoundError(NotFoundError):
    code = "VITALS_RECORD_NOT_FOUND"

    def __init__(self) -> None:
        super().__init__("Vitals record not found.")

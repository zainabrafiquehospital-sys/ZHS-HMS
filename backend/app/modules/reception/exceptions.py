"""Reception-module client-facing exceptions. All subclass the existing
app/core/exceptions.py hierarchy — never a parallel one (see
app/modules/auth/exceptions.py's identical module docstring). First file
of its kind for this module — register_visit/cancel_visit have never
needed one of their own, since every failure they can produce already
bubbles up from PatientService/VisitService/QueueService."""

from app.core.exceptions import ConflictError


class VisitHasSettledInvoiceError(ConflictError):
    """Raised by ReceptionService.admin_delete_visit — the one hard
    block on the 2026-08-19 admin delete-visit feature (see that
    method's own docstring for the full reasoning): a Visit with a
    `PAID`/`PARTIALLY_PAID` Invoice represents real money already
    collected, which must never be silently removed along with the
    Visit it's attached to."""

    code = "VISIT_HAS_SETTLED_INVOICE"

    def __init__(self) -> None:
        super().__init__(
            "This visit has a paid or partially-paid invoice and cannot be deleted — "
            "deleting it would remove the record of money already collected. Visits with "
            "recorded payments are not deletable through this tool."
        )

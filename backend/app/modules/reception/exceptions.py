"""Reception-module client-facing exceptions. All subclass the existing
app/core/exceptions.py hierarchy — never a parallel one (see
app/modules/auth/exceptions.py's identical module docstring). First file
of its kind for this module — register_visit/cancel_visit have never
needed one of their own, since every failure they can produce already
bubbles up from PatientService/VisitService/QueueService."""

from app.core.exceptions import ConflictError, NotFoundError


class DoctorNotAvailableForAssignmentError(NotFoundError):
    """Raised by ReceptionService.register_visit when an explicit
    `doctor_user_id` (2026-08-24 addition — Reception's doctor-selection
    dropdown, RegisterVisitForm.jsx) doesn't resolve via
    ReceptionRepository.get_doctor_by_id: not a real user, not ACTIVE,
    or not currently holding a role that grants `consultation:start`.
    Deliberately raised rather than silently falling back to
    auto-assignment — see that repository method's own docstring for
    why substituting a different doctor than the one Reception
    explicitly picked would be the wrong failure mode here."""

    code = "DOCTOR_NOT_AVAILABLE_FOR_ASSIGNMENT"

    def __init__(self) -> None:
        super().__init__(
            "The selected doctor is not available for assignment — they may no longer "
            "hold doctor permissions or their account may be inactive. Leave the doctor "
            "field blank to auto-assign, or choose a different doctor."
        )


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

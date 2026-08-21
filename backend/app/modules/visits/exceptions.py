"""Visit-module client-facing exceptions. All subclass the existing
app/core/exceptions.py hierarchy — never a parallel one (see
app/modules/auth/exceptions.py's identical module docstring)."""

from app.core.exceptions import ConflictError, NotFoundError, ValidationError


class VisitNotFoundError(NotFoundError):
    code = "VISIT_NOT_FOUND"

    def __init__(self) -> None:
        super().__init__("Visit not found.")


class ProcedureNotFoundError(NotFoundError):
    code = "PROCEDURE_NOT_FOUND"

    def __init__(self) -> None:
        super().__init__("Procedure not found.")


class ProcedureInactiveError(ValidationError):
    """Mirrors app/modules/pharmacy/exceptions.py's identical
    `MedicineInactiveError` — a deactivated catalog Procedure cannot be
    selected for a new visit/edit, exactly like a deactivated Medicine
    cannot be billed."""

    code = "PROCEDURE_INACTIVE"

    def __init__(self, procedure_name: str) -> None:
        super().__init__(
            f"'{procedure_name}' is not currently active and cannot be selected.",
            {"procedure_name": procedure_name},
        )


class VisitNotItemizedError(ConflictError):
    """Raised by VisitService.admin_replace_procedure_items — a Visit
    registered before 2026-08-21 has no `VisitProcedureItem` rows at all
    (an explicit, confirmed design decision — see models.py's
    `VisitProcedureItem` docstring: existing visits are never
    retroactively itemized) and so cannot have its procedure items
    replaced through this action. Its procedure/amount stay editable
    only through the original flat `update_visit_details` path."""

    code = "VISIT_NOT_ITEMIZED"

    def __init__(self) -> None:
        super().__init__(
            "This visit was registered before itemized procedures existed and has no "
            "procedure items to edit — correct its procedure/amount fields directly instead."
        )


class VisitAlreadyItemizedError(ConflictError):
    """The inverse of `VisitNotItemizedError` — raised by
    `update_visit_details` if a caller attempts the old flat
    procedure/amount edit against a visit that already has procedure
    items. Kept as a symmetric, equally explicit rejection rather than
    silently ignoring the field, so a malformed request never appears
    to succeed without doing what it asked."""

    code = "VISIT_ALREADY_ITEMIZED"

    def __init__(self) -> None:
        super().__init__(
            "This visit already has itemized procedures — edit its procedure items directly "
            "instead of its (unused) flat procedure/amount fields."
        )


class InvalidVisitStatusTransitionError(ValidationError):
    code = "INVALID_VISIT_STATUS_TRANSITION"

    def __init__(self, current: str, target: str) -> None:
        super().__init__(
            f"Cannot move a Visit from '{current}' to '{target}'.",
            {"current_status": current, "target_status": target},
        )


class VisitDiscountExceedsAmountError(ValidationError):
    """Mirrors app/modules/pharmacy/exceptions.py's identical
    `MedicineBillDiscountExceedsSubtotalError` — there is deliberately
    no `VisitDiscountReasonRequiredError` sibling: a registration-time
    discount's reason is always optional (2026-08-19 addition), the
    same product decision the medicine-bill discount already made."""

    code = "VISIT_DISCOUNT_EXCEEDS_AMOUNT"

    def __init__(self, amount: str) -> None:
        super().__init__(
            f"Discount exceeds the entered amount of {amount}.", {"amount": amount}
        )

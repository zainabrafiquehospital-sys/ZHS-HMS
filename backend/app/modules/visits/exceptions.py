"""Visit-module client-facing exceptions. All subclass the existing
app/core/exceptions.py hierarchy — never a parallel one (see
app/modules/auth/exceptions.py's identical module docstring)."""

from app.core.exceptions import NotFoundError, ValidationError


class VisitNotFoundError(NotFoundError):
    code = "VISIT_NOT_FOUND"

    def __init__(self) -> None:
        super().__init__("Visit not found.")


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

"""Pharmacy-module client-facing exceptions. All subclass the existing
app/core/exceptions.py hierarchy — never a parallel one, mirroring
app/modules/billing/exceptions.py's identical module docstring."""

from app.core.exceptions import NotFoundError, ValidationError


class MedicineNotFoundError(NotFoundError):
    code = "MEDICINE_NOT_FOUND"

    def __init__(self) -> None:
        super().__init__("Medicine not found.")


class MedicineInactiveError(ValidationError):
    code = "MEDICINE_INACTIVE"

    def __init__(self, medicine_name: str) -> None:
        super().__init__(
            f"'{medicine_name}' is not currently active and cannot be billed.",
            {"medicine_name": medicine_name},
        )


class MedicineBillNotFoundError(NotFoundError):
    code = "MEDICINE_BILL_NOT_FOUND"

    def __init__(self) -> None:
        super().__init__("Medicine bill not found.")


class MedicineBillEmptyError(ValidationError):
    code = "MEDICINE_BILL_EMPTY"

    def __init__(self) -> None:
        super().__init__("A medicine bill must have at least one line item.")

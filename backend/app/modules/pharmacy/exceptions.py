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


class MedicineBillNotPayableError(ValidationError):
    code = "MEDICINE_BILL_NOT_PAYABLE"

    def __init__(self, status: str) -> None:
        super().__init__(
            f"A medicine bill with status '{status}' cannot receive a payment.",
            {"status": status},
        )


class MedicineBillPaymentExceedsBalanceError(ValidationError):
    code = "MEDICINE_BILL_PAYMENT_EXCEEDS_BALANCE"

    def __init__(self, remaining_balance: str) -> None:
        super().__init__(
            f"Payment exceeds the remaining balance of {remaining_balance}.",
            {"remaining_balance": remaining_balance},
        )


class MedicineBillManualPatientConflictsWithVisitError(ValidationError):
    code = "MEDICINE_BILL_MANUAL_PATIENT_CONFLICTS_WITH_VISIT"

    def __init__(self) -> None:
        super().__init__(
            "A medicine bill cannot have both a linked visit and manual patient details."
        )


class MedicineBillManualPatientFieldsIncompleteError(ValidationError):
    code = "MEDICINE_BILL_MANUAL_PATIENT_FIELDS_INCOMPLETE"

    def __init__(self) -> None:
        super().__init__(
            "Manual patient details require name, age, and contact number all together."
        )

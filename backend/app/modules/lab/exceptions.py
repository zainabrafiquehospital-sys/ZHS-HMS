"""Lab-module client-facing exceptions. All subclass the existing
app/core/exceptions.py hierarchy — never a parallel one, mirroring
app/modules/pharmacy/exceptions.py's identical module docstring."""

from app.core.exceptions import ConflictError, NotFoundError, ValidationError


class LabTestNotFoundError(NotFoundError):
    code = "LAB_TEST_NOT_FOUND"

    def __init__(self) -> None:
        super().__init__("Lab test not found.")


class LabTestInactiveError(ValidationError):
    code = "LAB_TEST_INACTIVE"

    def __init__(self, lab_test_name: str) -> None:
        super().__init__(
            f"'{lab_test_name}' is not currently active and cannot be billed.",
            {"lab_test_name": lab_test_name},
        )


class LabBillNotFoundError(NotFoundError):
    code = "LAB_BILL_NOT_FOUND"

    def __init__(self) -> None:
        super().__init__("Lab bill not found.")


class LabBillNotPayableError(ValidationError):
    code = "LAB_BILL_NOT_PAYABLE"

    def __init__(self, status: str) -> None:
        super().__init__(
            f"A lab bill with status '{status}' cannot receive a payment.", {"status": status}
        )


class LabBillPaymentExceedsBalanceError(ValidationError):
    code = "LAB_BILL_PAYMENT_EXCEEDS_BALANCE"

    def __init__(self, remaining_balance: str) -> None:
        super().__init__(
            f"Payment exceeds the remaining balance of {remaining_balance}.",
            {"remaining_balance": remaining_balance},
        )


class LabBillManualPatientConflictsWithPatientError(ValidationError):
    """Mirrors app/modules/inventory/exceptions.py's identical
    `InventoryUsageManualPatientConflictsWithPatientError` — LabBill's
    patient linkage is a direct Patient link (confirmed design), not
    Visit-mediated like MedicineBill's, so this is named/shaped after
    Inventory's own usage-entry precedent rather than Pharmacy's."""

    code = "LAB_BILL_MANUAL_PATIENT_CONFLICTS_WITH_PATIENT"

    def __init__(self) -> None:
        super().__init__("A lab bill cannot have both a linked patient and manual patient details.")


class LabBillManualPatientFieldsIncompleteError(ValidationError):
    code = "LAB_BILL_MANUAL_PATIENT_FIELDS_INCOMPLETE"

    def __init__(self) -> None:
        super().__init__(
            "Manual patient details require name, age, and contact number all together."
        )


class LabBillDiscountExceedsSubtotalError(ValidationError):
    code = "LAB_BILL_DISCOUNT_EXCEEDS_SUBTOTAL"

    def __init__(self, subtotal: str) -> None:
        super().__init__(
            f"Discount exceeds the lab bill subtotal of {subtotal}.", {"subtotal": subtotal}
        )


class LabBillPaymentMethodRequiredError(ValidationError):
    code = "LAB_BILL_PAYMENT_METHOD_REQUIRED"

    def __init__(self) -> None:
        super().__init__("A payment method is required whenever a payment is recorded.")


class LabBillHasSettledPaymentError(ConflictError):
    """Raised by LabService.admin_update_bill/admin_delete_bill —
    mirrors app/modules/pharmacy/exceptions.py's identical
    `MedicineBillHasSettledPaymentError` for the identical reason: a
    LabBill's own `discount_amount` directly determines its own stored
    `total_amount` on the same row a payment is recorded against, so
    editing/deleting is blocked outright once any payment exists."""

    code = "LAB_BILL_HAS_SETTLED_PAYMENT"

    def __init__(self) -> None:
        super().__init__(
            "This lab bill has a paid or partially-paid balance and cannot be edited or "
            "deleted — doing so would risk the record of money already collected. Lab bills "
            "with recorded payments are not editable or deletable through this tool."
        )

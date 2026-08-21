"""Pharmacy-module client-facing exceptions. All subclass the existing
app/core/exceptions.py hierarchy — never a parallel one, mirroring
app/modules/billing/exceptions.py's identical module docstring."""

from app.core.exceptions import ConflictError, NotFoundError, ValidationError


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


class MedicineBillDiscountExceedsSubtotalError(ValidationError):
    """Mirrors app/modules/billing/exceptions.py's identical
    `DiscountExceedsSubtotalError` — there is deliberately no
    `MedicineBillDiscountReasonRequiredError` sibling: unlike Invoice's
    discount, a medicine bill's discount reason is always optional (a
    2026-08-19 product decision for this feature specifically), so
    there is no reason-required rule to enforce."""

    code = "MEDICINE_BILL_DISCOUNT_EXCEEDS_SUBTOTAL"

    def __init__(self, subtotal: str) -> None:
        super().__init__(
            f"Discount exceeds the medicine bill subtotal of {subtotal}.", {"subtotal": subtotal}
        )


class MedicineBillPaymentMethodRequiredError(ValidationError):
    """Mirrors app/modules/billing/exceptions.py's identical
    `PaymentMethodRequiredError` — a real payment's method is never
    optional when an amount is actually being recorded (2026-08-19
    addition, see app/shared/payment_method.py's module docstring)."""

    code = "MEDICINE_BILL_PAYMENT_METHOD_REQUIRED"

    def __init__(self) -> None:
        super().__init__("A payment method is required whenever a payment is recorded.")


class MedicineBillHasSettledPaymentError(ConflictError):
    """Raised by PharmacyService.admin_update_bill/admin_delete_bill
    (2026-08-20 addition) — the one hard block on both admin
    correction actions, mirroring app/modules/reception/exceptions.py's
    identical `VisitHasSettledInvoiceError`. Applied to *both* edit and
    delete here, unlike Visit (where edit and delete have different
    blast radii): a MedicineBill's own `discount_amount` directly
    determines its own stored `total_amount` on the same row a payment
    is recorded against — there is no separate, decoupled Invoice
    entity the way Visit has, so editing the discount on a bill that
    already has money collected against it would desynchronize
    `amount_paid`/`total_amount` on that same row. Blocking both once
    `status` is `PARTIALLY_PAID`/`PAID` also matches the already-frozen
    Phase 6 principle that a settled Invoice is immutable (see
    docs/PHASE_6_ARCHITECTURE.md)."""

    code = "MEDICINE_BILL_HAS_SETTLED_PAYMENT"

    def __init__(self) -> None:
        super().__init__(
            "This medicine bill has a paid or partially-paid balance and cannot be edited or "
            "deleted — doing so would risk the record of money already collected. Medicine "
            "bills with recorded payments are not editable or deletable through this tool."
        )

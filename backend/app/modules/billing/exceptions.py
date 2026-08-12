"""Billing-module client-facing exceptions. All subclass the existing
app/core/exceptions.py hierarchy — never a parallel one."""

from app.core.exceptions import ConflictError, NotFoundError, ValidationError


class PendingBillingItemNotFoundError(NotFoundError):
    code = "PENDING_BILLING_ITEM_NOT_FOUND"

    def __init__(self) -> None:
        super().__init__("Pending billing item not found.")


class PendingBillingItemNotPendingError(ValidationError):
    code = "PENDING_BILLING_ITEM_NOT_PENDING"

    def __init__(self) -> None:
        super().__init__("Only a pending billing item can be approved or rejected.")


class InvoiceNotFoundError(NotFoundError):
    code = "INVOICE_NOT_FOUND"

    def __init__(self) -> None:
        super().__init__("Invoice not found.")


class InvoiceAlreadyOpenError(ConflictError):
    code = "INVOICE_ALREADY_OPEN"

    def __init__(self) -> None:
        super().__init__(
            "This visit already has an open (unpaid) invoice — generate is not repeatable "
            "until it is paid or cancelled."
        )


class InvoiceNotPayableError(ValidationError):
    code = "INVOICE_NOT_PAYABLE"

    def __init__(self, status: str) -> None:
        super().__init__(
            f"An invoice with status '{status}' cannot receive a payment.", {"status": status}
        )


class PaymentExceedsBalanceError(ValidationError):
    code = "PAYMENT_EXCEEDS_BALANCE"

    def __init__(self, remaining_balance: str) -> None:
        super().__init__(
            f"Payment exceeds the remaining balance of {remaining_balance}.",
            {"remaining_balance": remaining_balance},
        )


class DiscountExceedsSubtotalError(ValidationError):
    code = "DISCOUNT_EXCEEDS_SUBTOTAL"

    def __init__(self, subtotal: str) -> None:
        super().__init__(
            f"Discount exceeds the invoice subtotal of {subtotal}.", {"subtotal": subtotal}
        )


class DiscountReasonRequiredError(ValidationError):
    code = "DISCOUNT_REASON_REQUIRED"

    def __init__(self) -> None:
        super().__init__("A reason is required whenever a discount is applied.")


class InvoiceImmutableError(ConflictError):
    code = "INVOICE_IMMUTABLE"

    def __init__(self) -> None:
        super().__init__("A paid or cancelled invoice can never be modified.")

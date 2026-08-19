"""The shared payment-method vocabulary (2026-08-19 addition) —
recorded manually by staff at the moment they confirm a payment was
made: cash handed over in person, or a bank transfer/JazzCash/
EasyPaisa/card payment the patient made separately that staff then
confirms. This is explicitly NOT a payment gateway integration —
nothing here initiates, processes, or verifies an actual transaction;
it is purely a record of what staff observed/were told.

Lives in `app/shared/` rather than inside Billing or Pharmacy because
both `InvoicePayment` (billing) and `MedicineBillPayment` (pharmacy)
need the exact same vocabulary, and Phase 6 architecture §12's
one-directional module dependency graph forbids either module
importing the other's types — `shared/` is the one place both may
depend on without violating that graph. Every existing payment row
predates this feature and was, in fact, always cash (the only method
this system had any concept of before now) — see the migration that
added `payment_method` for the correct, non-destructive backfill this
enables."""

from enum import Enum as PyEnum


class PaymentMethod(PyEnum):
    CASH = "cash"
    BANK_TRANSFER = "bank_transfer"
    JAZZCASH = "jazzcash"
    EASYPAISA = "easypaisa"
    CARD = "card"


# Human-readable display labels — used by the Central Print Service
# (app/shared/printing/service.py) to render a value like "bank_transfer"
# as "Bank Transfer" rather than the raw enum value. Keyed by the
# enum's own string value, not the PyEnum member, so callers holding
# either an already-loaded `PaymentMethod` or a raw string from the
# database (e.g. a `GROUP BY` query result) can look it up the same way.
PAYMENT_METHOD_LABELS: dict[str, str] = {
    PaymentMethod.CASH.value: "Cash",
    PaymentMethod.BANK_TRANSFER.value: "Bank Transfer",
    PaymentMethod.JAZZCASH.value: "JazzCash",
    PaymentMethod.EASYPAISA.value: "EasyPaisa",
    PaymentMethod.CARD.value: "Card",
}

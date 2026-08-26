"""Inventory-module client-facing exceptions. All subclass the existing
app/core/exceptions.py hierarchy — never a parallel one, mirroring
app/modules/pharmacy/exceptions.py's identical module docstring."""

from decimal import Decimal

from app.core.exceptions import ConflictError, NotFoundError, ValidationError


class InventoryItemNotFoundError(NotFoundError):
    code = "INVENTORY_ITEM_NOT_FOUND"

    def __init__(self) -> None:
        super().__init__("Inventory item not found.")


class InventoryItemInactiveError(ValidationError):
    code = "INVENTORY_ITEM_INACTIVE"

    def __init__(self, item_name: str) -> None:
        super().__init__(
            f"'{item_name}' is not currently active and cannot be received, transferred, "
            "or used.",
            {"item_name": item_name},
        )


class InventoryCategoryUnitMismatchError(ValidationError):
    code = "INVENTORY_CATEGORY_UNIT_MISMATCH"

    def __init__(self, category: str, unit: str, allowed_units: list[str]) -> None:
        super().__init__(
            f"Unit '{unit}' is not a standardized unit for category '{category}'.",
            {"category": category, "unit": unit, "allowed_units": allowed_units},
        )


class InsufficientMainStockError(ValidationError):
    """Raised by `transfer_to_emergency`/`fulfill_request` — never let a
    transfer take Main Stock below zero (Backend Architect review's own
    answer: neither stock level may ever go negative, enforced by
    rejecting the whole write before anything is committed, not a silent
    clamp)."""

    code = "INSUFFICIENT_MAIN_STOCK"

    def __init__(self, available: Decimal) -> None:
        super().__init__(
            f"Only {available} available in Main Stock.", {"available": str(available)}
        )


class InsufficientEmergencyStockError(ValidationError):
    """Raised by `record_usage` — the identical guarantee as
    `InsufficientMainStockError`, for Emergency Stock."""

    code = "INSUFFICIENT_EMERGENCY_STOCK"

    def __init__(self, available: Decimal) -> None:
        super().__init__(
            f"Only {available} available in Emergency Stock.", {"available": str(available)}
        )


class InventoryUsageManualPatientConflictsWithPatientError(ValidationError):
    code = "INVENTORY_USAGE_MANUAL_PATIENT_CONFLICTS_WITH_PATIENT"

    def __init__(self) -> None:
        super().__init__(
            "A usage entry cannot have both a linked patient and manual patient details."
        )


class InventoryUsageManualPatientFieldsIncompleteError(ValidationError):
    code = "INVENTORY_USAGE_MANUAL_PATIENT_FIELDS_INCOMPLETE"

    def __init__(self) -> None:
        super().__init__(
            "Manual patient details require name, age, and contact number all together."
        )


class InventoryRestockRequestNotFoundError(NotFoundError):
    code = "INVENTORY_RESTOCK_REQUEST_NOT_FOUND"

    def __init__(self) -> None:
        super().__init__("Restock request not found.")


class InventoryRestockRequestNotPendingError(ConflictError):
    """Raised by `fulfill_request`/`reject_request` against a request
    that isn't `PENDING` — mirrors `MedicineBillNotPayableError`'s
    identical "this row already reached a terminal state" shape."""

    code = "INVENTORY_RESTOCK_REQUEST_NOT_PENDING"

    def __init__(self, status: str) -> None:
        super().__init__(
            f"This restock request is already '{status}' and cannot be acted on again.",
            {"status": status},
        )

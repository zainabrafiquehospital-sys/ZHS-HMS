"""SQLAlchemy models for the Ward/Emergency Inventory Management module.

Deliberately independent from app/modules/pharmacy — Pharmacy is a
priced-sale-and-billing module with no stock concept at all
(Medicine carries a price, never a quantity, by design; see that
module's own docstring); this module is the reverse — stock custody
and usage tracking, with no pricing/billing dimension whatsoever. The
two only coincidentally look similar (both eventually reach a patient);
structurally this module imports nothing from Pharmacy, and Pharmacy
imports nothing from here. Its only real dependencies are Patients
(a usage entry's optional patient link) and Auth (permissions) — the
same one-directional shape every other module already has on those.

Two-tier stock model (confirmed design): every `InventoryItem` carries
two independently-maintained running-total columns, `main_stock_level`
(the full warehouse, increased only by a receipt) and
`emergency_stock_level` (the ward/emergency pool, increased only by a
transfer out of Main Stock, decreased only by a usage entry — Vitals
never touches Main Stock directly). Both are maintained in the same
transaction as the ledger row that changes them — the exact hybrid
`Invoice.amount_paid`/`InvoicePayment` and `MedicineBill.amount_paid`/
`MedicineBillPayment` already establish for money: a transactionally-
consistent cache column for fast reads (a dashboard's live stock level
is one row lookup, never a `SUM()` over history), backed by a genuine
append-only ledger for the full audit trail those money tables already
proved the pattern for. Both levels are `CHECK >= 0` — real database
backstops, not just service-layer discipline, mirroring every other
non-negative-balance invariant in this codebase (e.g. `Invoice.
amount_paid <= total_amount`).

Three concrete ledger tables, not one polymorphic "movement" table with
a type discriminator — `InventoryMainStockReceipt`, `InventoryTransfer`,
`InventoryUsageEntry` each have genuinely different shapes (a usage
entry alone carries patient/manual-entry/reason-note columns), and this
codebase's own established idiom is concrete tables per concept, never
a shared polymorphic ledger (see `MedicineBillPayment`/`InvoicePayment`,
`MedicineBillItem`/`InvoiceLineItem`/`VisitProcedureItem` — always
separate tables, never one generic "transaction" table with columns
that are `NULL` by construction for most rows).

All five tables use `BaseEntity` (not `TimestampedEntity`), matching
`MedicineBillPayment`'s/`InvoicePayment`'s own choice: these rows are
functionally immutable/append-only in practice (never edited, never
soft-deleted by any code path here), but `BaseEntity`'s `created_by`/
soft-delete columns are kept for the same uniformity those two payment
tables already chose over `TimestampedEntity`, rather than introducing
a third audit-column convention into the codebase for no real benefit."""

from datetime import date as date_type
from datetime import datetime
from decimal import Decimal
from enum import Enum as PyEnum
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base_entity import BaseEntity

# Numeric, not Integer — most items (tablets, vials, pieces) are always
# whole numbers in practice, but the unit vocabulary explicitly includes
# "ml" (a drip/bottle content), which is legitimately fractional. One
# quantity type for every item regardless of its own unit is a simpler
# mental model than switching column types per category, and mirrors
# this codebase's own "money is always Numeric, never a type that
# depends on the specific value" discipline (see
# app/modules/billing/models.py's module docstring on Numeric vs Float).
_QUANTITY = Numeric(12, 2)


class InventoryCategory(PyEnum):
    MEDICINE = "medicine"
    INJECTION = "injection"
    DRIP = "drip"
    EQUIPMENT = "equipment"


class InventoryUnit(PyEnum):
    PIECE = "piece"
    BOX = "box"
    BOTTLE = "bottle"
    VIAL = "vial"
    AMPOULE = "ampoule"
    ML = "ml"


# Standardized per category (confirmed design — "not free text"): which
# units are valid for which category. Enforced in InventoryService
# (create_item/update_item), never as a per-request Pydantic
# model_validator — a PATCH request only ever sees the fields actually
# being changed, so only the service (which always has the item's full,
# post-update state in hand) can correctly validate the *resulting*
# category+unit combination regardless of whether category, unit, both,
# or neither were touched by a given request. Same "service is the one
# place cross-field invariants are enforced" convention this codebase
# already follows for e.g. MedicineBill's manual-patient mutual-
# exclusivity (validated in PharmacyService.create_bill, not the schema).
CATEGORY_ALLOWED_UNITS: dict[InventoryCategory, frozenset[InventoryUnit]] = {
    InventoryCategory.MEDICINE: frozenset(
        {InventoryUnit.PIECE, InventoryUnit.BOTTLE, InventoryUnit.BOX}
    ),
    InventoryCategory.INJECTION: frozenset(
        {InventoryUnit.VIAL, InventoryUnit.AMPOULE, InventoryUnit.PIECE}
    ),
    InventoryCategory.DRIP: frozenset({InventoryUnit.BOTTLE, InventoryUnit.ML}),
    InventoryCategory.EQUIPMENT: frozenset({InventoryUnit.PIECE, InventoryUnit.BOX}),
}


class InventoryRestockRequestStatus(PyEnum):
    PENDING = "pending"
    FULFILLED = "fulfilled"
    REJECTED = "rejected"


def _enum_column(enum_cls: type[PyEnum], *, name: str, length: int = 20):
    return Enum(
        enum_cls,
        name=name,
        native_enum=False,
        length=length,
        values_callable=lambda cls: [member.value for member in cls],
        create_constraint=True,
    )


class InventoryItem(BaseEntity):
    """The catalog — one row per distinct stocked item. `is_active`
    (2026-08-26 addition, for symmetry with `Medicine.is_active`) is a
    "no longer stocked" flag distinct from `deleted_at`: a deactivated
    item drops out of Vitals'/the Inventory Manager's active pickers but
    stays visible (and re-activatable) on the management screen, and
    every ledger row that already referenced it keeps working unchanged
    — the identical rationale `Medicine.is_active`'s own docstring gives.

    `low_stock_threshold` is optional (`NULL` = no alert configured for
    this item) — compared live against `emergency_stock_level` at query
    time (`WHERE emergency_stock_level <= low_stock_threshold`), never
    cached as a stored boolean: unlike `MedicineBill.status` (cached
    because deriving it cheaply requires summing a payment table), "is
    this item low" is a single indexed-column comparison against another
    column on the same row — computing it live is simpler and cannot
    drift, so caching it here would only add a second place to keep in
    sync for no benefit."""

    __tablename__ = "inventory_item"
    __table_args__ = (
        Index("ix_inventory_item_name", "name"),
        Index("ix_inventory_item_category", "category"),
        Index("ix_inventory_item_is_active", "is_active"),
        CheckConstraint(
            "main_stock_level >= 0", name="ck_inventory_item_main_stock_level_non_negative"
        ),
        CheckConstraint(
            "emergency_stock_level >= 0",
            name="ck_inventory_item_emergency_stock_level_non_negative",
        ),
        CheckConstraint(
            "low_stock_threshold IS NULL OR low_stock_threshold >= 0",
            name="ck_inventory_item_low_stock_threshold_non_negative",
        ),
    )

    name: Mapped[str] = mapped_column(String(150), nullable=False)
    category: Mapped[InventoryCategory] = mapped_column(
        _enum_column(InventoryCategory, name="inventory_category"), nullable=False
    )
    unit: Mapped[InventoryUnit] = mapped_column(
        _enum_column(InventoryUnit, name="inventory_unit"), nullable=False
    )
    low_stock_threshold: Mapped[Decimal | None] = mapped_column(_QUANTITY)
    # Maintained running totals — see this module's own docstring for
    # the full "transactionally-consistent cache over an append-only
    # ledger" rationale. Never written directly outside
    # InventoryService's locked read-modify-write methods.
    main_stock_level: Mapped[Decimal] = mapped_column(
        _QUANTITY, nullable=False, default=Decimal("0")
    )
    emergency_stock_level: Mapped[Decimal] = mapped_column(
        _QUANTITY, nullable=False, default=Decimal("0")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class InventoryMainStockReceipt(BaseEntity):
    """One Main Stock receipt — the only way `InventoryItem.
    main_stock_level` ever increases. `received_on` is a real,
    caller-supplied date distinct from the inherited `created_at`
    (when the row was actually entered into the system) — a receipt is
    routinely logged after the fact (stock arrived yesterday, entered
    today), so the two are deliberately allowed to differ, the same way
    `MedicineBill`'s slip shows `created_at` for "billed on" but this
    module's own print log needs the *received* date, not the *entered*
    date, to be meaningful."""

    __tablename__ = "inventory_main_stock_receipt"
    __table_args__ = (
        Index("ix_inventory_main_stock_receipt_item_id", "item_id"),
        CheckConstraint("quantity > 0", name="ck_inventory_main_stock_receipt_quantity_positive"),
    )

    item_id: Mapped[UUID] = mapped_column(ForeignKey("inventory_item.id"), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(_QUANTITY, nullable=False)
    received_on: Mapped[date_type] = mapped_column(Date, nullable=False)


class InventoryTransfer(BaseEntity):
    """One Main Stock -> Emergency Stock transfer — the only way
    `emergency_stock_level` increases, and one of two ways
    `main_stock_level` decreases... in practice the *only* way, since
    there is no other Main Stock debit in this design. `transferred_on`
    mirrors `InventoryMainStockReceipt.received_on`'s identical
    entered-vs-effective-date rationale."""

    __tablename__ = "inventory_transfer"
    __table_args__ = (
        Index("ix_inventory_transfer_item_id", "item_id"),
        CheckConstraint("quantity > 0", name="ck_inventory_transfer_quantity_positive"),
    )

    item_id: Mapped[UUID] = mapped_column(ForeignKey("inventory_item.id"), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(_QUANTITY, nullable=False)
    transferred_on: Mapped[date_type] = mapped_column(Date, nullable=False)


class InventoryUsageEntry(BaseEntity):
    """One Emergency Stock usage entry — the only way
    `emergency_stock_level` decreases. Patient-linked, not visit-linked
    (a deliberate departure from `MedicineBill.visit_id`'s convention —
    confirmed design decision): this module's own "ward/emergency" scope
    is exactly the population most likely to have no same-day OPD Visit
    at all, so linking to a Visit would force a manual-entry fallback
    even for a genuine, already-registered patient. `patient_id` is
    mutually exclusive with the three manual fields, all-or-nothing when
    used — the identical two CHECK constraints `MedicineBill` already
    enforces for its own visit_id/manual-fields split, just with
    `patient_id` standing in for `visit_id`.

    `reason_note` (confirmed design, item 3) is always optional free
    text — a short "why", not a structured field."""

    __tablename__ = "inventory_usage_entry"
    __table_args__ = (
        Index("ix_inventory_usage_entry_item_id", "item_id"),
        Index("ix_inventory_usage_entry_patient_id", "patient_id"),
        Index("ix_inventory_usage_entry_created_at", "created_at"),
        CheckConstraint("quantity > 0", name="ck_inventory_usage_entry_quantity_positive"),
        CheckConstraint(
            "NOT (patient_id IS NOT NULL AND manual_patient_name IS NOT NULL)",
            name="ck_inventory_usage_entry_not_both_patient_and_manual",
        ),
        CheckConstraint(
            "(manual_patient_name IS NULL AND manual_patient_age IS NULL "
            "AND manual_patient_phone IS NULL) OR (manual_patient_name IS NOT NULL "
            "AND manual_patient_age IS NOT NULL AND manual_patient_phone IS NOT NULL)",
            name="ck_inventory_usage_entry_manual_patient_fields_all_or_none",
        ),
    )

    item_id: Mapped[UUID] = mapped_column(ForeignKey("inventory_item.id"), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(_QUANTITY, nullable=False)
    used_on: Mapped[date_type] = mapped_column(Date, nullable=False)
    # Nullable: mutually exclusive with the three manual fields below —
    # see this class's own docstring and the table's two CHECK
    # constraints above.
    patient_id: Mapped[UUID | None] = mapped_column(ForeignKey("patient.id"))
    manual_patient_name: Mapped[str | None] = mapped_column(String(150))
    manual_patient_age: Mapped[int | None] = mapped_column(Integer)
    manual_patient_phone: Mapped[str | None] = mapped_column(String(20))
    reason_note: Mapped[str | None] = mapped_column(String(200))


class InventoryRestockRequest(BaseEntity):
    """A Vitals-raised request for the Inventory Manager to top up an
    Emergency Stock item. `requested_quantity` is optional — "just flag
    it low" (no specific number, manager's judgment) is a legitimate
    request, not an incomplete one; when Vitals does know exactly how
    much they want, they can say so.

    Terminal once resolved (`FULFILLED`/`REJECTED`) — the same
    immutable-once-settled posture `MedicineBill`/`Invoice` already
    apply to a fully `PAID` row; enforced by `InventoryService.
    fulfill_request`/`reject_request` both requiring `PENDING` first,
    never by a DB constraint (the status transition itself, unlike a
    money-field invariant, has no natural CHECK-constraint expression).

    `fulfilled_by_transfer_id` (set only when `status == FULFILLED`) is
    a one-directional traceability link to the actual `InventoryTransfer`
    row that satisfied this request — the identical shape
    `InvoiceLineItem.pending_billing_item_id` already establishes for
    "this billed line came from that approved request". Deliberately
    one-directional only (`InventoryTransfer` carries no reverse column)
    to avoid a circular FK between the two tables; the rare reverse
    lookup ("was this transfer for a request?") is a cheap
    `WHERE fulfilled_by_transfer_id = :id` query when actually needed,
    not a column.

    `rejection_reason` is optional (confirmed design) — a rejection
    needs no mandatory justification, unlike e.g. `Invoice.
    discount_reason`, which is required whenever a discount is applied."""

    __tablename__ = "inventory_restock_request"
    __table_args__ = (
        Index("ix_inventory_restock_request_status_created_at", "status", "created_at"),
        Index("ix_inventory_restock_request_item_id", "item_id"),
        CheckConstraint(
            "requested_quantity IS NULL OR requested_quantity > 0",
            name="ck_inventory_restock_request_requested_quantity_positive",
        ),
    )

    item_id: Mapped[UUID] = mapped_column(ForeignKey("inventory_item.id"), nullable=False)
    requested_quantity: Mapped[Decimal | None] = mapped_column(_QUANTITY)
    note: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[InventoryRestockRequestStatus] = mapped_column(
        _enum_column(InventoryRestockRequestStatus, name="inventory_restock_request_status"),
        nullable=False,
        default=InventoryRestockRequestStatus.PENDING,
    )
    fulfilled_by_transfer_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("inventory_transfer.id")
    )
    rejection_reason: Mapped[str | None] = mapped_column(String(200))
    resolved_by: Mapped[UUID | None] = mapped_column(ForeignKey("user.id", ondelete="SET NULL"))
    resolved_at: Mapped[datetime | None] = mapped_column()

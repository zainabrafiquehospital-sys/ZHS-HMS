"""Ward/Emergency Inventory Management business logic.

Every stock-level mutation (`receive_stock`, `transfer_to_emergency`,
`record_usage`, and `fulfill_request` — which performs a transfer
internally) follows the identical shape `BillingService.record_payment`/
`PharmacyService.record_payment` already established for a money
read-modify-write: lock the row with `SELECT ... FOR UPDATE`
(`InventoryItemRepository.get_for_update`), validate the resulting
level would stay `>= 0`, mutate the level column(s) and insert the
ledger row in the same transaction, commit once. A transfer and a usage
entry racing against the same item are naturally serialized by that
same single-row lock — no special-casing needed beyond the existing
discipline every other locked read-modify-write in this codebase
already follows.

Neither stock level may ever go negative (Backend Architect review's own
answer) — a write that would drive one below zero is rejected outright,
atomically, before anything is written (`InsufficientMainStockError`/
`InsufficientEmergencyStockError`), the same "validate everything before
writing anything" discipline `PharmacyService.create_bill` follows."""

from datetime import UTC, datetime
from datetime import date as date_type
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ValidationError
from app.modules.auth.models import User
from app.modules.inventory.exceptions import (
    InsufficientEmergencyStockError,
    InsufficientMainStockError,
    InventoryCategoryUnitMismatchError,
    InventoryItemInactiveError,
    InventoryItemNotFoundError,
    InventoryRestockRequestNotFoundError,
    InventoryRestockRequestNotPendingError,
    InventoryUsageManualPatientConflictsWithPatientError,
    InventoryUsageManualPatientFieldsIncompleteError,
)
from app.modules.inventory.models import (
    CATEGORY_ALLOWED_UNITS,
    InventoryCategory,
    InventoryEmergencyDirectReceipt,
    InventoryItem,
    InventoryMainStockReceipt,
    InventoryRestockRequest,
    InventoryRestockRequestStatus,
    InventoryTransfer,
    InventoryUnit,
    InventoryUsageEntry,
)
from app.modules.inventory.repository import (
    INVENTORY_ITEM_SORTABLE_COLUMNS,
    InventoryEmergencyDirectReceiptRepository,
    InventoryItemRepository,
    InventoryMainStockReceiptRepository,
    InventoryRestockRequestRepository,
    InventoryTransferRepository,
    InventoryUsageEntryRepository,
)
from app.modules.patients.models import Patient
from app.modules.patients.service import PatientService
from app.modules.visits.models import Visit
from app.modules.visits.service import VisitService
from app.shared.audit.repository import AuditLogRepository

_QUANTITY_SCALE = Decimal("0.01")


def _quantize_quantity(value: Decimal) -> Decimal:
    """Same construction-time-quantization discipline as
    `app/shared/money.py`'s `quantize_money` — see that function's
    docstring for why this must happen before the value ever touches
    the ORM, not just formatted on the way out."""
    return value.quantize(_QUANTITY_SCALE, rounding=ROUND_HALF_UP)


class InventoryService:
    def __init__(
        self,
        session: AsyncSession,
        item_repository: InventoryItemRepository,
        receipt_repository: InventoryMainStockReceiptRepository,
        emergency_direct_receipt_repository: InventoryEmergencyDirectReceiptRepository,
        transfer_repository: InventoryTransferRepository,
        usage_repository: InventoryUsageEntryRepository,
        request_repository: InventoryRestockRequestRepository,
        patient_service: PatientService,
        visit_service: VisitService,
        audit_repository: AuditLogRepository,
    ) -> None:
        self._session = session
        self._item_repo = item_repository
        self._receipt_repo = receipt_repository
        self._emergency_direct_receipt_repo = emergency_direct_receipt_repository
        self._transfer_repo = transfer_repository
        self._usage_repo = usage_repository
        self._request_repo = request_repository
        self._patient_service = patient_service
        self._visit_service = visit_service
        self._audit_repo = audit_repository

    # ------------------------------------------------------------------
    # Catalog (Inventory Manager only, inventory:manage)
    # ------------------------------------------------------------------

    def _validate_category_unit(self, category: InventoryCategory, unit: InventoryUnit) -> None:
        allowed = CATEGORY_ALLOWED_UNITS[category]
        if unit not in allowed:
            raise InventoryCategoryUnitMismatchError(
                category.value, unit.value, sorted(u.value for u in allowed)
            )

    async def create_item(
        self,
        *,
        actor: User,
        name: str,
        category: InventoryCategory,
        unit: InventoryUnit,
        low_stock_threshold: Decimal | None,
    ) -> InventoryItem:
        self._validate_category_unit(category, unit)
        if low_stock_threshold is not None:
            low_stock_threshold = _quantize_quantity(low_stock_threshold)

        item = InventoryItem(
            name=name,
            category=category,
            unit=unit,
            low_stock_threshold=low_stock_threshold,
            main_stock_level=Decimal("0.00"),
            emergency_stock_level=Decimal("0.00"),
            is_active=True,
            created_by=actor.id,
            updated_by=actor.id,
        )
        await self._item_repo.add(item)
        await self._audit_repo.record(
            module="inventory",
            action="inventory.item_created",
            entity_type="inventory_item",
            entity_id=item.id,
            actor_user_id=actor.id,
            metadata={"name": name, "category": category.value, "unit": unit.value},
        )
        await self._session.commit()
        return await self._get_item(item.id)

    async def _get_item(self, item_id: UUID) -> InventoryItem:
        item = await self._item_repo.get_by_id(item_id)
        if item is None:
            raise InventoryItemNotFoundError
        return item

    async def get_item(self, item_id: UUID) -> InventoryItem:
        return await self._get_item(item_id)

    async def update_item(self, *, actor: User, item_id: UUID, updates: dict) -> InventoryItem:
        """Partial update — `updates` comes from
        `UpdateInventoryItemRequest.model_dump(exclude_unset=True)`, the
        same `exclude_unset` semantics every other PATCH endpoint in
        this codebase relies on. Category/unit compatibility is
        re-validated against the *resulting* combination (see
        `models.CATEGORY_ALLOWED_UNITS`'s own docstring for why this
        can only happen here, never in the request schema)."""
        item = await self._get_item(item_id)
        if not updates:
            return item

        for field in ("name", "category", "unit", "low_stock_threshold", "is_active"):
            if field in updates:
                value = updates[field]
                if field == "low_stock_threshold" and value is not None:
                    value = _quantize_quantity(value)
                setattr(item, field, value)

        if "category" in updates or "unit" in updates:
            self._validate_category_unit(item.category, item.unit)

        item.updated_by = actor.id
        await self._item_repo.add(item)
        await self._audit_repo.record(
            module="inventory",
            action="inventory.item_updated",
            entity_type="inventory_item",
            entity_id=item.id,
            actor_user_id=actor.id,
            metadata={"fields": sorted(updates.keys())},
        )
        await self._session.commit()
        return await self._get_item(item.id)

    async def search_items(self, *, search: str, limit: int = 20) -> list[InventoryItem]:
        return await self._item_repo.search_active(search=search, limit=limit)

    async def list_items(
        self,
        *,
        search: str | None,
        category: str | None,
        low_stock_only: bool,
        sort_by: str,
        sort_desc: bool,
        page: int,
        page_size: int,
    ) -> tuple[list[InventoryItem], int]:
        sort_column = INVENTORY_ITEM_SORTABLE_COLUMNS[sort_by]
        return await self._item_repo.list_all(
            search=search,
            category=category,
            low_stock_only=low_stock_only,
            sort_column=sort_column,
            sort_desc=sort_desc,
            limit=page_size,
            offset=(page - 1) * page_size,
        )

    async def count_low_stock(self) -> int:
        return await self._item_repo.count_low_stock()

    # ------------------------------------------------------------------
    # Main Stock receipts (Inventory Manager only, inventory:manage)
    # ------------------------------------------------------------------

    async def receive_stock(
        self, *, actor: User, item_id: UUID, quantity: Decimal, received_on: date_type
    ) -> InventoryItem:
        if quantity <= 0:
            raise ValidationError("Quantity must be greater than zero.")
        quantity = _quantize_quantity(quantity)

        item = await self._item_repo.get_for_update(item_id)
        if item is None:
            raise InventoryItemNotFoundError
        if not item.is_active:
            raise InventoryItemInactiveError(item.name)

        item.main_stock_level = item.main_stock_level + quantity
        item.updated_by = actor.id
        await self._item_repo.add(item)
        await self._receipt_repo.add(
            InventoryMainStockReceipt(
                item_id=item.id,
                quantity=quantity,
                received_on=received_on,
                created_by=actor.id,
                updated_by=actor.id,
            )
        )
        await self._audit_repo.record(
            module="inventory",
            action="inventory.stock_received",
            entity_type="inventory_item",
            entity_id=item.id,
            actor_user_id=actor.id,
            metadata={"quantity": str(quantity), "received_on": received_on.isoformat()},
        )
        await self._session.commit()
        return await self._get_item(item.id)

    async def receive_stock_batch(
        self,
        *,
        actor: User,
        items: list[tuple[UUID, Decimal]],
        received_on: date_type,
    ) -> list[InventoryItem]:
        """Batch Main Stock receiving (2026-09 addition, the checklist-
        entry redesign) — `items` is a list of `(item_id, quantity)`
        pairs, already validated non-empty by `ReceiveStockBatchRequest`,
        one `received_on` shared across the whole batch, committed
        atomically together. The exact same "sequential lock/increment/
        insert, one commit, no partial batch ever lands" shape
        `transfer_to_emergency`'s own docstring establishes — including
        why two lines naming the same item correctly stack against each
        other's stock delta (both run against the same locked, identity-
        mapped `InventoryItem` row within this one transaction).

        Deliberately a *new*, additional method — the original single-
        item `receive_stock` above is untouched, still backing its own
        `POST /items/{item_id}/receive` endpoint unchanged, rather than
        being widened/replaced the way `transfer_to_emergency`/
        `record_usage` fully replaced their own single-item predecessors
        when *they* got batched: those two had no other caller left to
        break, while `receive_stock` is exercised directly by a large
        share of this module's own existing test suite as ordinary setup
        — replacing it here would mean rewriting all of that for a UI-
        only redesign, a disproportionate blast radius for no behavioral
        gain. The frontend's own Receive Stock screen calls this batch
        method exclusively going forward."""
        updated_items: list[InventoryItem] = []
        for item_id, quantity in items:
            if quantity <= 0:
                raise ValidationError("Quantity must be greater than zero.")
            quantity = _quantize_quantity(quantity)

            item = await self._item_repo.get_for_update(item_id)
            if item is None:
                raise InventoryItemNotFoundError
            if not item.is_active:
                raise InventoryItemInactiveError(item.name)

            item.main_stock_level = item.main_stock_level + quantity
            item.updated_by = actor.id
            await self._item_repo.add(item)
            await self._receipt_repo.add(
                InventoryMainStockReceipt(
                    item_id=item.id,
                    quantity=quantity,
                    received_on=received_on,
                    created_by=actor.id,
                    updated_by=actor.id,
                )
            )
            await self._audit_repo.record(
                module="inventory",
                action="inventory.stock_received",
                entity_type="inventory_item",
                entity_id=item.id,
                actor_user_id=actor.id,
                metadata={"quantity": str(quantity), "received_on": received_on.isoformat()},
            )
            updated_items.append(item)

        await self._session.commit()
        return [await self._get_item(item.id) for item in updated_items]

    # ------------------------------------------------------------------
    # Direct-to-Emergency receipts (Inventory Manager only, inventory:manage)
    # ------------------------------------------------------------------

    async def receive_directly_to_emergency(
        self,
        *,
        actor: User,
        items: list[tuple[UUID, Decimal]],
        received_on: date_type,
    ) -> list[InventoryItem]:
        """The real-world-shaped receiving path (2026-09 addition) — see
        this module's own top-level docstring and `InventoryEmergencyDirectReceipt`'s
        docstring for why this exists alongside, not instead of,
        `receive_stock`/`receive_stock_batch`. Same batch shape as
        `transfer_to_emergency`/`receive_stock_batch`: `items` is a list
        of `(item_id, quantity)` pairs, one `received_on` shared across
        the batch, committed atomically together.

        Auto-resolves restock requests (see `InventoryRestockRequest.
        fulfilled_by_direct_receipt_id`'s own docstring for the full
        "why auto-resolve, not an explicit per-item request link"
        reasoning): every currently-PENDING request against an item is
        marked FULFILLED the moment a direct receipt lands for that
        item, in the same transaction, with no request_id the caller
        must supply. Lock order per line is request(s)-then-item —
        deliberately matching `fulfill_request`'s own documented lock
        order (request row before item row) so this method can never
        deadlock against a concurrent `fulfill_request`/`reject_request`
        call on the same request."""
        updated_items: list[InventoryItem] = []
        for item_id, quantity in items:
            if quantity <= 0:
                raise ValidationError("Quantity must be greater than zero.")
            quantity = _quantize_quantity(quantity)

            # Locked before the item row, matching fulfill_request's own
            # documented lock order — see this method's own docstring.
            pending_requests = await self._request_repo.list_pending_for_item(item_id)

            item = await self._item_repo.get_for_update(item_id)
            if item is None:
                raise InventoryItemNotFoundError
            if not item.is_active:
                raise InventoryItemInactiveError(item.name)

            item.emergency_stock_level = item.emergency_stock_level + quantity
            item.updated_by = actor.id
            await self._item_repo.add(item)

            receipt = InventoryEmergencyDirectReceipt(
                item_id=item.id,
                quantity=quantity,
                received_on=received_on,
                created_by=actor.id,
                updated_by=actor.id,
            )
            await self._emergency_direct_receipt_repo.add(receipt)
            await self._audit_repo.record(
                module="inventory",
                action="inventory.received_directly_to_emergency",
                entity_type="inventory_item",
                entity_id=item.id,
                actor_user_id=actor.id,
                metadata={"quantity": str(quantity), "received_on": received_on.isoformat()},
            )

            resolved_at = datetime.now(UTC)
            for request in pending_requests:
                request.status = InventoryRestockRequestStatus.FULFILLED
                request.fulfilled_by_direct_receipt_id = receipt.id
                request.resolved_by = actor.id
                request.resolved_at = resolved_at
                request.updated_by = actor.id
                await self._request_repo.add(request)
                await self._audit_repo.record(
                    module="inventory",
                    action="inventory.restock_request_fulfilled",
                    entity_type="inventory_restock_request",
                    entity_id=request.id,
                    actor_user_id=actor.id,
                    metadata={
                        "direct_receipt_id": str(receipt.id),
                        "quantity": str(quantity),
                    },
                )

            updated_items.append(item)

        await self._session.commit()
        return [await self._get_item(item.id) for item in updated_items]

    # ------------------------------------------------------------------
    # Transfers (Inventory Manager only, inventory:manage)
    # ------------------------------------------------------------------

    async def _transfer_locked(
        self,
        *,
        actor: User,
        item: InventoryItem,
        quantity: Decimal,
        transferred_on: date_type,
        carried_by_name: str,
    ) -> InventoryTransfer:
        """Assumes `item` was already fetched with `get_for_update` by
        the caller (`transfer_to_emergency` or `fulfill_request`, which
        additionally needs the request row locked first) — never calls
        `get_for_update` itself, so callers control lock ordering."""
        if item.main_stock_level < quantity:
            raise InsufficientMainStockError(item.main_stock_level)

        item.main_stock_level = item.main_stock_level - quantity
        item.emergency_stock_level = item.emergency_stock_level + quantity
        item.updated_by = actor.id
        await self._item_repo.add(item)
        transfer = InventoryTransfer(
            item_id=item.id,
            quantity=quantity,
            transferred_on=transferred_on,
            carried_by_name=carried_by_name,
            created_by=actor.id,
            updated_by=actor.id,
        )
        await self._transfer_repo.add(transfer)
        await self._audit_repo.record(
            module="inventory",
            action="inventory.transferred_to_emergency",
            entity_type="inventory_item",
            entity_id=item.id,
            actor_user_id=actor.id,
            metadata={
                "quantity": str(quantity),
                "transferred_on": transferred_on.isoformat(),
                "carried_by_name": carried_by_name,
            },
        )
        return transfer

    async def transfer_to_emergency(
        self,
        *,
        actor: User,
        items: list[tuple[UUID, Decimal]],
        transferred_on: date_type,
        carried_by_name: str,
    ) -> list[InventoryItem]:
        """`items` is a list of `(item_id, quantity)` pairs, already
        validated non-empty by `TransferStockRequest` — one
        `transferred_on`/`carried_by_name` shared across the whole
        batch, submitted and committed atomically together (2026-08-28
        addition; a single-item call used to be the only shape, same
        batch extension `record_usage` got — see that method's own
        docstring for the identical "sequential lock/decrement/insert,
        one commit, no partial batch ever lands" rationale, including
        why two lines naming the same item correctly stack against each
        other's stock delta)."""
        updated_items: list[InventoryItem] = []
        for item_id, quantity in items:
            if quantity <= 0:
                raise ValidationError("Quantity must be greater than zero.")
            quantity = _quantize_quantity(quantity)

            item = await self._item_repo.get_for_update(item_id)
            if item is None:
                raise InventoryItemNotFoundError
            if not item.is_active:
                raise InventoryItemInactiveError(item.name)

            await self._transfer_locked(
                actor=actor,
                item=item,
                quantity=quantity,
                transferred_on=transferred_on,
                carried_by_name=carried_by_name,
            )
            updated_items.append(item)

        await self._session.commit()
        return [await self._get_item(item.id) for item in updated_items]

    # ------------------------------------------------------------------
    # Usage entries (Vitals only, inventory:record_usage)
    # ------------------------------------------------------------------

    async def record_usage(
        self,
        *,
        actor: User,
        items: list[tuple[UUID, Decimal, str | None]],
        used_on: date_type,
        patient_id: UUID | None,
        manual_patient_name: str | None,
        manual_patient_age: int | None,
        manual_patient_phone: str | None,
    ) -> list[InventoryUsageEntry]:
        """`items` is a list of `(item_id, quantity, reason_note)`
        triples, already validated non-empty by `RecordUsageRequest` —
        one patient context (linked or manual) shared by every line,
        same "fixed context, items added one at a time" shape
        `RegisterVisitForm` uses for procedures (2026-08-27 batch
        addition; a single-item call used to be the only shape).

        This does **not** introduce a batch/session parent entity —
        every line still becomes its own fully independent
        `InventoryUsageEntry` row (see models.py's docstring for why),
        just written atomically: one row per line is locked/decremented/
        inserted in order (so two lines naming the *same* item
        correctly stack against each other's stock delta, since both
        run against the same locked, identity-mapped `InventoryItem`
        row within this one transaction), and if any line fails
        validation the whole batch raises before the single commit at
        the end ever runs — no partial usage ever lands, the same
        all-or-nothing discipline `PharmacyService.create_bill` follows
        for its own `items` list.

        `patient_id` is mutually exclusive with the three manual
        fields, all-or-nothing when used — validated here (never in the
        request schema), the identical convention `PharmacyService.
        create_bill` already follows for its own `visit_id`/manual-field
        split; see models.py's `InventoryUsageEntry` docstring for the
        full rationale and the DB-level CHECK constraints that also
        enforce these two rules."""
        manual_fields = (manual_patient_name, manual_patient_age, manual_patient_phone)
        any_manual_field = any(field is not None for field in manual_fields)
        all_manual_fields = all(field is not None for field in manual_fields)
        if any_manual_field and not all_manual_fields:
            raise InventoryUsageManualPatientFieldsIncompleteError
        if any_manual_field and patient_id is not None:
            raise InventoryUsageManualPatientConflictsWithPatientError
        if manual_patient_name is not None:
            manual_patient_name = manual_patient_name.strip()
        if manual_patient_phone is not None:
            manual_patient_phone = manual_patient_phone.strip()

        if patient_id is not None:
            await self._patient_service.get_patient(patient_id)

        created_entries: list[InventoryUsageEntry] = []
        for item_id, quantity, reason_note in items:
            if quantity <= 0:
                raise ValidationError("Quantity must be greater than zero.")
            quantity = _quantize_quantity(quantity)

            item = await self._item_repo.get_for_update(item_id)
            if item is None:
                raise InventoryItemNotFoundError
            if not item.is_active:
                raise InventoryItemInactiveError(item.name)
            if item.emergency_stock_level < quantity:
                raise InsufficientEmergencyStockError(item.emergency_stock_level)

            item.emergency_stock_level = item.emergency_stock_level - quantity
            item.updated_by = actor.id
            await self._item_repo.add(item)

            entry = InventoryUsageEntry(
                item_id=item.id,
                quantity=quantity,
                used_on=used_on,
                patient_id=patient_id,
                manual_patient_name=manual_patient_name,
                manual_patient_age=manual_patient_age,
                manual_patient_phone=manual_patient_phone,
                reason_note=reason_note.strip() if reason_note else None,
                created_by=actor.id,
                updated_by=actor.id,
            )
            await self._usage_repo.add(entry)
            created_entries.append(entry)

        for entry in created_entries:
            await self._audit_repo.record(
                module="inventory",
                action="inventory.usage_recorded",
                entity_type="inventory_usage_entry",
                entity_id=entry.id,
                actor_user_id=actor.id,
                metadata={
                    "item_id": str(entry.item_id),
                    "quantity": str(entry.quantity),
                    "patient_id": str(patient_id) if patient_id else None,
                    "manual_patient_name": manual_patient_name,
                },
            )

        await self._session.commit()
        return [await self._usage_repo.get_by_id(entry.id) for entry in created_entries]

    async def get_patient_context(self, patient_id: UUID) -> tuple[Patient, Visit | None]:
        """Backs the usage-entry screen's read-only "MR number +
        registered procedure" preview once a patient is picked — never
        stored on the usage entry itself, purely a display convenience.
        Reuses `VisitService.list_visits`'s existing `patient_id` filter
        (already public, already used by `VitalsService.
        get_latest_for_patient` for the identical "this patient's most
        recent visit" lookup) rather than adding a new method to Visits
        — no visit-module change needed for this at all. Returns
        `(patient, None)` when the patient has no visit on file yet, a
        normal outcome for the ward/emergency population this module is
        built for, never an error."""
        patient = await self._patient_service.get_patient(patient_id)
        visits, _total = await self._visit_service.list_visits(
            patient_id=patient_id,
            doctor_user_id=None,
            unassigned_only=False,
            status=None,
            sort_by="created_at",
            sort_desc=True,
            page=1,
            page_size=1,
        )
        latest_visit = visits[0] if visits else None
        return patient, latest_visit

    # ------------------------------------------------------------------
    # Restock requests
    # ------------------------------------------------------------------

    async def raise_restock_request(
        self,
        *,
        actor: User,
        item_id: UUID,
        requested_quantity: Decimal | None,
        note: str | None,
    ) -> InventoryRestockRequest:
        item = await self._get_item(item_id)
        if requested_quantity is not None:
            if requested_quantity <= 0:
                raise ValidationError("Requested quantity must be greater than zero.")
            requested_quantity = _quantize_quantity(requested_quantity)

        request = InventoryRestockRequest(
            item_id=item.id,
            requested_quantity=requested_quantity,
            note=note.strip() if note else None,
            status=InventoryRestockRequestStatus.PENDING,
            created_by=actor.id,
            updated_by=actor.id,
        )
        await self._request_repo.add(request)
        await self._audit_repo.record(
            module="inventory",
            action="inventory.restock_requested",
            entity_type="inventory_restock_request",
            entity_id=request.id,
            actor_user_id=actor.id,
            metadata={
                "item_id": str(item.id),
                "requested_quantity": str(requested_quantity) if requested_quantity else None,
            },
        )
        await self._session.commit()
        return await self._request_repo.get_by_id(request.id)

    async def list_requests(
        self, *, status: InventoryRestockRequestStatus | None, page: int, page_size: int
    ) -> tuple[list[InventoryRestockRequest], int]:
        return await self._request_repo.list_all(
            status=status, limit=page_size, offset=(page - 1) * page_size
        )

    async def count_pending_requests(self) -> int:
        return await self._request_repo.count_pending()

    async def _get_request_for_update(self, request_id: UUID) -> InventoryRestockRequest:
        request = await self._request_repo.get_for_update(request_id)
        if request is None:
            raise InventoryRestockRequestNotFoundError
        return request

    async def fulfill_request(
        self,
        *,
        actor: User,
        request_id: UUID,
        transfer_quantity: Decimal,
        transferred_on: date_type,
        carried_by_name: str,
    ) -> InventoryRestockRequest:
        """Fulfilling a request *performs* the transfer (pre-filled from
        the request's own `item_id`, but the Inventory Manager may send
        a different quantity than originally requested — `note`'s "just
        flag it low" case has no number to default to at all). Locks the
        request row first, then the item row — a consistent lock order
        with `reject_request` (which locks only the request) and every
        other item-locking method (which never also locks a request),
        so no cross-method lock-ordering cycle can occur. `carried_by_name`
        is required here too — see `InventoryTransfer.carried_by_name`'s
        own docstring for why this path needs it just as much as a
        manually-initiated transfer."""
        if transfer_quantity <= 0:
            raise ValidationError("Transfer quantity must be greater than zero.")
        transfer_quantity = _quantize_quantity(transfer_quantity)

        request = await self._get_request_for_update(request_id)
        if request.status != InventoryRestockRequestStatus.PENDING:
            raise InventoryRestockRequestNotPendingError(request.status.value)

        item = await self._item_repo.get_for_update(request.item_id)
        if item is None:
            raise InventoryItemNotFoundError
        if not item.is_active:
            raise InventoryItemInactiveError(item.name)

        transfer = await self._transfer_locked(
            actor=actor,
            item=item,
            quantity=transfer_quantity,
            transferred_on=transferred_on,
            carried_by_name=carried_by_name,
        )

        request.status = InventoryRestockRequestStatus.FULFILLED
        request.fulfilled_by_transfer_id = transfer.id
        request.resolved_by = actor.id
        request.resolved_at = datetime.now(UTC)
        request.updated_by = actor.id
        await self._request_repo.add(request)
        await self._audit_repo.record(
            module="inventory",
            action="inventory.restock_request_fulfilled",
            entity_type="inventory_restock_request",
            entity_id=request.id,
            actor_user_id=actor.id,
            metadata={"transfer_id": str(transfer.id), "quantity": str(transfer_quantity)},
        )
        await self._session.commit()
        return await self._request_repo.get_by_id(request.id)

    async def reject_request(
        self, *, actor: User, request_id: UUID, rejection_reason: str | None
    ) -> InventoryRestockRequest:
        request = await self._get_request_for_update(request_id)
        if request.status != InventoryRestockRequestStatus.PENDING:
            raise InventoryRestockRequestNotPendingError(request.status.value)

        request.status = InventoryRestockRequestStatus.REJECTED
        request.rejection_reason = rejection_reason.strip() if rejection_reason else None
        request.resolved_by = actor.id
        request.resolved_at = datetime.now(UTC)
        request.updated_by = actor.id
        await self._request_repo.add(request)
        await self._audit_repo.record(
            module="inventory",
            action="inventory.restock_request_rejected",
            entity_type="inventory_restock_request",
            entity_id=request.id,
            actor_user_id=actor.id,
            metadata={"rejection_reason": request.rejection_reason},
        )
        await self._session.commit()
        return await self._request_repo.get_by_id(request.id)

    # ------------------------------------------------------------------
    # History (Admin + Inventory Manager visibility, inventory:read)
    # ------------------------------------------------------------------

    async def list_receipts(
        self,
        *,
        item_id: UUID | None,
        start_date: date_type | None,
        end_date: date_type | None,
        page: int,
        page_size: int,
    ) -> tuple[list[InventoryMainStockReceipt], int]:
        return await self._receipt_repo.list_for_range(
            item_id=item_id,
            start_date=start_date,
            end_date=end_date,
            limit=page_size,
            offset=(page - 1) * page_size,
        )

    async def list_emergency_direct_receipts(
        self,
        *,
        item_id: UUID | None,
        start_date: date_type | None,
        end_date: date_type | None,
        page: int,
        page_size: int,
    ) -> tuple[list[InventoryEmergencyDirectReceipt], int]:
        return await self._emergency_direct_receipt_repo.list_for_range(
            item_id=item_id,
            start_date=start_date,
            end_date=end_date,
            limit=page_size,
            offset=(page - 1) * page_size,
        )

    async def list_transfers(
        self,
        *,
        item_id: UUID | None,
        start_date: date_type | None,
        end_date: date_type | None,
        page: int,
        page_size: int,
    ) -> tuple[list[InventoryTransfer], int]:
        return await self._transfer_repo.list_for_range(
            item_id=item_id,
            start_date=start_date,
            end_date=end_date,
            limit=page_size,
            offset=(page - 1) * page_size,
        )

    async def list_usage_entries(
        self,
        *,
        item_id: UUID | None,
        created_by: UUID | None,
        start_date: date_type | None,
        end_date: date_type | None,
        page: int,
        page_size: int,
    ) -> tuple[list[InventoryUsageEntry], int]:
        return await self._usage_repo.list_for_range(
            item_id=item_id,
            created_by=created_by,
            start_date=start_date,
            end_date=end_date,
            limit=page_size,
            offset=(page - 1) * page_size,
        )

    async def list_usage_for_creator_and_day(
        self, *, created_by: UUID, day: datetime
    ) -> list[InventoryUsageEntry]:
        """The Vitals daily usage slip's source query — see
        `InventoryUsageEntryRepository.list_for_creator_and_day`."""
        return await self._usage_repo.list_for_creator_and_day(created_by=created_by, day=day)

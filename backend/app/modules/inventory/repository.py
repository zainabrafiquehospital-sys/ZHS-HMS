"""Persistence-only repositories for the Inventory module — see
app/modules/patients/repository.py's identical module docstring for the
"persistence only, no policy" rationale."""

from datetime import date as date_type
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import InstrumentedAttribute

from app.modules.inventory.models import (
    InventoryItem,
    InventoryMainStockReceipt,
    InventoryRestockRequest,
    InventoryRestockRequestStatus,
    InventoryTransfer,
    InventoryUsageEntry,
)
from app.shared.repository.base_repository import BaseRepository

# Whitelist of columns InventoryItemRepository.list_all may sort by —
# never accept a raw column/attribute name from a caller, same rationale
# as app/modules/pharmacy/repository.py's MEDICINE_SORTABLE_COLUMNS.
INVENTORY_ITEM_SORTABLE_COLUMNS: dict[str, InstrumentedAttribute] = {
    "created_at": InventoryItem.created_at,
    "name": InventoryItem.name,
}


class InventoryItemRepository(BaseRepository[InventoryItem]):
    model = InventoryItem

    async def get_for_update(self, item_id: UUID) -> InventoryItem | None:
        """Row-locking variant of `get_by_id` — every stock-level
        mutation (a receipt, a transfer, a usage entry) reads the item
        through this, never the plain `get_by_id`, identical rationale
        to `InvoiceRepository.get_for_update`/`MedicineBillRepository.
        get_for_update`: two concurrent writes against the same item's
        stock levels must never both compute their "current level" from
        the same stale snapshot."""
        stmt = self._exclude_soft_deleted(
            select(InventoryItem).where(InventoryItem.id == item_id), include_deleted=False
        ).with_for_update()
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def search_active(self, *, search: str, limit: int) -> list[InventoryItem]:
        """Backs the Vitals usage-entry item picker's autocomplete —
        active items only, case-insensitive partial name match, same
        `ILIKE` pattern as `MedicineRepository.search_active`."""
        pattern = f"%{search}%"
        stmt = self._exclude_soft_deleted(
            select(InventoryItem)
            .where(InventoryItem.is_active.is_(True), InventoryItem.name.ilike(pattern))
            .order_by(InventoryItem.name.asc())
            .limit(limit),
            include_deleted=False,
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_all(
        self,
        *,
        search: str | None,
        category: str | None,
        low_stock_only: bool,
        sort_column: InstrumentedAttribute,
        sort_desc: bool,
        limit: int,
        offset: int,
    ) -> tuple[list[InventoryItem], int]:
        """Backs the Inventory Manager/Admin catalog listing — every
        item, active and inactive alike (mirrors `MedicineRepository.
        list_all`'s identical "deactivated stays visible" rationale).
        `low_stock_only` filters to items with a configured threshold
        currently at or below it — computed live, never a stored flag
        (see `InventoryItem`'s own docstring)."""
        conditions = [InventoryItem.deleted_at.is_(None)]
        if search:
            conditions.append(InventoryItem.name.ilike(f"%{search}%"))
        if category:
            conditions.append(InventoryItem.category == category)
        if low_stock_only:
            conditions.append(InventoryItem.low_stock_threshold.is_not(None))
            conditions.append(
                InventoryItem.emergency_stock_level <= InventoryItem.low_stock_threshold
            )

        stmt = select(InventoryItem).where(*conditions)
        total = (
            await self.session.execute(select(func.count()).select_from(stmt.subquery()))
        ).scalar_one()

        order_column = sort_column.desc() if sort_desc else sort_column.asc()
        stmt = stmt.order_by(order_column, InventoryItem.id).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total

    async def count_low_stock(self) -> int:
        """Backs the Admin Overview / Inventory Manager dashboard's
        low-stock count badge — a single scalar, not a full listing."""
        stmt = select(func.count()).where(
            InventoryItem.deleted_at.is_(None),
            InventoryItem.is_active.is_(True),
            InventoryItem.low_stock_threshold.is_not(None),
            InventoryItem.emergency_stock_level <= InventoryItem.low_stock_threshold,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one()


class InventoryMainStockReceiptRepository(BaseRepository[InventoryMainStockReceipt]):
    model = InventoryMainStockReceipt

    async def list_for_range(
        self,
        *,
        item_id: UUID | None,
        start_date: date_type | None,
        end_date: date_type | None,
        limit: int,
        offset: int,
    ) -> tuple[list[InventoryMainStockReceipt], int]:
        conditions = [InventoryMainStockReceipt.deleted_at.is_(None)]
        if item_id is not None:
            conditions.append(InventoryMainStockReceipt.item_id == item_id)
        if start_date is not None:
            conditions.append(InventoryMainStockReceipt.received_on >= start_date)
        if end_date is not None:
            conditions.append(InventoryMainStockReceipt.received_on <= end_date)

        stmt = select(InventoryMainStockReceipt).where(*conditions)
        total = (
            await self.session.execute(select(func.count()).select_from(stmt.subquery()))
        ).scalar_one()
        stmt = (
            stmt.order_by(InventoryMainStockReceipt.created_at.desc()).limit(limit).offset(offset)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total


class InventoryTransferRepository(BaseRepository[InventoryTransfer]):
    model = InventoryTransfer

    async def list_for_range(
        self,
        *,
        item_id: UUID | None,
        start_date: date_type | None,
        end_date: date_type | None,
        limit: int,
        offset: int,
    ) -> tuple[list[InventoryTransfer], int]:
        """Backs both the Inventory Manager's/Admin's transfer history
        screen and the printable transfer log — the same query, the
        print endpoint just requests a wider page."""
        conditions = [InventoryTransfer.deleted_at.is_(None)]
        if item_id is not None:
            conditions.append(InventoryTransfer.item_id == item_id)
        if start_date is not None:
            conditions.append(InventoryTransfer.transferred_on >= start_date)
        if end_date is not None:
            conditions.append(InventoryTransfer.transferred_on <= end_date)

        stmt = select(InventoryTransfer).where(*conditions)
        total = (
            await self.session.execute(select(func.count()).select_from(stmt.subquery()))
        ).scalar_one()
        stmt = stmt.order_by(InventoryTransfer.created_at.desc()).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total


class InventoryUsageEntryRepository(BaseRepository[InventoryUsageEntry]):
    model = InventoryUsageEntry

    async def list_for_range(
        self,
        *,
        item_id: UUID | None,
        created_by: UUID | None,
        start_date: date_type | None,
        end_date: date_type | None,
        limit: int,
        offset: int,
    ) -> tuple[list[InventoryUsageEntry], int]:
        """Backs the usage history screen (Admin/Inventory Manager
        visibility) and, filtered to one `created_by` + one day, the
        Vitals daily usage slip (see `list_for_creator_and_day` below,
        which reuses this same shape unpaginated)."""
        conditions = [InventoryUsageEntry.deleted_at.is_(None)]
        if item_id is not None:
            conditions.append(InventoryUsageEntry.item_id == item_id)
        if created_by is not None:
            conditions.append(InventoryUsageEntry.created_by == created_by)
        if start_date is not None:
            conditions.append(InventoryUsageEntry.used_on >= start_date)
        if end_date is not None:
            conditions.append(InventoryUsageEntry.used_on <= end_date)

        stmt = select(InventoryUsageEntry).where(*conditions)
        total = (
            await self.session.execute(select(func.count()).select_from(stmt.subquery()))
        ).scalar_one()
        stmt = stmt.order_by(InventoryUsageEntry.created_at.desc()).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total

    async def list_for_creator_and_day(
        self, *, created_by: UUID, day: datetime
    ) -> list[InventoryUsageEntry]:
        """Every usage entry `created_by` personally recorded on `day`'s
        UTC calendar date, oldest first — the exact `list_for_day` shape
        `MedicineBillRepository`/`InvoiceRepository` already use for
        their own day-scoped Admin Overview queries, scoped to one
        creator for the Vitals daily usage slip specifically."""
        start_of_day = datetime(day.year, day.month, day.day, tzinfo=day.tzinfo)
        end_of_day = start_of_day + timedelta(days=1)
        stmt = self._exclude_soft_deleted(
            select(InventoryUsageEntry)
            .where(
                InventoryUsageEntry.created_by == created_by,
                InventoryUsageEntry.created_at >= start_of_day,
                InventoryUsageEntry.created_at < end_of_day,
            )
            .order_by(InventoryUsageEntry.created_at.asc()),
            include_deleted=False,
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class InventoryRestockRequestRepository(BaseRepository[InventoryRestockRequest]):
    model = InventoryRestockRequest

    async def get_for_update(self, request_id: UUID) -> InventoryRestockRequest | None:
        """Row-locking variant of `get_by_id`, for `InventoryService.
        fulfill_request`/`reject_request`'s read-modify-write — two
        concurrent resolutions of the same request must never both
        pass the `status == PENDING` check from the same stale
        snapshot, identical rationale to every other `get_for_update`
        in this module."""
        stmt = self._exclude_soft_deleted(
            select(InventoryRestockRequest).where(InventoryRestockRequest.id == request_id),
            include_deleted=False,
        ).with_for_update()
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_all(
        self,
        *,
        status: InventoryRestockRequestStatus | None,
        limit: int,
        offset: int,
    ) -> tuple[list[InventoryRestockRequest], int]:
        """Newest-pending-first ordering when filtered to `PENDING`
        (the worklist's own natural order — oldest unresolved request
        first); newest-first otherwise (a general history view)."""
        conditions = [InventoryRestockRequest.deleted_at.is_(None)]
        if status is not None:
            conditions.append(InventoryRestockRequest.status == status)

        stmt = select(InventoryRestockRequest).where(*conditions)
        total = (
            await self.session.execute(select(func.count()).select_from(stmt.subquery()))
        ).scalar_one()

        order_column = (
            InventoryRestockRequest.created_at.asc()
            if status == InventoryRestockRequestStatus.PENDING
            else InventoryRestockRequest.created_at.desc()
        )
        stmt = stmt.order_by(order_column).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total

    async def count_pending(self) -> int:
        """Backs Admin Overview's "Pending Requests" indicator — a
        single scalar, mirroring `PendingApprovals`'s own count query
        shape for user signups."""
        stmt = select(func.count()).where(
            InventoryRestockRequest.deleted_at.is_(None),
            InventoryRestockRequest.status == InventoryRestockRequestStatus.PENDING,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one()

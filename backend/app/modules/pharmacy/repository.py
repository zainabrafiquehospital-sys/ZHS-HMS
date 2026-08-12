"""Persistence-only repositories for the Pharmacy module — see
app/modules/patients/repository.py's identical module docstring for the
"persistence only, no policy" rationale."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import InstrumentedAttribute

from app.modules.pharmacy.models import Medicine, MedicineBill, MedicineBillItem, MedicineBillPayment
from app.shared.repository.base_repository import BaseRepository

# Whitelist of columns MedicineRepository.list_all may sort by — never
# accept a raw column/attribute name from a caller, same rationale as
# app/modules/patients/repository.py's PATIENT_SORTABLE_COLUMNS.
MEDICINE_SORTABLE_COLUMNS: dict[str, InstrumentedAttribute] = {
    "created_at": Medicine.created_at,
    "name": Medicine.name,
}


class MedicineRepository(BaseRepository[Medicine]):
    model = Medicine

    async def search_active(self, *, search: str, limit: int) -> list[Medicine]:
        """Backs the receptionist-facing autocomplete (`GET
        /pharmacy/medicines/search`) — active medicines only, case-
        insensitive partial name match, same `ILIKE` pattern as
        app/modules/patients/repository.py's `search`."""
        pattern = f"%{search}%"
        stmt = self._exclude_soft_deleted(
            select(Medicine)
            .where(Medicine.is_active.is_(True), Medicine.name.ilike(pattern))
            .order_by(Medicine.name.asc())
            .limit(limit),
            include_deleted=False,
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_all(
        self,
        *,
        search: str | None,
        sort_column: InstrumentedAttribute,
        sort_desc: bool,
        limit: int,
        offset: int,
    ) -> tuple[list[Medicine], int]:
        """Backs the admin management screen (`GET /pharmacy/medicines`)
        — every medicine, active and inactive alike, so a deactivated
        entry stays visible and re-activatable there."""
        conditions = [Medicine.deleted_at.is_(None)]
        if search:
            conditions.append(Medicine.name.ilike(f"%{search}%"))

        stmt = select(Medicine).where(*conditions)
        total = (
            await self.session.execute(select(func.count()).select_from(stmt.subquery()))
        ).scalar_one()

        order_column = sort_column.desc() if sort_desc else sort_column.asc()
        stmt = stmt.order_by(order_column, Medicine.id).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total


class MedicineBillRepository(BaseRepository[MedicineBill]):
    model = MedicineBill

    async def get_for_update(self, medicine_bill_id: UUID) -> MedicineBill | None:
        """Row-locking variant of `get_by_id`, for `PharmacyService.
        record_payment`'s read-modify-write — identical rationale to
        app/modules/billing/repository.py's `InvoiceRepository.
        get_for_update`: two concurrent payments against the same bill
        must never both compute their "amount paid so far" from the
        same stale snapshot."""
        stmt = self._exclude_soft_deleted(
            select(MedicineBill).where(MedicineBill.id == medicine_bill_id), include_deleted=False
        ).with_for_update()
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_for_day(self, day: datetime) -> list[MedicineBill]:
        """Every medicine bill created on `day`'s UTC calendar date — the
        Admin Overview's Medicine Bills tab, the same UTC-calendar-day
        window `InvoiceRepository.get_today_summary` uses (see
        app/modules/billing/repository.py's identical documented
        simplification: a hospital deployment outside UTC would want
        this computed against local time)."""
        start_of_day = datetime(day.year, day.month, day.day, tzinfo=UTC)
        end_of_day = start_of_day + timedelta(days=1)
        stmt = self._exclude_soft_deleted(
            select(MedicineBill)
            .where(MedicineBill.created_at >= start_of_day, MedicineBill.created_at < end_of_day)
            .order_by(MedicineBill.created_at.asc()),
            include_deleted=False,
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class MedicineBillItemRepository(BaseRepository[MedicineBillItem]):
    model = MedicineBillItem

    async def list_for_bill(self, medicine_bill_id: UUID) -> list[MedicineBillItem]:
        stmt = self._exclude_soft_deleted(
            select(MedicineBillItem)
            .where(MedicineBillItem.medicine_bill_id == medicine_bill_id)
            .order_by(MedicineBillItem.created_at.asc()),
            include_deleted=False,
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count_items_for_bills(self, medicine_bill_ids: list[UUID]) -> dict[UUID, int]:
        """One `GROUP BY` query for every given bill's line-item count —
        backs the Admin Overview's Medicine Bills tab (`GET
        /pharmacy/bills?date=`), not one query per bill (the same N+1
        avoidance as app/modules/visits/repository.py's
        `count_by_status`). Bills with zero matching rows (impossible in
        practice — `PharmacyService.create_bill` rejects an empty item
        list — but never assumed) simply have no entry in the returned
        dict; callers should default to 0."""
        if not medicine_bill_ids:
            return {}
        stmt = (
            select(MedicineBillItem.medicine_bill_id, func.count())
            .where(
                MedicineBillItem.deleted_at.is_(None),
                MedicineBillItem.medicine_bill_id.in_(medicine_bill_ids),
            )
            .group_by(MedicineBillItem.medicine_bill_id)
        )
        result = await self.session.execute(stmt)
        return dict(result.all())


class MedicineBillPaymentRepository(BaseRepository[MedicineBillPayment]):
    model = MedicineBillPayment

    async def list_for_bill(self, medicine_bill_id: UUID) -> list[MedicineBillPayment]:
        stmt = self._exclude_soft_deleted(
            select(MedicineBillPayment)
            .where(MedicineBillPayment.medicine_bill_id == medicine_bill_id)
            .order_by(MedicineBillPayment.created_at.asc()),
            include_deleted=False,
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

"""Persistence-only repositories for the Lab module — see
app/modules/patients/repository.py's identical module docstring for the
"persistence only, no policy" rationale."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Sequence, func, select
from sqlalchemy.orm import InstrumentedAttribute

from app.modules.lab.models import LabBill, LabBillItem, LabBillPayment, LabTest
from app.modules.visits.constants import QUEUE_TOKEN_SEQUENCE_NAME
from app.shared.repository.base_repository import BaseRepository

# The exact same Postgres sequence app/modules/visits/repository.py's
# VisitRepository and app/modules/pharmacy/repository.py's
# MedicineBillRepository both already draw from — see
# QUEUE_TOKEN_SEQUENCE_NAME's own docstring for the full unification
# rationale. Deliberately not a third, independent Sequence object.
_queue_token_sequence = Sequence(QUEUE_TOKEN_SEQUENCE_NAME)

# Whitelist of columns LabTestRepository.list_all may sort by — never
# accept a raw column/attribute name from a caller, same rationale as
# app/modules/pharmacy/repository.py's MEDICINE_SORTABLE_COLUMNS.
LAB_TEST_SORTABLE_COLUMNS: dict[str, InstrumentedAttribute] = {
    "created_at": LabTest.created_at,
    "name": LabTest.name,
}


class LabTestRepository(BaseRepository[LabTest]):
    model = LabTest

    async def search_active(self, *, search: str, limit: int) -> list[LabTest]:
        """Backs the receptionist-facing autocomplete (`GET
        /lab/tests/search`) — active tests only, case-insensitive
        partial name match, same `ILIKE` pattern as app/modules/
        pharmacy/repository.py's `MedicineRepository.search_active`."""
        pattern = f"%{search}%"
        stmt = self._exclude_soft_deleted(
            select(LabTest)
            .where(LabTest.is_active.is_(True), LabTest.name.ilike(pattern))
            .order_by(LabTest.name.asc())
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
    ) -> tuple[list[LabTest], int]:
        """Backs the admin management screen (`GET /lab/tests`) — every
        test, active and inactive alike, so a deactivated entry stays
        visible and re-activatable there."""
        conditions = [LabTest.deleted_at.is_(None)]
        if search:
            conditions.append(LabTest.name.ilike(f"%{search}%"))

        stmt = select(LabTest).where(*conditions)
        total = (
            await self.session.execute(select(func.count()).select_from(stmt.subquery()))
        ).scalar_one()

        order_column = sort_column.desc() if sort_desc else sort_column.asc()
        stmt = stmt.order_by(order_column, LabTest.id).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total


class LabBillRepository(BaseRepository[LabBill]):
    model = LabBill

    async def next_queue_token_value(self) -> int:
        """Draws the next value from the exact same Postgres sequence
        `VisitRepository.next_queue_token_value`/`MedicineBillRepository.
        next_queue_token_value` draw from — see `_queue_token_sequence`'s
        own module-level docstring above. Race-safe the same way both
        already are: a Postgres sequence's `nextval` is atomic."""
        result = await self.session.execute(_queue_token_sequence.next_value().select())
        return result.scalar_one()

    async def get_for_update(self, lab_bill_id: UUID) -> LabBill | None:
        """Row-locking variant of `get_by_id`, for `LabService.
        record_payment`'s read-modify-write — identical rationale to
        app/modules/pharmacy/repository.py's `MedicineBillRepository.
        get_for_update`."""
        stmt = self._exclude_soft_deleted(
            select(LabBill).where(LabBill.id == lab_bill_id), include_deleted=False
        ).with_for_update()
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def count_and_revenue_by_creator(self) -> dict[UUID, tuple[int, Decimal]]:
        """Backs the Admin "Employee Accounts & Stats" page's per-
        receptionist "lab bills created" / "revenue billed" figures —
        identical shape to app/modules/pharmacy/repository.py's
        `MedicineBillRepository.count_and_revenue_by_creator`. Sums
        `total_amount` ("revenue billed"), not `amount_paid`, matching
        that method's own documented convention."""
        stmt = (
            select(LabBill.created_by, func.count(), func.sum(LabBill.total_amount))
            .where(LabBill.deleted_at.is_(None), LabBill.created_by.is_not(None))
            .group_by(LabBill.created_by)
        )
        result = await self.session.execute(stmt)
        return {created_by: (count, revenue) for created_by, count, revenue in result.all()}

    async def count_and_revenue_for_creator(
        self, user_id: UUID, *, since: datetime | None = None
    ) -> tuple[int, Decimal]:
        """The single-user, optionally-since-a-cutoff sibling of
        `count_and_revenue_by_creator` above — backs the "Lab" quarter
        of Reception's own "My Revenue" tile, the identical shape
        app/modules/pharmacy/repository.py's `MedicineBillRepository.
        count_and_revenue_for_creator` already established."""
        conditions = [LabBill.deleted_at.is_(None), LabBill.created_by == user_id]
        if since is not None:
            conditions.append(LabBill.created_at > since)
        stmt = select(func.count(), func.sum(LabBill.total_amount)).where(*conditions)
        result = await self.session.execute(stmt)
        count, revenue = result.one()
        return count, (revenue if revenue is not None else Decimal("0.00"))

    async def list_for_creator(
        self, user_id: UUID, *, page: int, page_size: int
    ) -> tuple[list[LabBill], int]:
        """Real, paginated server-side "every bill this user has ever
        created", newest first, no date restriction — the lab-bill
        sibling of app/modules/pharmacy/repository.py's
        `MedicineBillRepository.list_for_creator`, backing the
        receptionist's own "My Lab Bills" list."""
        stmt = self._exclude_soft_deleted(
            select(LabBill).where(LabBill.created_by == user_id), include_deleted=False
        )
        total = (
            await self.session.execute(select(func.count()).select_from(stmt.subquery()))
        ).scalar_one()

        stmt = (
            stmt.order_by(LabBill.created_at.desc()).limit(page_size).offset((page - 1) * page_size)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total

    async def list_for_patient(self, patient_id: UUID) -> list[LabBill]:
        """Every lab bill actually linked to this Patient row (`patient_id`
        set) — never a "manual"/walk-in bill, which by construction has
        no `patient_id` at all (see this module's own docstring on the
        mutual-exclusivity CHECK constraint) and so could never belong to
        a specific Patient's history regardless. Used by the Patient
        History aggregation module (app/modules/patient_history/
        service.py) — unlike every other module in that aggregation,
        LabBill needs no visit_id join at all, since it already carries
        `patient_id` directly."""
        stmt = self._exclude_soft_deleted(
            select(LabBill)
            .where(LabBill.patient_id == patient_id)
            .order_by(LabBill.created_at.asc()),
            include_deleted=False,
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_for_day(self, day: datetime) -> list[LabBill]:
        """Every lab bill created on `day`'s UTC calendar date — the
        Admin Overview's Lab Bills tab, the same UTC-calendar-day window
        app/modules/pharmacy/repository.py's `MedicineBillRepository.
        list_for_day` already uses."""
        start_of_day = datetime(day.year, day.month, day.day, tzinfo=UTC)
        end_of_day = start_of_day + timedelta(days=1)
        stmt = self._exclude_soft_deleted(
            select(LabBill)
            .where(LabBill.created_at >= start_of_day, LabBill.created_at < end_of_day)
            .order_by(LabBill.created_at.asc()),
            include_deleted=False,
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class LabBillItemRepository(BaseRepository[LabBillItem]):
    model = LabBillItem

    async def list_for_bill(self, lab_bill_id: UUID) -> list[LabBillItem]:
        stmt = self._exclude_soft_deleted(
            select(LabBillItem)
            .where(LabBillItem.lab_bill_id == lab_bill_id)
            .order_by(LabBillItem.created_at.asc()),
            include_deleted=False,
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count_items_for_bills(self, lab_bill_ids: list[UUID]) -> dict[UUID, int]:
        """One `GROUP BY` query for every given bill's line-item count —
        backs the Admin Overview's Lab Bills tab, not one query per bill,
        the same N+1 avoidance as app/modules/pharmacy/repository.py's
        `MedicineBillItemRepository.count_items_for_bills`."""
        if not lab_bill_ids:
            return {}
        stmt = (
            select(LabBillItem.lab_bill_id, func.count())
            .where(LabBillItem.deleted_at.is_(None), LabBillItem.lab_bill_id.in_(lab_bill_ids))
            .group_by(LabBillItem.lab_bill_id)
        )
        result = await self.session.execute(stmt)
        return dict(result.all())


class LabBillPaymentRepository(BaseRepository[LabBillPayment]):
    model = LabBillPayment

    async def list_for_bill(self, lab_bill_id: UUID) -> list[LabBillPayment]:
        stmt = self._exclude_soft_deleted(
            select(LabBillPayment)
            .where(LabBillPayment.lab_bill_id == lab_bill_id)
            .order_by(LabBillPayment.created_at.asc()),
            include_deleted=False,
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_distinct_payment_methods_for_bills(
        self, lab_bill_ids: list[UUID]
    ) -> dict[UUID, list[str]]:
        """One query for every given bill's *distinct* payment methods,
        in first-payment order — backs the Admin Overview Lab Bills
        tab's "Payment Method" column, the same N+1-avoidance shape as
        app/modules/pharmacy/repository.py's `MedicineBillPaymentRepository.
        list_distinct_payment_methods_for_bills`."""
        if not lab_bill_ids:
            return {}
        stmt = (
            select(LabBillPayment.lab_bill_id, LabBillPayment.payment_method)
            .where(
                LabBillPayment.deleted_at.is_(None), LabBillPayment.lab_bill_id.in_(lab_bill_ids)
            )
            .order_by(LabBillPayment.lab_bill_id, LabBillPayment.created_at.asc())
        )
        result = await self.session.execute(stmt)
        methods_by_bill: dict[UUID, list[str]] = {}
        for bill_id, method in result.all():
            methods = methods_by_bill.setdefault(bill_id, [])
            if method.value not in methods:
                methods.append(method.value)
        return methods_by_bill

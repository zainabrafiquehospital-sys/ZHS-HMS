"""Persistence-only repositories for the Pharmacy module — see
app/modules/patients/repository.py's identical module docstring for the
"persistence only, no policy" rationale."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Sequence, func, select
from sqlalchemy.orm import InstrumentedAttribute

from app.modules.pharmacy.models import (
    Medicine,
    MedicineBill,
    MedicineBillItem,
    MedicineBillPayment,
)
from app.modules.visits.constants import QUEUE_TOKEN_SEQUENCE_NAME
from app.shared.repository.base_repository import BaseRepository

# The exact same Postgres sequence app/modules/visits/repository.py's
# VisitRepository draws from — see QUEUE_TOKEN_SEQUENCE_NAME's own
# docstring (2026-08-20 addition) for the full unification rationale.
# Deliberately not a second, independent Sequence object with a
# different name: this is the single source of every token number
# either a Visit or a MedicineBill can ever get, which is what
# guarantees true chronological interleaving with no possible
# collision.
_queue_token_sequence = Sequence(QUEUE_TOKEN_SEQUENCE_NAME)

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

    async def next_queue_token_value(self) -> int:
        """Draws the next value from the exact same Postgres sequence
        `VisitRepository.next_queue_token_value` draws from — see
        `_queue_token_sequence`'s own module-level docstring above and
        `MedicineBill.queue_token`'s column docstring for the full
        unification rationale (2026-08-20 addition). Race-safe the same
        way the Visit side already is: a Postgres sequence's `nextval`
        is atomic, so two concurrent bill-creation (or visit-
        registration) requests can never receive the same value."""
        result = await self.session.execute(_queue_token_sequence.next_value().select())
        return result.scalar_one()

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

    async def count_and_revenue_by_creator(self) -> dict[UUID, tuple[int, Decimal]]:
        """Backs the Admin "Employee Accounts & Stats" page's per-
        receptionist "medicine bills created" / "revenue billed"
        figures — one `GROUP BY` query for every creator's bill count
        and `total_amount` sum, the same N+1-avoidance shape as
        app/modules/visits/repository.py's `count_by_creator`. "Revenue
        billed" deliberately sums `total_amount` (what was billed), not
        `amount_paid` (what has actually been collected so far) — an
        unpaid or partially-paid bill still counts toward this figure,
        matching the task's literal "revenue billed" wording. Bills
        with a NULL `created_by` (none in practice — see
        PharmacyService.create_bill — but never assumed) are excluded
        rather than surfacing as a spurious `{None: ...}` entry."""
        stmt = (
            select(MedicineBill.created_by, func.count(), func.sum(MedicineBill.total_amount))
            .where(MedicineBill.deleted_at.is_(None), MedicineBill.created_by.is_not(None))
            .group_by(MedicineBill.created_by)
        )
        result = await self.session.execute(stmt)
        return {
            created_by: (count, revenue) for created_by, count, revenue in result.all()
        }

    async def count_and_revenue_for_creator(
        self, user_id: UUID, *, since: datetime | None = None
    ) -> tuple[int, Decimal]:
        """The single-user, optionally-since-a-cutoff sibling of
        `count_and_revenue_by_creator` above — see app/modules/visits/
        repository.py's identical `count_and_revenue_for_creator` for
        the full rationale (this backs the "Medicines" half of
        Reception's own "My Revenue" tile, 2026-08-19 addition). Also
        sums `total_amount` ("revenue billed"), matching
        `count_and_revenue_by_creator`'s own documented convention, not
        `amount_paid`."""
        conditions = [MedicineBill.deleted_at.is_(None), MedicineBill.created_by == user_id]
        if since is not None:
            conditions.append(MedicineBill.created_at > since)
        stmt = select(func.count(), func.sum(MedicineBill.total_amount)).where(*conditions)
        result = await self.session.execute(stmt)
        count, revenue = result.one()
        return count, (revenue if revenue is not None else Decimal("0.00"))

    async def list_for_creator(
        self, user_id: UUID, *, page: int, page_size: int
    ) -> tuple[list[MedicineBill], int]:
        """Real, paginated server-side "every bill this user has ever
        created" (2026-08-19 addition) — the medicine-bill sibling of
        app/modules/visits/repository.py's `search`'s `created_by`
        filter, backing the receptionist's own "My Medicine Bills" list
        the same way that filter backs "My Registrations". Newest
        first, no date restriction, same rationale as that method's own
        docstring: a real unbounded server-side filter, never a
        client-side "fetch N most recent" approximation."""
        stmt = self._exclude_soft_deleted(
            select(MedicineBill).where(MedicineBill.created_by == user_id), include_deleted=False
        )
        total = (
            await self.session.execute(select(func.count()).select_from(stmt.subquery()))
        ).scalar_one()

        stmt = stmt.order_by(MedicineBill.created_at.desc()).limit(page_size).offset(
            (page - 1) * page_size
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total

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

    async def list_for_visit_ids(self, visit_ids: list[UUID]) -> list[MedicineBill]:
        """Every medicine bill actually linked to one of the given
        Visits (`visit_id` set) — never a "manual"/walk-in bill, which
        by construction has no `visit_id` at all (see this module's own
        docstring on the mutual-exclusivity CHECK constraint). Used by
        the Patient History aggregation module (app/modules/
        patient_history/service.py), the same visit-ID-batch shape as
        app/modules/vitals/repository.py's `list_for_visit_ids` —
        MedicineBill has no `patient_id` column of its own (unlike
        LabBill), so this is the only path from patient to their
        medicine bills."""
        if not visit_ids:
            return []
        stmt = self._exclude_soft_deleted(
            select(MedicineBill)
            .where(MedicineBill.visit_id.in_(visit_ids))
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

    async def list_distinct_payment_methods_for_bills(
        self, medicine_bill_ids: list[UUID]
    ) -> dict[UUID, list[str]]:
        """One query for every given bill's *distinct* payment methods,
        in first-payment order — backs the Admin Overview Medicine
        Bills tab's "Payment Method" column (2026-08-19 addition), the
        same N+1-avoidance shape as `MedicineBillItemRepository.
        count_items_for_bills`. Grouping/de-duplicating by first-seen
        order happens in Python rather than a `GROUP BY` + `array_agg`
        (which would need Postgres-specific ordering tricks to keep
        first-payment order) — this table is small per bill, so a
        single ordered fetch plus a plain Python loop is simpler and
        just as correct. Bills with no payments yet simply have no
        entry in the returned dict; callers should default to `[]`."""
        if not medicine_bill_ids:
            return {}
        stmt = (
            select(MedicineBillPayment.medicine_bill_id, MedicineBillPayment.payment_method)
            .where(
                MedicineBillPayment.deleted_at.is_(None),
                MedicineBillPayment.medicine_bill_id.in_(medicine_bill_ids),
            )
            .order_by(MedicineBillPayment.medicine_bill_id, MedicineBillPayment.created_at.asc())
        )
        result = await self.session.execute(stmt)
        methods_by_bill: dict[UUID, list[str]] = {}
        for bill_id, method in result.all():
            methods = methods_by_bill.setdefault(bill_id, [])
            if method.value not in methods:
                methods.append(method.value)
        return methods_by_bill

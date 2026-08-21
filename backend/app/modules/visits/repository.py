"""Persistence-only repository for the Visit module — see
app/modules/patients/repository.py's identical module docstring for the
"persistence only, no policy" rationale."""

from datetime import UTC, date as date_type, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Sequence, func, select, update
from sqlalchemy.orm import InstrumentedAttribute

from app.modules.visits.constants import QUEUE_TOKEN_SEQUENCE_NAME
from app.modules.visits.models import Procedure, Visit, VisitProcedureItem, VisitStatus
from app.shared.repository.base_repository import BaseRepository

VISIT_SORTABLE_COLUMNS: dict[str, InstrumentedAttribute] = {
    "created_at": Visit.created_at,
    "status": Visit.status,
}

# Whitelist of columns ProcedureRepository.list_all may sort by — never
# accept a raw column/attribute name from a caller, same rationale as
# app/modules/pharmacy/repository.py's MEDICINE_SORTABLE_COLUMNS.
PROCEDURE_SORTABLE_COLUMNS: dict[str, InstrumentedAttribute] = {
    "created_at": Procedure.created_at,
    "name": Procedure.name,
}

# See app/modules/patients/repository.py's `_mr_number_sequence` for the
# identical race-safety rationale, applied here to Queue Token generation.
_queue_token_sequence = Sequence(QUEUE_TOKEN_SEQUENCE_NAME)


class VisitRepository(BaseRepository[Visit]):
    model = Visit

    async def next_queue_token_value(self) -> int:
        result = await self.session.execute(_queue_token_sequence.next_value().select())
        return result.scalar_one()

    async def get_by_queue_token(self, queue_token: str) -> Visit | None:
        stmt = self._exclude_soft_deleted(
            select(Visit).where(Visit.queue_token == queue_token), include_deleted=False
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def search(
        self,
        *,
        patient_id: UUID | None,
        doctor_user_id: UUID | None,
        created_by: UUID | None = None,
        date: date_type | None = None,
        unassigned_only: bool = False,
        status: VisitStatus | None,
        sort_column: InstrumentedAttribute,
        sort_desc: bool,
        limit: int,
        offset: int,
    ) -> tuple[list[Visit], int]:
        """Backs `GET /visits`. Every filter is optional and additive —
        the Doctor Queue / Vitals worklist screens (built on top of the
        not-yet-built Queue module) will layer their own routing filter
        on top of this; this method only ever filters by Visit's own
        columns.

        `unassigned_only` backs the Doctor Queue's "unclaimed pool" view
        (fast-registration visits Reception couldn't auto-assign — see
        models.py's `doctor_user_id` docstring) — mutually exclusive
        with `doctor_user_id` in practice, but not enforced here; the
        caller (VisitService) owns that policy.

        `created_by` is a real, unbounded server-side filter — added so
        "every visit this specific user has ever registered" (Reception's
        own "My Registrations" list) never depends on a client-side
        "fetch N most recent + filter" approximation that could silently
        drop older rows once hospital-wide volume grows past whatever N
        was chosen (see this codebase's own prior documented follow-up
        on that exact gap).

        `date` filters to one UTC calendar day (`[date 00:00, date+1
        00:00) UTC`) — the same interpretation
        `MedicineBillRepository.list_for_day` already uses for Pharmacy,
        not the caller's DISPLAY_TIMEZONE calendar day (see that
        method's docstring for the identical caveat: a Visit created in
        the first/last few hours of a Karachi calendar day can appear
        under the adjacent UTC date near midnight). Added so the Admin
        Overview day-view is a real, always-accurate server-side query
        instead of the same "fetch N most recent + filter" shortcut."""
        conditions = [Visit.deleted_at.is_(None)]
        if patient_id is not None:
            conditions.append(Visit.patient_id == patient_id)
        if unassigned_only:
            conditions.append(Visit.doctor_user_id.is_(None))
        elif doctor_user_id is not None:
            conditions.append(Visit.doctor_user_id == doctor_user_id)
        if created_by is not None:
            conditions.append(Visit.created_by == created_by)
        if date is not None:
            start_of_day = datetime(date.year, date.month, date.day, tzinfo=UTC)
            end_of_day = start_of_day + timedelta(days=1)
            conditions.append(Visit.created_at >= start_of_day)
            conditions.append(Visit.created_at < end_of_day)
        if status is not None:
            conditions.append(Visit.status == status)

        stmt = select(Visit).where(*conditions)
        total = (
            await self.session.execute(select(func.count()).select_from(stmt.subquery()))
        ).scalar_one()

        order_column = sort_column.desc() if sort_desc else sort_column.asc()
        stmt = stmt.order_by(order_column, Visit.id).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total

    async def assign_doctor_if_unassigned(self, *, visit_id: UUID, doctor_user_id: UUID) -> bool:
        """Conditional claim for an unassigned Visit (`doctor_user_id IS
        NULL`) — a plain `UPDATE ... WHERE doctor_user_id IS NULL`
        rather than a read-then-write, so two doctors racing to claim
        the same unclaimed Visit can never both "win" this column (the
        loser's UPDATE simply matches zero rows). The actual
        authoritative arbiter of who gets to treat the patient is still
        Consultation's own single-active-per-visit unique index (see
        consultation/service.py's `start_consultation`) — this only
        protects the informational `doctor_user_id` column on Visit
        itself from being silently overwritten by a second claim.
        Returns whether a row was actually updated."""
        stmt = (
            update(Visit)
            .where(Visit.id == visit_id, Visit.doctor_user_id.is_(None))
            .values(doctor_user_id=doctor_user_id)
        )
        result = await self.session.execute(stmt)
        return result.rowcount > 0

    async def count_by_status(self) -> dict[VisitStatus, int]:
        """Backs the Reception Dashboard (Phase 6 §22) — a single
        `GROUP BY` query for every status's count, not one query per
        status (which would be exactly the N+1 pattern this project's
        quality bar forbids)."""
        stmt = (
            select(Visit.status, func.count())
            .where(Visit.deleted_at.is_(None))
            .group_by(Visit.status)
        )
        result = await self.session.execute(stmt)
        return dict(result.all())

    async def count_and_revenue_by_creator(self) -> dict[UUID, tuple[int, Decimal]]:
        """Backs the Admin "Employee Accounts & Stats" page's per-
        receptionist "visits registered" figure — every creator's real,
        all-time, never-reset total, exactly as recorded — one
        `GROUP BY` query for every creator's count and total `amount`
        across all Visits, the same N+1-avoidance shape as
        `count_by_status` above, and the same `(count, revenue)` shape
        `MedicineBillRepository.count_and_revenue_by_creator` already
        returns for medicine bills. Visits with a NULL `created_by`
        (none in practice — VisitService.register_visit always stamps
        it — but never assumed) are excluded by the `is_not(None)`
        filter rather than surfacing as a spurious `{None: ...}` entry
        the caller would have to special-case.

        Deliberately never scoped/filtered by a receptionist's own
        "Clear Revenue" action (see ReceptionService.get_own_revenue) —
        this is Admin's own all-time audit view of everyone, and must
        keep showing the true, complete history regardless of what any
        individual receptionist has cleared from her own display.
        `count_and_revenue_for_creator` below is the single-user,
        clear-aware sibling this method deliberately isn't."""
        stmt = (
            select(Visit.created_by, func.count(), func.sum(Visit.amount))
            .where(Visit.deleted_at.is_(None), Visit.created_by.is_not(None))
            .group_by(Visit.created_by)
        )
        result = await self.session.execute(stmt)
        return {created_by: (count, revenue) for created_by, count, revenue in result.all()}

    async def count_and_revenue_for_creator(
        self, user_id: UUID, *, since: datetime | None = None
    ) -> tuple[int, Decimal]:
        """The single-user, optionally-since-a-cutoff sibling of
        `count_and_revenue_by_creator` above — backs Reception's own "My
        Revenue" tile (2026-08-19 addition). `since`, when given, is a
        receptionist's own "Clear Revenue" reset point (see
        ReceptionService.get_own_revenue) — never touches or excludes
        any row, purely narrows which of her *own* already-intact rows
        count toward what she currently sees. Returns `(0, Decimal("0.00"))`
        rather than `(0, None)` for "no matching visits", so callers never
        need a None-check on the revenue half specifically."""
        conditions = [Visit.deleted_at.is_(None), Visit.created_by == user_id]
        if since is not None:
            conditions.append(Visit.created_at > since)
        stmt = select(func.count(), func.sum(Visit.amount)).where(*conditions)
        result = await self.session.execute(stmt)
        count, revenue = result.one()
        return count, (revenue if revenue is not None else Decimal("0.00"))


class ProcedureRepository(BaseRepository[Procedure]):
    """Mirrors app/modules/pharmacy/repository.py's `MedicineRepository`
    almost exactly (2026-08-21 addition)."""

    model = Procedure

    async def search_active(self, *, search: str, limit: int) -> list[Procedure]:
        """Backs the receptionist-facing autocomplete (`GET
        /visits/procedures/search`) — active procedures only, case-
        insensitive partial name match, same `ILIKE` pattern as
        `MedicineRepository.search_active`."""
        pattern = f"%{search}%"
        stmt = self._exclude_soft_deleted(
            select(Procedure)
            .where(Procedure.is_active.is_(True), Procedure.name.ilike(pattern))
            .order_by(Procedure.name.asc())
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
    ) -> tuple[list[Procedure], int]:
        """Backs the admin management screen (`GET /visits/procedures`)
        — every procedure, active and inactive alike, so a deactivated
        entry stays visible and re-activatable there. Soft-deleted
        procedures are excluded (unlike Medicine, this catalog also
        supports a genuine delete, not only activate/deactivate — see
        models.py's `Procedure` docstring)."""
        conditions = [Procedure.deleted_at.is_(None)]
        if search:
            conditions.append(Procedure.name.ilike(f"%{search}%"))

        stmt = select(Procedure).where(*conditions)
        total = (
            await self.session.execute(select(func.count()).select_from(stmt.subquery()))
        ).scalar_one()

        order_column = sort_column.desc() if sort_desc else sort_column.asc()
        stmt = stmt.order_by(order_column, Procedure.id).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total


class VisitProcedureItemRepository(BaseRepository[VisitProcedureItem]):
    """Mirrors app/modules/pharmacy/repository.py's
    `MedicineBillItemRepository` (2026-08-21 addition)."""

    model = VisitProcedureItem

    async def list_for_visit(self, visit_id: UUID) -> list[VisitProcedureItem]:
        stmt = self._exclude_soft_deleted(
            select(VisitProcedureItem)
            .where(VisitProcedureItem.visit_id == visit_id)
            .order_by(VisitProcedureItem.created_at.asc()),
            include_deleted=False,
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_for_visits(
        self, visit_ids: list[UUID]
    ) -> dict[UUID, list[VisitProcedureItem]]:
        """Batched sibling of `list_for_visit` — one query for every
        given visit's procedure items, not one query per visit (the
        same N+1 avoidance as `MedicineBillItemRepository.
        count_items_for_bills`), backing `GET /visits`'s list response.
        A visit with zero matching rows (every visit registered before
        2026-08-21, by design — see models.py's `VisitProcedureItem`
        docstring) simply has no entry in the returned dict; callers
        should default to `[]`."""
        if not visit_ids:
            return {}
        stmt = self._exclude_soft_deleted(
            select(VisitProcedureItem)
            .where(VisitProcedureItem.visit_id.in_(visit_ids))
            .order_by(VisitProcedureItem.visit_id, VisitProcedureItem.created_at.asc()),
            include_deleted=False,
        )
        result = await self.session.execute(stmt)
        items_by_visit: dict[UUID, list[VisitProcedureItem]] = {}
        for item in result.scalars().all():
            items_by_visit.setdefault(item.visit_id, []).append(item)
        return items_by_visit

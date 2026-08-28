"""Persistence-only repository for the Vitals module — see
app/modules/patients/repository.py's identical module docstring."""

from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select

from app.modules.vitals.models import VitalsRecord
from app.shared.repository.base_repository import BaseRepository


class VitalsRecordRepository(BaseRepository[VitalsRecord]):
    model = VitalsRecord

    async def list_for_visit(self, visit_id: UUID) -> list[VitalsRecord]:
        stmt = self._exclude_soft_deleted(
            select(VitalsRecord)
            .where(VitalsRecord.visit_id == visit_id)
            .order_by(VitalsRecord.created_at.asc()),
            include_deleted=False,
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_latest_for_visit_ids(self, visit_ids: list[UUID]) -> VitalsRecord | None:
        """Used by VitalsService.get_latest_for_patient to find a
        patient's most recent prior vitals record, given the patient's
        other visit IDs (resolved via VisitService, not looked up here —
        see this module's models.py docstring: Visit is a plain FK
        column, never a `relationship()`, and this repository only ever
        queries its own table, keeping the one-directional module
        dependency graph (§12) intact). Filters purely by
        `visit_id IN (...)`, no cross-table join."""
        if not visit_ids:
            return None
        stmt = self._exclude_soft_deleted(
            select(VitalsRecord)
            .where(VitalsRecord.visit_id.in_(visit_ids))
            .order_by(VitalsRecord.created_at.desc())
            .limit(1),
            include_deleted=False,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_for_visit_ids(self, visit_ids: list[UUID]) -> list[VitalsRecord]:
        """Used by VitalsService.list_for_patient to back the "Show
        Details" cross-visit vitals history view — every vitals record
        recorded across every one of a patient's visits, not just the
        latest (see get_latest_for_visit_ids' identical docstring on why
        this stays a plain `visit_id IN (...)` filter rather than a
        cross-table join). Newest first, matching the history view's own
        "chronological, newest-first" requirement — callers never need
        to re-sort."""
        if not visit_ids:
            return []
        stmt = self._exclude_soft_deleted(
            select(VitalsRecord)
            .where(VitalsRecord.visit_id.in_(visit_ids))
            .order_by(VitalsRecord.created_at.desc()),
            include_deleted=False,
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_for_creator_and_day(
        self, *, created_by: UUID, day: datetime
    ) -> list[VitalsRecord]:
        """Every vitals record `created_by` personally recorded on `day`'s
        UTC calendar date, oldest first — the exact same shape
        `InventoryUsageEntryRepository.list_for_creator_and_day` already
        established for the identical "one staff member's one day"
        scoping (see that method's own docstring), backing this module's
        half of the Step 5 combined daily summary print (Inventory items
        used + Vitals recorded, one document — see
        app/shared/printing/service.py's `render_vitals_daily_summary`)."""
        start_of_day = datetime(day.year, day.month, day.day, tzinfo=day.tzinfo)
        end_of_day = start_of_day + timedelta(days=1)
        stmt = self._exclude_soft_deleted(
            select(VitalsRecord)
            .where(
                VitalsRecord.created_by == created_by,
                VitalsRecord.created_at >= start_of_day,
                VitalsRecord.created_at < end_of_day,
            )
            .order_by(VitalsRecord.created_at.asc()),
            include_deleted=False,
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_for_creator(
        self, user_id: UUID, *, page: int, page_size: int
    ) -> tuple[list[VitalsRecord], int]:
        """Real, paginated server-side "every vitals record this staff
        member has ever recorded" (2026-08-28 addition) — the Vitals
        sibling of `MedicineBillRepository.list_for_creator`/
        `MedicineBillRepository`'s own "My Medicine Bills" list, backing
        Vitals' own "My Vitals Records" screen the same way that method
        backs Pharmacy's. Newest first, no date restriction — unlike
        `list_for_creator_and_day` above (deliberately day-scoped for
        the daily summary print), this is the full, real, unbounded
        history, same rationale as `MedicineBillRepository.
        list_for_creator`'s own docstring: a real server-side filter,
        never a client-side "fetch N most recent" approximation."""
        stmt = self._exclude_soft_deleted(
            select(VitalsRecord).where(VitalsRecord.created_by == user_id), include_deleted=False
        )
        total = (
            await self.session.execute(select(func.count()).select_from(stmt.subquery()))
        ).scalar_one()

        stmt = stmt.order_by(VitalsRecord.created_at.desc()).limit(page_size).offset(
            (page - 1) * page_size
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total

    async def count_by_creator(self) -> dict[UUID, int]:
        """Backs the Admin "Employee Accounts & Stats" page's per-
        vitals-staff "vitals recorded" figure — one `GROUP BY` query for
        every creator's count, the same N+1-avoidance shape as
        app/modules/visits/repository.py's `count_by_creator`. Records
        with a NULL `created_by` (none in practice — VitalsService.
        record_vitals always stamps it — but never assumed) are
        excluded rather than surfacing as a spurious `{None: n}` entry."""
        stmt = (
            select(VitalsRecord.created_by, func.count())
            .where(VitalsRecord.deleted_at.is_(None), VitalsRecord.created_by.is_not(None))
            .group_by(VitalsRecord.created_by)
        )
        result = await self.session.execute(stmt)
        return dict(result.all())

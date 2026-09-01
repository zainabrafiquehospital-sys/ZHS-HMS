"""Read-only cross-table query backing the Patient History page's own
always-visible, hospital-wide feed (`GET /patients/history/visits`) —
the one place in this codebase a single query is allowed to span
`Visit`/`MedicineBill`/`LabBill` directly. This is safe precisely
because of this *module's* own "depends on everything it reports on;
nothing depends back on it" shape (see service.py's module docstring)
— none of those three modules' own repositories gain any new
cross-module knowledge from this file, and nothing outside
`patient_history` ever imports from here.

Every real Token # in the hospital is drawn from one shared Postgres
sequence across all three tables (see app/modules/visits/constants.py's
`QUEUE_TOKEN_SEQUENCE_NAME` docstring — Visit/MedicineBill/LabBill all
draw from `visit_queue_token_seq`). This repository's whole job is
presenting that already-unified numbering as one genuinely continuous,
searchable, paginated feed — a receptionist should never have to check
three separate lists to find "Token #802", regardless of which of the
three tables it actually lives in.

`MedicineBill` has no `patient_id` column of its own (see that model's
own docstring) — a medicine bill's patient, if any, is only reachable
by joining through its (nullable) `visit_id` to `Visit.patient_id`.
That join lives here, not in Pharmacy's own repository, for the same
"this module already depends on both, neither of them may depend on
each other" reasoning `patient_ids` resolution already established for
`VisitRepository.search` (see that method's own docstring)."""

from dataclasses import dataclass
from datetime import UTC, date as date_type, datetime, timedelta
from uuid import UUID

from sqlalchemy import Select, func, literal, or_, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from app.modules.lab.models import LabBill
from app.modules.pharmacy.models import MedicineBill
from app.modules.visits.models import Visit


@dataclass(frozen=True)
class PatientHistoryFeedRow:
    """One normalized row out of the unified union — just enough to
    identify *which* real row (of which type) belongs on this page and
    in what order; `PatientHistoryService.list_records` looks the full
    `Visit`/`MedicineBill`/`LabBill` row up afterward, batched by type,
    to build the actual response."""

    id: UUID
    record_type: str
    queue_token: str | None
    created_at: datetime
    patient_id: UUID | None


class PatientHistoryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def search_feed(
        self,
        *,
        patient_ids: list[UUID] | None,
        token_search: str | None,
        start_date: date_type | None,
        end_date: date_type | None,
        include_visits: bool,
        include_medicine_bills: bool,
        include_lab_bills: bool,
        limit: int,
        offset: int,
    ) -> tuple[list[PatientHistoryFeedRow], int]:
        """`patient_ids`/`token_search` combine with `OR`, never `AND`
        — a single search box serves both "find this patient's
        records" and "find this exact token", and a term that happens
        to look like both (unlikely, but not impossible) should still
        match either way. `patient_ids=None` means no search term was
        given at all (no patient filter); `patient_ids=[]` means a
        term *was* given but matched no patient by name/MR/phone/CNIC
        — still a real, correct "zero patient matches" filter via
        `IN ()`, exactly like `VisitRepository.search`'s own identical
        `patient_ids` semantics — but with `token_search` still able to
        independently match a token even when the patient side matched
        nobody.

        `include_visits`/`include_medicine_bills`/`include_lab_bills`
        are the router's own per-actor permission decision (visits:read/
        pharmacy:read/lab:read), passed down rather than re-derived
        here — this repository has no permission logic of its own, the
        same split every other module's repository/router already
        follows. A branch the actor can't see is dropped from the
        `UNION ALL` entirely (never fetched and filtered after), so the
        page/total genuinely reflect only what this actor may see."""
        branches: list[Select] = []

        if include_visits:
            visit_select = self._apply_common_filters(
                select(
                    Visit.id.label("id"),
                    literal("visit").label("record_type"),
                    Visit.queue_token.label("queue_token"),
                    Visit.created_at.label("created_at"),
                    Visit.patient_id.label("patient_id"),
                ).where(Visit.deleted_at.is_(None)),
                created_at_column=Visit.created_at,
                queue_token_column=Visit.queue_token,
                patient_id_column=Visit.patient_id,
                patient_ids=patient_ids,
                token_search=token_search,
                start_date=start_date,
                end_date=end_date,
            )
            branches.append(visit_select)

        if include_medicine_bills:
            # LEFT JOIN, not INNER — a standalone/walk-in MedicineBill
            # with no `visit_id` must still appear (with `patient_id`
            # NULL), never be silently dropped from the feed just
            # because it has nothing to join against.
            medicine_select = self._apply_common_filters(
                select(
                    MedicineBill.id.label("id"),
                    literal("medicine_bill").label("record_type"),
                    MedicineBill.queue_token.label("queue_token"),
                    MedicineBill.created_at.label("created_at"),
                    Visit.patient_id.label("patient_id"),
                )
                .select_from(MedicineBill)
                .outerjoin(Visit, MedicineBill.visit_id == Visit.id)
                .where(MedicineBill.deleted_at.is_(None)),
                created_at_column=MedicineBill.created_at,
                queue_token_column=MedicineBill.queue_token,
                patient_id_column=Visit.patient_id,
                patient_ids=patient_ids,
                token_search=token_search,
                start_date=start_date,
                end_date=end_date,
            )
            branches.append(medicine_select)

        if include_lab_bills:
            lab_select = self._apply_common_filters(
                select(
                    LabBill.id.label("id"),
                    literal("lab_bill").label("record_type"),
                    LabBill.queue_token.label("queue_token"),
                    LabBill.created_at.label("created_at"),
                    LabBill.patient_id.label("patient_id"),
                ).where(LabBill.deleted_at.is_(None)),
                created_at_column=LabBill.created_at,
                queue_token_column=LabBill.queue_token,
                patient_id_column=LabBill.patient_id,
                patient_ids=patient_ids,
                token_search=token_search,
                start_date=start_date,
                end_date=end_date,
            )
            branches.append(lab_select)

        # No record type the actor may see at all (a hypothetical
        # future role holding patients:history:read but none of
        # visits:read/pharmacy:read/lab:read) — a genuinely empty feed,
        # not an invalid zero-branch UNION ALL.
        if not branches:
            return [], 0

        unioned = union_all(*branches).subquery()

        total = (
            await self.session.execute(select(func.count()).select_from(unioned))
        ).scalar_one()

        # `.id.desc()` as a tiebreaker: two rows can share the exact
        # same `created_at` (distinct sequence values, e.g. a Visit and
        # its own linked MedicineBill created in the same request), and
        # pagination across a UNION needs a fully deterministic order —
        # an `ORDER BY` on a non-unique column alone can otherwise
        # reshuffle rows between identically-ordered pages, the classic
        # correctness bug real pagination testing exists to catch.
        page_stmt = (
            select(unioned)
            .order_by(unioned.c.created_at.desc(), unioned.c.id.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(page_stmt)
        rows = [
            PatientHistoryFeedRow(
                id=row.id,
                record_type=row.record_type,
                queue_token=row.queue_token,
                created_at=row.created_at,
                patient_id=row.patient_id,
            )
            for row in result
        ]
        return rows, total

    @staticmethod
    def _apply_common_filters(
        stmt: Select,
        *,
        created_at_column: InstrumentedAttribute,
        queue_token_column: InstrumentedAttribute,
        patient_id_column: InstrumentedAttribute,
        patient_ids: list[UUID] | None,
        token_search: str | None,
        start_date: date_type | None,
        end_date: date_type | None,
    ) -> Select:
        if patient_ids is not None or token_search:
            conditions = []
            if patient_ids is not None:
                conditions.append(patient_id_column.in_(patient_ids))
            if token_search:
                conditions.append(queue_token_column.ilike(f"%{token_search}%"))
            stmt = stmt.where(or_(*conditions))
        if start_date is not None:
            stmt = stmt.where(
                created_at_column
                >= datetime(start_date.year, start_date.month, start_date.day, tzinfo=UTC)
            )
        if end_date is not None:
            end_of_range = datetime(
                end_date.year, end_date.month, end_date.day, tzinfo=UTC
            ) + timedelta(days=1)
            stmt = stmt.where(created_at_column < end_of_range)
        return stmt

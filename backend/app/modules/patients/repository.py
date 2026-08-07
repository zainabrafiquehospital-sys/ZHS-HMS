"""Persistence-only repository for the Patient module. Subclasses
`BaseRepository` (soft-delete filtering, `get_by_id`, `list`, `add`
already provided there) and adds only the entity-specific queries
PatientService needs — no validation, no MR-number formatting policy,
no business rules; persistence only, exactly as the layered
`router -> service -> repository -> model` architecture requires (see
app/modules/auth/repository.py's identical module docstring)."""

from sqlalchemy import Sequence, func, or_, select
from sqlalchemy.orm import InstrumentedAttribute

from app.modules.patients.constants import MR_NUMBER_SEQUENCE_NAME
from app.modules.patients.models import Patient
from app.shared.repository.base_repository import BaseRepository

# Whitelist of columns PatientRepository.search may sort by — never accept
# a raw column/attribute name from a caller, same rationale as
# app/modules/auth/repository.py's USER_SORTABLE_COLUMNS.
PATIENT_SORTABLE_COLUMNS: dict[str, InstrumentedAttribute] = {
    "created_at": Patient.created_at,
    "full_name": Patient.full_name,
    "mr_number": Patient.mr_number,
}

# The database-level sequence backing MR-number generation — created by
# this module's migration alongside the `patient` table. A real Postgres
# SEQUENCE (not `SELECT count(*) + 1`), so two concurrent Reception
# counters registering patients at the same instant can never be handed
# the same next value — the database itself serializes `nextval()`
# calls, closing the exact TOCTOU race app/shared/db_errors.py's module
# docstring describes for other "generate the next identifier" patterns.
_mr_number_sequence = Sequence(MR_NUMBER_SEQUENCE_NAME)


class PatientRepository(BaseRepository[Patient]):
    model = Patient

    async def next_mr_number_value(self) -> int:
        """The next raw sequence value — PatientService formats it into
        the final `MR-000123`-shaped string (see constants.py); the
        repository only owns talking to the database, never string
        formatting policy."""
        result = await self.session.execute(_mr_number_sequence.next_value().select())
        return result.scalar_one()

    async def get_by_mr_number(self, mr_number: str) -> Patient | None:
        stmt = self._exclude_soft_deleted(
            select(Patient).where(Patient.mr_number == mr_number), include_deleted=False
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_cnic(self, cnic: str) -> Patient | None:
        stmt = self._exclude_soft_deleted(
            select(Patient).where(Patient.cnic == cnic), include_deleted=False
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def search(
        self,
        *,
        search: str | None,
        sort_column: InstrumentedAttribute,
        sort_desc: bool,
        limit: int,
        offset: int,
    ) -> tuple[list[Patient], int]:
        """Backs `GET /patients` (listing) and the Patient Search MVP
        module (matches on name, MR number, phone number, or CNIC — the
        subset of Phase 6 §21's Global Search fields this module alone
        can serve without depending on visits/queue/billing, which would
        violate the one-directional dependency graph, §12)."""
        conditions = [Patient.deleted_at.is_(None)]
        if search:
            pattern = f"%{search}%"
            conditions.append(
                or_(
                    Patient.full_name.ilike(pattern),
                    Patient.mr_number.ilike(pattern),
                    Patient.phone_number.ilike(pattern),
                    Patient.cnic.ilike(pattern),
                )
            )

        stmt = select(Patient).where(*conditions)
        total = (
            await self.session.execute(select(func.count()).select_from(stmt.subquery()))
        ).scalar_one()

        order_column = sort_column.desc() if sort_desc else sort_column.asc()
        stmt = stmt.order_by(order_column, Patient.id).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total

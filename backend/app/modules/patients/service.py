"""Patient Management business logic. Does not subclass the shared
`BaseService` (app/shared/service/base_service.py), for the same reason
`RoleService`/`UserService` don't: this coordinates a repository plus
cross-cutting audit logging, not a single-entity CRUD shape (see
app/modules/auth/role_service.py's identical module docstring).

Every mutating method ends with an explicit `await self._session.commit()`,
matching the rest of this codebase's transaction-boundary convention."""

from typing import Any
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import User
from app.modules.patients.constants import MR_NUMBER_PAD_WIDTH, MR_NUMBER_PREFIX
from app.modules.patients.exceptions import PatientCnicAlreadyExistsError, PatientNotFoundError
from app.modules.patients.models import Patient
from app.modules.patients.repository import PATIENT_SORTABLE_COLUMNS, PatientRepository
from app.shared.audit.repository import AuditLogRepository
from app.shared.db_errors import unique_violation_constraint_name

# The unique-while-active index backing Patient.cnic — see
# app/modules/patients/models.py. Checked against a caught IntegrityError
# to tell a genuine race-lost duplicate apart from any other integrity
# failure, same rationale as app/modules/auth/role_service.py's
# _ROLE_NAME_CONSTRAINT handling.
_PATIENT_CNIC_CONSTRAINT = "ix_patient_cnic_active"


class PatientService:
    def __init__(
        self,
        session: AsyncSession,
        patient_repository: PatientRepository,
        audit_repository: AuditLogRepository,
    ) -> None:
        self._session = session
        self._patient_repo = patient_repository
        self._audit_repo = audit_repository

    async def _generate_mr_number(self) -> str:
        value = await self._patient_repo.next_mr_number_value()
        return f"{MR_NUMBER_PREFIX}-{value:0{MR_NUMBER_PAD_WIDTH}d}"

    async def register_patient(
        self,
        *,
        actor: User,
        full_name: str,
        guardian_name: str | None,
        gender: Any,
        age_years: int,
        phone_number: str,
        cnic: str | None,
        address: str | None,
    ) -> Patient:
        """Creates a brand-new Patient with a freshly generated, permanent
        `mr_number`. The CNIC pre-check below is not by itself race-safe
        — two concurrent registrations for the same CNIC can both pass it
        before either commits. The `try`/`except` around `add()` is what
        actually closes that window, matching every other
        "check existence, then insert" flow in this codebase (see
        app/shared/db_errors.py's module docstring)."""
        if cnic is not None and await self._patient_repo.get_by_cnic(cnic) is not None:
            raise PatientCnicAlreadyExistsError

        patient = Patient(
            mr_number=await self._generate_mr_number(),
            full_name=full_name,
            guardian_name=guardian_name,
            gender=gender,
            age_years=age_years,
            phone_number=phone_number,
            cnic=cnic,
            address=address,
            created_by=actor.id,
            updated_by=actor.id,
        )
        try:
            await self._patient_repo.add(patient)
        except IntegrityError as exc:
            await self._session.rollback()
            if unique_violation_constraint_name(exc) == _PATIENT_CNIC_CONSTRAINT:
                raise PatientCnicAlreadyExistsError from exc
            raise
        await self._audit_repo.record(
            module="patients",
            action="patients.created",
            entity_type="patient",
            entity_id=patient.id,
            actor_user_id=actor.id,
            metadata={"mr_number": patient.mr_number},
        )
        await self._session.commit()
        return await self._patient_repo.get_by_id(patient.id)

    async def get_patient(self, patient_id: UUID) -> Patient:
        patient = await self._patient_repo.get_by_id(patient_id)
        if patient is None:
            raise PatientNotFoundError
        return patient

    async def list_patients(
        self, *, search: str | None, sort_by: str, sort_desc: bool, page: int, page_size: int
    ) -> tuple[list[Patient], int]:
        sort_column = PATIENT_SORTABLE_COLUMNS[sort_by]
        return await self._patient_repo.search(
            search=search,
            sort_column=sort_column,
            sort_desc=sort_desc,
            limit=page_size,
            offset=(page - 1) * page_size,
        )

    async def update_patient(
        self, *, actor: User, patient_id: UUID, updates: dict[str, Any]
    ) -> Patient:
        """Partial update. `mr_number` is never accepted here — see this
        module's docstring; it is immutable once assigned."""
        patient = await self.get_patient(patient_id)
        if not updates:
            return patient

        if "cnic" in updates:
            new_cnic = updates["cnic"]
            if new_cnic is not None:
                existing = await self._patient_repo.get_by_cnic(new_cnic)
                if existing is not None and existing.id != patient.id:
                    raise PatientCnicAlreadyExistsError
            patient.cnic = new_cnic

        for field in (
            "full_name",
            "guardian_name",
            "gender",
            "age_years",
            "phone_number",
            "address",
        ):
            if field in updates:
                setattr(patient, field, updates[field])

        patient.updated_by = actor.id
        try:
            await self._patient_repo.add(patient)
        except IntegrityError as exc:
            await self._session.rollback()
            if unique_violation_constraint_name(exc) == _PATIENT_CNIC_CONSTRAINT:
                raise PatientCnicAlreadyExistsError from exc
            raise
        await self._audit_repo.record(
            module="patients",
            action="patients.updated",
            entity_type="patient",
            entity_id=patient.id,
            actor_user_id=actor.id,
            metadata={"fields": sorted(updates.keys())},
        )
        await self._session.commit()
        return await self._patient_repo.get_by_id(patient.id)

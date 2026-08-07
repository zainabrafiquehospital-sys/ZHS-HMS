"""Pydantic request/response schemas for the Patient module, mirroring
app/modules/auth/role_schemas.py's shape and conventions exactly
(partial-update `exclude_unset` semantics via UpdatePatientRequest,
`from_attributes` response models built via a `from_patient`
classmethod).

`mr_number` never appears in any request schema — it is always
server-generated (see PatientService.register_patient /
constants.py's module docstring), never client-supplied."""

from datetime import datetime
from enum import Enum as PyEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.patients.models import Patient, PatientGender


class PatientSortField(str, PyEnum):
    CREATED_AT = "created_at"
    FULL_NAME = "full_name"
    MR_NUMBER = "mr_number"


# ---------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------


class PatientIdentityFields(BaseModel):
    """Shared between create and update — see CreatePatientRequest /
    UpdatePatientRequest below for how each uses it. Public (no leading
    underscore) since the Reception module reuses this exact shape for
    its "register a new patient as part of visit registration" request,
    rather than duplicating the same field set a second time (see
    app/modules/reception/schemas.py).

    `age_years` is the patient's age in whole years as stated at
    registration — required, recorded directly, never calculated or
    derived from any date. There is no date-of-birth field anywhere in
    this schema.

    Only `full_name`, `age_years`, and `phone_number` are compulsory — a
    real high-volume OPD counter needs to register a visit in well under
    20 seconds; `guardian_name`, `gender`, `cnic`, and `address` remain
    fully supported (never removed) but are optional, fillable later via
    `UpdatePatientRequest` if/when they're known."""

    full_name: str = Field(min_length=1, max_length=150)
    guardian_name: str | None = Field(default=None, max_length=150)
    gender: PatientGender | None = Field(default=None, strict=False)
    age_years: int = Field(ge=0, le=150)
    phone_number: str = Field(min_length=6, max_length=20)
    cnic: str | None = Field(default=None, min_length=1, max_length=20)
    address: str | None = Field(default=None, max_length=2000)


class CreatePatientRequest(PatientIdentityFields):
    model_config = ConfigDict(strict=True)


class UpdatePatientRequest(BaseModel):
    """All fields optional for PATCH-style partial update — see
    app/modules/auth/user_schemas.py's module docstring for the
    `exclude_unset` semantics PatientService relies on."""

    model_config = ConfigDict(strict=True)

    full_name: str | None = Field(default=None, min_length=1, max_length=150)
    guardian_name: str | None = Field(default=None, max_length=150)
    gender: PatientGender | None = Field(default=None, strict=False)
    age_years: int | None = Field(default=None, ge=0, le=150)
    phone_number: str | None = Field(default=None, min_length=6, max_length=20)
    cnic: str | None = Field(default=None, min_length=1, max_length=20)
    address: str | None = Field(default=None, max_length=2000)


# ---------------------------------------------------------------------
# Responses
# ---------------------------------------------------------------------


class PatientOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    mr_number: str
    full_name: str
    guardian_name: str | None
    gender: PatientGender | None
    age_years: int
    phone_number: str
    cnic: str | None
    address: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_patient(cls, patient: Patient) -> "PatientOut":
        return cls(
            id=patient.id,
            mr_number=patient.mr_number,
            full_name=patient.full_name,
            guardian_name=patient.guardian_name,
            gender=patient.gender,
            age_years=patient.age_years,
            phone_number=patient.phone_number,
            cnic=patient.cnic,
            address=patient.address,
            created_at=patient.created_at,
            updated_at=patient.updated_at,
        )


class PatientSummary(BaseModel):
    """The minimal projection embedded anywhere another module's response
    references "which patient" without embedding a full PatientOut —
    mirrors app/shared/schema_types.py's RoleSummary precedent exactly.
    Used by the Visit module (Phase 6 §3: a Visit references a Patient)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    mr_number: str
    full_name: str

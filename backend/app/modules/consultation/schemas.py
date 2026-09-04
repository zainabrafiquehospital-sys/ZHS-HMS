"""Pydantic request/response schemas for the Consultation module."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.consultation.models import Consultation, ConsultationStatus
from app.shared.schema_types import LaxUUID


class StartConsultationRequest(BaseModel):
    model_config = ConfigDict(strict=True)

    visit_id: LaxUUID


class SendToVitalsRequest(BaseModel):
    model_config = ConfigDict(strict=True)

    reason: str | None = Field(default=None, max_length=200)


class CompleteConsultationRequest(BaseModel):
    model_config = ConfigDict(strict=True)

    notes: str | None = Field(default=None, max_length=5000)
    diagnosis: str | None = Field(default=None, max_length=2000)
    prescription: str | None = Field(default=None, max_length=5000)
    # H/O / C/O / Adv sections of the prescription slip (2026-09-03) —
    # every field on this request is optional; the doctor fills whichever
    # apply, exactly as with notes/diagnosis/prescription above.
    history_of: str | None = Field(default=None, max_length=5000)
    complaint_of: str | None = Field(default=None, max_length=5000)
    advised: str | None = Field(default=None, max_length=5000)


class CorrectConsultationRequest(BaseModel):
    """Post-completion clinical-content correction (2026-09-04) — the
    doctor amending a typo/mistake in *their own* already-completed
    consultation. Identical field set to `CompleteConsultationRequest`
    (the same six free-text clinical fields), partial: only the keys
    actually sent are written (`model_dump(exclude_unset=True)` at the
    call site). Structural facts (`status`, `doctor_user_id`,
    `visit_id`, `completed_at`) are deliberately absent — a correction
    never changes who ran the consultation or when it finished."""

    model_config = ConfigDict(strict=True)

    notes: str | None = Field(default=None, max_length=5000)
    diagnosis: str | None = Field(default=None, max_length=2000)
    prescription: str | None = Field(default=None, max_length=5000)
    history_of: str | None = Field(default=None, max_length=5000)
    complaint_of: str | None = Field(default=None, max_length=5000)
    advised: str | None = Field(default=None, max_length=5000)


class ConsultationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    visit_id: UUID
    doctor_user_id: UUID
    status: ConsultationStatus
    notes: str | None
    diagnosis: str | None
    prescription: str | None
    history_of: str | None
    complaint_of: str | None
    advised: str | None
    created_at: datetime
    completed_at: datetime | None

    @classmethod
    def from_consultation(cls, consultation: Consultation) -> "ConsultationOut":
        return cls(
            id=consultation.id,
            visit_id=consultation.visit_id,
            doctor_user_id=consultation.doctor_user_id,
            status=consultation.status,
            notes=consultation.notes,
            diagnosis=consultation.diagnosis,
            prescription=consultation.prescription,
            history_of=consultation.history_of,
            complaint_of=consultation.complaint_of,
            advised=consultation.advised,
            created_at=consultation.created_at,
            completed_at=consultation.completed_at,
        )


class ConsultationDoctorStatOut(BaseModel):
    """One row of `GET /consultations/stats/by-doctor`'s response — one
    doctor's "consultations completed" count. Not an ORM-backed schema,
    same plain-aggregate shape as
    app/modules/visits/schemas.py's `VisitCreatorStatOut`. Powers the
    Admin "Employee Accounts & Stats" page."""

    model_config = ConfigDict(strict=True)

    user_id: UUID
    count: int

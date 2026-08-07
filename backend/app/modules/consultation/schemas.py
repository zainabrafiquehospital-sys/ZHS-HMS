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


class ConsultationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    visit_id: UUID
    doctor_user_id: UUID
    status: ConsultationStatus
    notes: str | None
    diagnosis: str | None
    prescription: str | None
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
            created_at=consultation.created_at,
            completed_at=consultation.completed_at,
        )

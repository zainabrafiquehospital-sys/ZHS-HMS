"""Pydantic request/response schemas for the Vitals module."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.vitals.models import VitalsRecord
from app.shared.schema_types import LaxUUID


class RecordVitalsRequest(BaseModel):
    model_config = ConfigDict(strict=True)

    visit_id: LaxUUID
    systolic_bp: int | None = Field(default=None, ge=0, le=300)
    diastolic_bp: int | None = Field(default=None, ge=0, le=300)
    pulse_rate: int | None = Field(default=None, ge=0, le=300)
    temperature_celsius: float | None = Field(default=None, ge=20.0, le=45.0)
    weight_kg: float | None = Field(default=None, ge=0, le=500)
    height_cm: float | None = Field(default=None, ge=0, le=300)
    spo2_percent: int | None = Field(default=None, ge=0, le=100)
    notes: str | None = Field(default=None, max_length=2000)


class VitalsRecordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    visit_id: UUID
    consultation_id: UUID | None
    systolic_bp: int | None
    diastolic_bp: int | None
    pulse_rate: int | None
    temperature_celsius: float | None
    weight_kg: float | None
    height_cm: float | None
    spo2_percent: int | None
    notes: str | None
    created_at: datetime

    @classmethod
    def from_record(cls, record: VitalsRecord) -> "VitalsRecordOut":
        return cls(
            id=record.id,
            visit_id=record.visit_id,
            consultation_id=record.consultation_id,
            systolic_bp=record.systolic_bp,
            diastolic_bp=record.diastolic_bp,
            pulse_rate=record.pulse_rate,
            temperature_celsius=record.temperature_celsius,
            weight_kg=record.weight_kg,
            height_cm=record.height_cm,
            spo2_percent=record.spo2_percent,
            notes=record.notes,
            created_at=record.created_at,
        )

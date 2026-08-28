"""Pydantic request/response schemas for the Vitals module."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.vitals.models import TemperatureUnit, VitalsRecord
from app.shared.schema_types import LaxUUID


class RecordVitalsRequest(BaseModel):
    """`temperature` (2026-08-28 change, was `temperature_celsius`) is
    always a Fahrenheit reading now — going-forward only, see models.py's
    `VitalsRecord` docstring for the full rationale. There is
    deliberately no `temperature_unit` field here: the caller never
    chooses a unit, `VitalsService.record_vitals` always stamps
    `FAHRENHEIT` itself. `68.0-113.0` is the exact Fahrenheit equivalent
    of the previous `20.0-45.0` Celsius sanity range."""

    model_config = ConfigDict(strict=True)

    visit_id: LaxUUID
    systolic_bp: int | None = Field(default=None, ge=0, le=300)
    diastolic_bp: int | None = Field(default=None, ge=0, le=300)
    pulse_rate: int | None = Field(default=None, ge=0, le=300)
    temperature: float | None = Field(default=None, ge=68.0, le=113.0)
    weight_kg: float | None = Field(default=None, ge=0, le=500)
    height_cm: float | None = Field(default=None, ge=0, le=300)
    spo2_percent: int | None = Field(default=None, ge=0, le=100)
    notes: str | None = Field(default=None, max_length=2000)


class VitalsRecordOut(BaseModel):
    """`temperature_unit` (2026-08-28 addition) is `None` only when
    `temperature` itself is `None` (no reading taken) — otherwise always
    `celsius` (a historical record, from before this change) or
    `fahrenheit` (recorded after) — see models.py's `VitalsRecord`
    docstring. Every consumer of this field must read `temperature_unit`
    before displaying or classifying `temperature`, never assume one
    globally."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    visit_id: UUID
    consultation_id: UUID | None
    systolic_bp: int | None
    diastolic_bp: int | None
    pulse_rate: int | None
    temperature: float | None
    temperature_unit: TemperatureUnit | None
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
            temperature=record.temperature,
            temperature_unit=record.temperature_unit,
            weight_kg=record.weight_kg,
            height_cm=record.height_cm,
            spo2_percent=record.spo2_percent,
            notes=record.notes,
            created_at=record.created_at,
        )


class VitalsCreatorStatOut(BaseModel):
    """One row of `GET /vitals/stats/by-creator`'s response — one user's
    "vitals recorded" count. Not an ORM-backed schema, same plain-
    aggregate shape as app/modules/visits/schemas.py's
    `VisitCreatorStatOut`. Powers the Admin "Employee Accounts & Stats"
    page."""

    model_config = ConfigDict(strict=True)

    user_id: UUID
    count: int

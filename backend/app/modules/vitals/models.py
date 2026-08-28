"""SQLAlchemy models for the Vitals module (Phase 6 architecture §3:
"One set of captured vitals, scoped to either 'all standard vitals'
(Workflow A) or a specific requested subset (doctor mid-consult
request)."). Registered once into app/db/model_registry.py's centralized
model registry.

Every field is nullable — a single flexible record shape rather than a
rigid "all fields required" one, since a real vitals capture (especially
a doctor-requested detour, e.g. "just recheck BP") legitimately fills in
only a subset. `consultation_id` is the discriminator between the two
scoping cases the architecture describes: `NULL` for a Workflow-A intake
record captured before any Consultation exists, set for a record
captured because of a specific doctor-requested detour (see
VitalsService for how that distinction drives routing).

`temperature`/`temperature_unit` (2026-08-28 addition, confirmed design
— replacing the original `temperature_celsius`-only column): a real
bug fix, going-forward only. Every record captured from this change
onward stores a Fahrenheit reading (`temperature_unit=FAHRENHEIT`,
always server-stamped, never client-suppliable — see VitalsService.
record_vitals's own docstring). Every record captured *before* this
change keeps its exact original number, completely untouched, now
tagged `temperature_unit=CELSIUS` by a one-time migration backfill —
never reinterpreted or silently flipped to look like a Fahrenheit
value. `temperature` itself is deliberately unit-agnostic in name
(renamed from `temperature_celsius`, values never rewritten) precisely
because it can hold either unit depending on which era a given row is
from; every reader must always consult this row's own `temperature_unit`
before displaying or classifying its `temperature`, never assume one
globally. The two travel together — `CheckConstraint` below enforces
one is NULL if and only if the other is."""

from enum import Enum as PyEnum
from uuid import UUID

from sqlalchemy import CheckConstraint, Enum, ForeignKey, Index, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base_entity import BaseEntity


class TemperatureUnit(PyEnum):
    CELSIUS = "celsius"
    FAHRENHEIT = "fahrenheit"


class VitalsRecord(BaseEntity):
    __tablename__ = "vitals_record"
    __table_args__ = (
        Index("ix_vitals_record_visit_id", "visit_id"),
        Index("ix_vitals_record_consultation_id", "consultation_id"),
        CheckConstraint(
            "(temperature IS NULL) = (temperature_unit IS NULL)",
            name="ck_vitals_record_temperature_unit_paired",
        ),
    )

    visit_id: Mapped[UUID] = mapped_column(ForeignKey("visit.id"), nullable=False)
    consultation_id: Mapped[UUID | None] = mapped_column(ForeignKey("consultation.id"))
    systolic_bp: Mapped[int | None] = mapped_column()
    diastolic_bp: Mapped[int | None] = mapped_column()
    pulse_rate: Mapped[int | None] = mapped_column()
    # See this class's own docstring — unit-agnostic by design.
    temperature: Mapped[float | None] = mapped_column()
    temperature_unit: Mapped[TemperatureUnit | None] = mapped_column(
        Enum(
            TemperatureUnit,
            name="vitals_record_temperature_unit",
            native_enum=False,
            length=20,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
            create_constraint=True,
        ),
    )
    weight_kg: Mapped[float | None] = mapped_column()
    height_cm: Mapped[float | None] = mapped_column()
    spo2_percent: Mapped[int | None] = mapped_column()
    notes: Mapped[str | None] = mapped_column(Text())

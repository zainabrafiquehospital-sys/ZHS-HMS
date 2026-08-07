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
VitalsService for how that distinction drives routing)."""

from uuid import UUID

from sqlalchemy import ForeignKey, Index, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base_entity import BaseEntity


class VitalsRecord(BaseEntity):
    __tablename__ = "vitals_record"
    __table_args__ = (
        Index("ix_vitals_record_visit_id", "visit_id"),
        Index("ix_vitals_record_consultation_id", "consultation_id"),
    )

    visit_id: Mapped[UUID] = mapped_column(ForeignKey("visit.id"), nullable=False)
    consultation_id: Mapped[UUID | None] = mapped_column(ForeignKey("consultation.id"))
    systolic_bp: Mapped[int | None] = mapped_column()
    diastolic_bp: Mapped[int | None] = mapped_column()
    pulse_rate: Mapped[int | None] = mapped_column()
    temperature_celsius: Mapped[float | None] = mapped_column()
    weight_kg: Mapped[float | None] = mapped_column()
    height_cm: Mapped[float | None] = mapped_column()
    spo2_percent: Mapped[int | None] = mapped_column()
    notes: Mapped[str | None] = mapped_column(Text())

"""SQLAlchemy models for the Consultation module (Phase 6 architecture
§5.4: "the doctor's active clinical session against a Visit"). Registered
once into app/db/model_registry.py's centralized model registry.

Only `AWAITING_VITALS` (of §5.4's full status set) is implemented — the
architecture's own future-reserved `AWAITING_LAB`/`AWAITING_RADIOLOGY`
have no owning module yet (Lab/Radiology are explicitly out of scope for
this build) and are deliberately not modeled here; adding them later is
an additive enum change, not a redesign."""

from datetime import datetime
from enum import Enum as PyEnum
from uuid import UUID

from sqlalchemy import Enum, ForeignKey, Index, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base_entity import BaseEntity


class ConsultationStatus(PyEnum):
    IN_PROGRESS = "in_progress"
    AWAITING_VITALS = "awaiting_vitals"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class Consultation(BaseEntity):
    __tablename__ = "consultation"
    __table_args__ = (
        # At most one *active* (non-terminal) Consultation per Visit —
        # mirrors app/modules/queue/models.py's identical single-active
        # invariant, backed by the database, not only service logic.
        Index(
            "ix_consultation_visit_id_active",
            "visit_id",
            unique=True,
            postgresql_where=text(
                "deleted_at IS NULL AND status IN ('in_progress', 'awaiting_vitals')"
            ),
        ),
        Index("ix_consultation_visit_id", "visit_id"),
        Index("ix_consultation_doctor_user_id_status", "doctor_user_id", "status"),
    )

    visit_id: Mapped[UUID] = mapped_column(ForeignKey("visit.id"), nullable=False)
    doctor_user_id: Mapped[UUID] = mapped_column(ForeignKey("user.id"), nullable=False)
    status: Mapped[ConsultationStatus] = mapped_column(
        Enum(
            ConsultationStatus,
            name="consultation_status",
            native_enum=False,
            length=20,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
            create_constraint=True,
        ),
        nullable=False,
        default=ConsultationStatus.IN_PROGRESS,
    )
    notes: Mapped[str | None] = mapped_column(Text())
    diagnosis: Mapped[str | None] = mapped_column(Text())
    prescription: Mapped[str | None] = mapped_column(Text())
    completed_at: Mapped[datetime | None] = mapped_column()

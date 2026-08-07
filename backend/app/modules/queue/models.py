"""SQLAlchemy models for the Queue module (Phase 6 architecture §3:
"Where a Visit is *right now* ... and why. Owned separately from Visit
so routing logic doesn't live inside the clinical aggregate.").
Registered once into app/db/model_registry.py's centralized model
registry.

A `QueueEntry` row is one leg of a Visit's journey through the hospital
— never mutated to represent a *new* leg, only closed (`left_at` set,
`status` moved to a terminal state) when the Visit moves on, with a
fresh row created for the new destination. This is what makes "queue
history is preserved" (§18) fall out of the model directly rather than
needing a separate history table: the full sequence of legs a Visit took
is just every QueueEntry row for that `visit_id`, ordered by
`created_at`."""

from datetime import datetime
from enum import Enum as PyEnum
from uuid import UUID

from sqlalchemy import Enum, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base_entity import BaseEntity


class QueueDestination(PyEnum):
    """The three destinations Phase 6 §5.1/§5.2 route a Visit between for
    the MVP OPD flow. Lab/Radiology (§5.4's future-reserved Consultation
    statuses) have no queue destination yet — out of scope until those
    modules exist."""

    RECEPTION = "reception"
    VITALS = "vitals"
    DOCTOR = "doctor"


class QueueEntryStatus(PyEnum):
    WAITING = "waiting"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class QueueEntry(BaseEntity):
    __tablename__ = "queue_entry"
    __table_args__ = (
        # At most one *active* (still-open) leg per Visit at any time —
        # a real database constraint, not just a service-layer check,
        # backing QueueService's "close the current leg before opening a
        # new one" invariant.
        Index(
            "ix_queue_entry_visit_id_active",
            "visit_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL AND left_at IS NULL"),
        ),
        Index("ix_queue_entry_visit_id", "visit_id"),
        Index("ix_queue_entry_destination_status", "destination", "status"),
    )

    visit_id: Mapped[UUID] = mapped_column(ForeignKey("visit.id"), nullable=False)
    destination: Mapped[QueueDestination] = mapped_column(
        Enum(
            QueueDestination,
            name="queue_destination",
            native_enum=False,
            length=20,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
            create_constraint=True,
        ),
        nullable=False,
    )
    status: Mapped[QueueEntryStatus] = mapped_column(
        Enum(
            QueueEntryStatus,
            name="queue_entry_status",
            native_enum=False,
            length=20,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
            create_constraint=True,
        ),
        nullable=False,
        default=QueueEntryStatus.WAITING,
    )
    reason: Mapped[str | None] = mapped_column(String(200))
    left_at: Mapped[datetime | None] = mapped_column()

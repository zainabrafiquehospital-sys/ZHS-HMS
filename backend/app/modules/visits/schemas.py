"""Pydantic request/response schemas for the Visit module — see
app/modules/patients/schemas.py's identical module docstring for
conventions. There is deliberately no `UpdateVisitRequest` — Visit has
no freely-editable fields; every change to it after creation is one of
VisitService's named `mark_*` status transitions, called by the module
whose business action caused it (Vitals, Consultation, Billing), never
a generic PATCH a client could use to set an arbitrary status."""

from datetime import datetime
from decimal import Decimal
from enum import Enum as PyEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.modules.visits.models import Visit, VisitStatus


class VisitSortField(str, PyEnum):
    CREATED_AT = "created_at"
    STATUS = "status"


class VisitOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    queue_token: str
    patient_id: UUID
    # None means "unclaimed" — no online doctor was available at
    # registration time; any doctor may claim it by starting the
    # consultation (see consultation/service.py's `start_consultation`).
    doctor_user_id: UUID | None
    procedure: str
    amount: Decimal
    vitals_required: bool
    status: VisitStatus
    # Who registered this Visit — BaseEntity's own audit-on-write column
    # (see shared/base_entity.py), already populated correctly by
    # VisitService.register_visit for every Visit; simply never surfaced
    # in this response shape until the Admin overview needed to show
    # "which receptionist booked this" (see features/admin's own
    # "Booked By" column). Nullable only because BaseEntity's FK is
    # `ON DELETE SET NULL` — a hard-deleted user leaves existing Visits
    # with no actor on record rather than failing to load them.
    created_by: UUID | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_visit(cls, visit: Visit) -> "VisitOut":
        return cls(
            id=visit.id,
            queue_token=visit.queue_token,
            patient_id=visit.patient_id,
            doctor_user_id=visit.doctor_user_id,
            procedure=visit.procedure,
            amount=visit.amount,
            vitals_required=visit.vitals_required,
            status=visit.status,
            created_by=visit.created_by,
            created_at=visit.created_at,
            updated_at=visit.updated_at,
        )


class VisitSummary(BaseModel):
    """The minimal projection embedded anywhere another module's response
    references "which visit" without embedding a full VisitOut — mirrors
    app/modules/patients/schemas.py's PatientSummary precedent exactly.
    Used by the not-yet-built Queue/Consultation/Billing modules."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    queue_token: str
    status: VisitStatus


class VisitCreatorStatOut(BaseModel):
    """One row of `GET /visits/stats/by-creator`'s response — one user's
    "visits registered" count and total `amount` across every Visit they
    created. Not an ORM-backed schema (constructed directly from
    `VisitRepository.count_and_revenue_by_creator`'s `{user_id: (count,
    revenue)}` dict, not `from_attributes`) — same plain-aggregate shape
    convention as dashboard/schemas.py's `DoctorDashboardOut`, and the
    same `(count, revenue)` pair `MedicineBillCreatorStatOut` already
    carries for medicine bills. Powers the Admin "Employee Accounts &
    Stats" page's per-receptionist "visits registered" column AND
    Reception's own "My Revenue"/"My Slips" tiles (that receptionist's
    own row, looked up by their own user id)."""

    model_config = ConfigDict(strict=True)

    user_id: UUID
    count: int
    revenue: Decimal

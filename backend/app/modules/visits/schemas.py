"""Pydantic request/response schemas for the Visit module — see
app/modules/patients/schemas.py's identical module docstring for
conventions. There is deliberately no `UpdateVisitRequest` here, and
this module's own (read-only) router still exposes no update/delete
endpoint of any kind — every status change remains one of VisitService's
named `mark_*` transitions, never a generic PATCH a client could use to
set an arbitrary status. `VisitService.update_visit_details`/
`delete_visit` (2026-08-19 addition, for admin data correction) are the
one narrow exception to "no freely-editable fields" — `procedure`/
`amount` only, never status — and are deliberately reached exclusively
through Reception's own admin-only composite endpoints
(`PATCH`/`DELETE /reception/visits/{id}`, see reception/schemas.py's
`AdminUpdateVisitRequest`), not through anything defined in this file.

`Procedure`/`VisitProcedureItem` schemas (2026-08-21 addition) — the
admin-managed procedure catalog and its per-visit line items, mirroring
app/modules/pharmacy/schemas.py's Medicine/MedicineBillItem shapes. See
models.py's module docstring for the full "coexisting catalog-linked
and manual entries, never retrofitted onto a pre-existing Visit"
rationale."""

from datetime import datetime
from decimal import Decimal
from enum import Enum as PyEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.visits.models import Procedure, Visit, VisitProcedureItem, VisitStatus
from app.shared.schema_types import LaxDecimal, LaxUUID


class VisitSortField(str, PyEnum):
    CREATED_AT = "created_at"
    STATUS = "status"


class ProcedureSortField(str, PyEnum):
    CREATED_AT = "created_at"
    NAME = "name"


# ---------------------------------------------------------------------
# Procedure catalog (2026-08-21 addition) — Admin-only management,
# mirrors app/modules/pharmacy/schemas.py's CreateMedicineRequest/
# UpdateMedicineRequest/MedicineOut almost exactly (no category).
# ---------------------------------------------------------------------


class CreateProcedureRequest(BaseModel):
    model_config = ConfigDict(strict=True)

    name: str = Field(min_length=1, max_length=200)
    price: LaxDecimal = Field(gt=0)


class UpdateProcedureRequest(BaseModel):
    """All fields optional for PATCH-style partial update — same
    `exclude_unset` semantics as pharmacy/schemas.py's
    `UpdateMedicineRequest`."""

    model_config = ConfigDict(strict=True)

    name: str | None = Field(default=None, min_length=1, max_length=200)
    price: LaxDecimal | None = Field(default=None, gt=0)
    is_active: bool | None = None


class ProcedureOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    price: Decimal
    is_active: bool
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_procedure(cls, procedure: Procedure) -> "ProcedureOut":
        return cls(
            id=procedure.id,
            name=procedure.name,
            price=procedure.price,
            is_active=procedure.is_active,
            created_at=procedure.created_at,
            updated_at=procedure.updated_at,
        )


# ---------------------------------------------------------------------
# VisitProcedureItem — one procedure line on a Visit registered from
# 2026-08-21 onward (2026-08-21 addition). Coexists with `Visit.
# procedure`/`Visit.amount`, which stay untouched for every pre-existing
# Visit — see models.py's module docstring for the full rationale.
# ---------------------------------------------------------------------


class VisitProcedureItemRequest(BaseModel):
    """Exactly one of two shapes, enforced below: a catalog-linked
    entry (`procedure_id` set, `name`/`amount` both omitted — its name
    and price are always server-derived from the catalog, mirroring
    `MedicineBillLineItemRequest`'s identical price-integrity rule) or a
    manual/free-typed entry (`procedure_id` omitted, `name` and
    `amount` both required). Rejecting `name`/`amount` outright for a
    catalog-linked entry, rather than silently ignoring them, means a
    client can never be confused about whether a submitted price
    actually took effect — it never would have."""

    model_config = ConfigDict(strict=True)

    procedure_id: LaxUUID | None = None
    name: str | None = Field(default=None, min_length=1, max_length=200)
    amount: LaxDecimal | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def _exactly_one_shape(self) -> "VisitProcedureItemRequest":
        if self.procedure_id is not None:
            if self.name is not None or self.amount is not None:
                raise ValueError(
                    "Do not send name/amount alongside procedure_id — a catalog-linked "
                    "procedure's name and price are always taken from the catalog."
                )
        elif self.name is None or self.amount is None:
            raise ValueError(
                "A manual (non-catalog) procedure entry requires both name and amount."
            )
        return self


class VisitProcedureItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    procedure_id: UUID | None
    name: str
    amount: Decimal

    @classmethod
    def from_item(cls, item: VisitProcedureItem) -> "VisitProcedureItemOut":
        return cls(id=item.id, procedure_id=item.procedure_id, name=item.name, amount=item.amount)


class VisitOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    queue_token: str
    patient_id: UUID
    # None means "unclaimed" — no online doctor was available at
    # registration time; any doctor may claim it by starting the
    # consultation (see consultation/service.py's `start_consultation`).
    doctor_user_id: UUID | None
    # For a visit registered before 2026-08-21 (i.e. `procedure_items`
    # below is empty): the real, single procedure name/amount, exactly
    # as they have always been — every reader falls back to displaying
    # these two fields directly in that case. For a visit registered
    # from 2026-08-21 onward (`procedure_items` non-empty): `procedure`
    # holds `ITEMIZED_PROCEDURE_PLACEHOLDER` and must never be
    # displayed — `amount` still holds the real, correct total (see
    # models.py's own docstrings for the full mechanism either way).
    procedure: str
    amount: Decimal
    discount_amount: Decimal
    discount_reason: str | None
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
    # Empty for every visit registered before 2026-08-21 — permanently,
    # by design (see models.py's `VisitProcedureItem` docstring) — and
    # for every reader (print, every list/detail view, the admin edit
    # dialog) the one and only signal for which of `procedure`/`amount`
    # above vs. this list is the real record of what this visit billed.
    procedure_items: list[VisitProcedureItemOut] = Field(default_factory=list)

    @classmethod
    def from_visit(
        cls, visit: Visit, procedure_items: list[VisitProcedureItem] | None = None
    ) -> "VisitOut":
        return cls(
            id=visit.id,
            queue_token=visit.queue_token,
            patient_id=visit.patient_id,
            doctor_user_id=visit.doctor_user_id,
            procedure=visit.procedure,
            amount=visit.amount,
            discount_amount=visit.discount_amount,
            discount_reason=visit.discount_reason,
            vitals_required=visit.vitals_required,
            status=visit.status,
            created_by=visit.created_by,
            created_at=visit.created_at,
            updated_at=visit.updated_at,
            procedure_items=[
                VisitProcedureItemOut.from_item(item) for item in (procedure_items or [])
            ],
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

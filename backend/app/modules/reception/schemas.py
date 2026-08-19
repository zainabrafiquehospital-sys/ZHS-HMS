"""Pydantic request/response schemas for the Reception module — the
composite "register a visit" action (Phase 6 architecture §6, revised
for fast registration): exactly one of an existing `patient_id` or a
full `new_patient` identity block, plus procedure + amount, and the
Yes/No vitals-required decision that sets the Visit's initial queue
destination. There is deliberately no doctor-selection field — doctor
assignment is always automatic (see ReceptionService.register_visit's
docstring)."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.patients.models import PatientGender
from app.modules.patients.schemas import PatientIdentityFields, PatientOut
from app.modules.queue.schemas import QueueEntryOut
from app.modules.visits.schemas import VisitOut
from app.shared.schema_types import LaxDecimal, LaxUUID


class RegisterVisitRequest(BaseModel):
    model_config = ConfigDict(strict=True)

    patient_id: LaxUUID | None = None
    new_patient: PatientIdentityFields | None = None
    procedure: str = Field(min_length=1, max_length=200)
    amount: LaxDecimal = Field(gt=0)
    vitals_required: bool
    # Optional flat discount off `amount`, applied at registration time
    # only (2026-08-19 addition) — same shape as
    # app/modules/pharmacy/schemas.py's CreateMedicineBillRequest.
    # discount_amount/discount_reason: `discount_reason` is always
    # optional here too, even when `discount_amount > 0` (see
    # VisitService.register_visit's docstring for the full mechanism —
    # `amount` ends up already post-discount on the stored Visit).
    discount_amount: LaxDecimal = Field(default=Decimal("0"), ge=0)
    discount_reason: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def _exactly_one_patient_source(self) -> "RegisterVisitRequest":
        """Reception either pulls up an existing patient or registers a
        new one in the same action — never both, never neither (Phase 6
        §6: "Patient registration (create or pull up a Patient)")."""
        has_existing = self.patient_id is not None
        has_new = self.new_patient is not None
        if has_existing == has_new:
            raise ValueError("Provide exactly one of patient_id or new_patient, not both/neither.")
        return self


class CancelVisitRequest(BaseModel):
    model_config = ConfigDict(strict=True)

    reason: str | None = Field(default=None, max_length=500)


class RegisterVisitResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    patient: PatientOut
    visit: VisitOut
    queue_entry: QueueEntryOut


# ---------------------------------------------------------------------
# Admin data correction (2026-08-19 addition) — see this module's
# router.py and service.py for the full RBAC/business-rule story.
# ---------------------------------------------------------------------


class AdminUpdateVisitRequest(BaseModel):
    """A single flat "Edit Slip" form covering both halves of what a
    printed registration slip actually shows — Visit's own two
    correctable fields (`procedure`/`amount`) and Patient's editable
    identity fields (the exact same set `UpdatePatientRequest` already
    validates, deliberately not re-declared as a shared class the way
    `PatientIdentityFields` is: unlike create-vs-update on Patient
    alone, there is no second call site that would ever need this exact
    combined shape). Every field optional/PATCH-style (`exclude_unset`)
    — ReceptionService.admin_update_visit splits this into the two
    already-existing, already-tested update paths (`PatientService.
    update_patient`, `VisitService.update_visit_details`) rather than
    this schema (or the service) reimplementing either one's validation.
    No field-name collision between the two halves, so a flat shape is
    unambiguous — no `visit: {...}` / `patient: {...}` nesting needed."""

    model_config = ConfigDict(strict=True)

    # Visit's own fields.
    procedure: str | None = Field(default=None, min_length=1, max_length=200)
    amount: LaxDecimal | None = Field(default=None, gt=0)

    # Patient's fields — same constraints as UpdatePatientRequest.
    full_name: str | None = Field(default=None, min_length=1, max_length=150)
    guardian_name: str | None = Field(default=None, max_length=150)
    gender: PatientGender | None = Field(default=None, strict=False)
    age_years: int | None = Field(default=None, ge=0, le=150)
    phone_number: str | None = Field(default=None, min_length=6, max_length=20)
    cnic: str | None = Field(default=None, min_length=1, max_length=20)
    address: str | None = Field(default=None, max_length=2000)


class AdminUpdateVisitResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    patient: PatientOut
    visit: VisitOut


# ---------------------------------------------------------------------
# "My Revenue" (2026-08-19 addition) — own-scoped only, see this
# module's router.py/service.py for the full RBAC/mechanism story.
# ---------------------------------------------------------------------


class ReceptionRevenueOut(BaseModel):
    """A receptionist's own revenue — visits and medicine bills broken
    out separately plus a combined total, always capped to roughly the
    last 24 hours (2026-08-19 fix). `cleared_at` reports the effective
    window start — `max(last manual "Clear Revenue" action, now - 24h)`
    — so it is always a real, recent timestamp, never `None` and never
    an all-time cumulative view (see ReceptionService.get_own_revenue's
    own docstring for the full mechanism). Never anyone else's revenue
    — this response shape carries no `user_id` field at all, since the
    caller can only ever be asking about themselves (see
    ReceptionService.get_own_revenue: always `actor.id`, never a
    request parameter)."""

    model_config = ConfigDict(strict=True)

    visits_count: int
    visits_revenue: Decimal
    medicine_bill_count: int
    medicine_revenue: Decimal
    total_revenue: Decimal
    cleared_at: datetime


class ClearRevenueResponse(BaseModel):
    model_config = ConfigDict(strict=True)

    cleared_at: datetime

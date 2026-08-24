"""Pydantic request/response schemas for the Reception module — the
composite "register a visit" action (Phase 6 architecture §6, revised
for fast registration): exactly one of an existing `patient_id` or a
full `new_patient` identity block, plus one or more procedure line
items, and the Yes/No vitals-required decision that sets the Visit's
initial queue destination. Doctor assignment defaults to automatic
(see ReceptionService.register_visit's docstring) but an optional
explicit `doctor_user_id` (2026-08-24 addition) can override it — see
`RegisterVisitRequest.doctor_user_id`'s own comment and
`DoctorSelectionOut` below, which powers the selection dropdown.

`procedures` (2026-08-21 addition, replacing the old flat `procedure`/
`amount` fields) is one or more `VisitProcedureItemRequest`s — see that
schema's own docstring for the catalog-linked-vs-manual shape. Every
visit registered from now on has at least one; see
app/modules/visits/models.py's `VisitProcedureItem` docstring for why
this never touches any visit registered before today."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.auth.models import User
from app.modules.patients.models import PatientGender
from app.modules.patients.schemas import PatientIdentityFields, PatientOut
from app.modules.queue.schemas import QueueEntryOut
from app.modules.visits.schemas import VisitOut, VisitProcedureItemRequest
from app.shared.payment_method import PaymentMethod
from app.shared.schema_types import LaxDecimal, LaxUUID


class RegisterVisitRequest(BaseModel):
    model_config = ConfigDict(strict=True)

    patient_id: LaxUUID | None = None
    new_patient: PatientIdentityFields | None = None
    procedures: list[VisitProcedureItemRequest] = Field(min_length=1)
    vitals_required: bool
    # Explicit doctor selection (2026-08-24 addition — RegisterVisitForm.jsx's
    # doctor-selection dropdown). `None` (the default, and still the
    # common case) preserves today's behavior exactly: auto-assign the
    # least-busy online doctor, or leave unassigned if none is online
    # (see ReceptionService.register_visit's own docstring). A provided
    # value bypasses auto-assignment and is validated server-side
    # against ReceptionRepository.get_doctor_by_id, not trusted as-is.
    doctor_user_id: LaxUUID | None = None
    # Optional flat discount off the procedures' combined subtotal,
    # applied at registration time only (2026-08-19 addition, unaffected
    # by the 2026-08-21 itemization — see VisitService.register_visit's
    # docstring for the full mechanism, now validated against the sum
    # of `procedures` rather than a single typed amount). Same shape as
    # app/modules/pharmacy/schemas.py's CreateMedicineBillRequest.
    # discount_amount/discount_reason: `discount_reason` is always
    # optional here too, even when `discount_amount > 0`.
    discount_amount: LaxDecimal = Field(default=Decimal("0"), ge=0)
    discount_reason: str | None = Field(default=None, max_length=200)
    # Registration-charge payment (2026-08-22 addition) — both required,
    # unlike Billing's/Pharmacy's optional equivalents: a real payment
    # (full or partial, never zero) is always collected at registration,
    # see VisitService.register_visit's own docstring for the full
    # mechanism. `initial_payment_amount` is validated server-side
    # against the post-discount net total (`VisitPaymentExceedsBalanceError`
    # if it exceeds it), never against the pre-discount subtotal.
    initial_payment_amount: LaxDecimal = Field(gt=0)
    initial_payment_method: PaymentMethod = Field(strict=False)

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
    printed registration slip actually shows — Visit's own correctable
    fields and Patient's editable identity fields (the exact same set
    `UpdatePatientRequest` already validates, deliberately not
    re-declared as a shared class the way `PatientIdentityFields` is:
    unlike create-vs-update on Patient alone, there is no second call
    site that would ever need this exact combined shape). Every field
    optional/PATCH-style (`exclude_unset`) — ReceptionService.
    admin_update_visit splits this into the already-existing update
    paths (`PatientService.update_patient`, `VisitService.
    update_visit_details`) rather than this schema (or the service)
    reimplementing either one's validation. No field-name collision
    between the two halves, so a flat shape is unambiguous — no
    `visit: {...}` / `patient: {...}` nesting needed.

    Visit's own fields (2026-08-21 revision) now bifurcate on which
    kind of visit is being edited — never both meaningful on the same
    call, enforced at the service layer (VisitService.
    update_visit_details), not here, since which one applies depends on
    the *target visit's own current state* (whether it already has
    `VisitProcedureItem` rows), not on anything this request alone can
    know:
    - `procedure`/`amount`: the original flat fields, exactly as they
      have always worked — apply only to a visit registered before
      2026-08-21 (which has no procedure items to edit at all; see
      models.py's `VisitProcedureItem` docstring for why that's never
      retrofitted).
    - `procedures`: replaces a visit's *entire* procedure-item set in
      one call — applies only to a visit registered from 2026-08-21
      onward. Deliberately does not touch `discount_amount`/
      `discount_reason` at all (a confirmed, explicit scope decision —
      discount correction stays a fully separate concern from procedure
      correction, exactly as `update_visit_details` has never touched
      discount either)."""

    model_config = ConfigDict(strict=True)

    # Visit's own fields — see this schema's own docstring for the
    # legacy-vs-itemized bifurcation.
    procedure: str | None = Field(default=None, min_length=1, max_length=200)
    amount: LaxDecimal | None = Field(default=None, gt=0)
    procedures: list[VisitProcedureItemRequest] | None = Field(default=None, min_length=1)

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


# ---------------------------------------------------------------------
# Doctor selection (2026-08-24 addition) — GET /reception/doctors, the
# minimal list backing RegisterVisitForm.jsx's optional doctor dropdown.
# Deliberately narrow: only what a selection UI needs (id, name, online
# status), never the full admin User shape GET /users returns — see
# ReceptionRepository.list_doctors_for_selection's own docstring for why
# this reuses `reception:register_visit` rather than `users:read`.
# ---------------------------------------------------------------------


class DoctorSelectionOut(BaseModel):
    model_config = ConfigDict(strict=True)

    id: UUID
    full_name: str
    is_online: bool

    @classmethod
    def from_user(cls, user: User, is_online: bool) -> "DoctorSelectionOut":
        return cls(id=user.id, full_name=user.full_name, is_online=is_online)

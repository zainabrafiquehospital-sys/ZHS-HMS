"""Pydantic request/response schemas for the Reception module — the
composite "register a visit" action (Phase 6 architecture §6, revised
for fast registration): exactly one of an existing `patient_id` or a
full `new_patient` identity block, plus procedure + amount, and the
Yes/No vitals-required decision that sets the Visit's initial queue
destination. There is deliberately no doctor-selection field — doctor
assignment is always automatic (see ReceptionService.register_visit's
docstring)."""

from pydantic import BaseModel, ConfigDict, Field, model_validator

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

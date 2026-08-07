"""Pydantic response schema for the Search module."""

from pydantic import BaseModel, ConfigDict

from app.modules.patients.models import Patient
from app.modules.patients.schemas import PatientSummary
from app.modules.visits.models import Visit
from app.modules.visits.schemas import VisitSummary


class SearchResultOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    patients: list[PatientSummary]
    visit: VisitSummary | None

    @classmethod
    def from_results(cls, patients: list[Patient], visit: Visit | None) -> "SearchResultOut":
        return cls(
            patients=[PatientSummary.model_validate(patient) for patient in patients],
            visit=VisitSummary.model_validate(visit) if visit else None,
        )

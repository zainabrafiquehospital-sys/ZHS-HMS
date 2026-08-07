"""FastAPI dependency-injection provider for the Search module — see
app/modules/reception/dependencies.py's identical composition pattern."""

from fastapi import Depends

from app.modules.patients.dependencies import get_patient_service
from app.modules.patients.service import PatientService
from app.modules.search.service import SearchService
from app.modules.visits.dependencies import get_visit_service
from app.modules.visits.service import VisitService


def get_search_service(
    patient_service: PatientService = Depends(get_patient_service),
    visit_service: VisitService = Depends(get_visit_service),
) -> SearchService:
    return SearchService(patient_service=patient_service, visit_service=visit_service)

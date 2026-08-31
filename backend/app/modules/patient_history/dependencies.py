"""FastAPI dependency-injection provider for the Patient History module —
see app/modules/search/dependencies.py's identical composition pattern
(a purely-read-only aggregator wiring in every service it reports on,
owning no repository of its own)."""

from fastapi import Depends

from app.modules.billing.dependencies import get_billing_service
from app.modules.billing.service import BillingService
from app.modules.consultation.dependencies import get_consultation_service
from app.modules.consultation.service import ConsultationService
from app.modules.lab.dependencies import get_lab_service
from app.modules.lab.service import LabService
from app.modules.patient_history.service import PatientHistoryService
from app.modules.patients.dependencies import get_patient_service
from app.modules.patients.service import PatientService
from app.modules.pharmacy.dependencies import get_pharmacy_service
from app.modules.pharmacy.service import PharmacyService
from app.modules.visits.dependencies import get_visit_service
from app.modules.visits.service import VisitService
from app.modules.vitals.dependencies import get_vitals_service
from app.modules.vitals.service import VitalsService


def get_patient_history_service(
    patient_service: PatientService = Depends(get_patient_service),
    visit_service: VisitService = Depends(get_visit_service),
    vitals_service: VitalsService = Depends(get_vitals_service),
    consultation_service: ConsultationService = Depends(get_consultation_service),
    billing_service: BillingService = Depends(get_billing_service),
    lab_service: LabService = Depends(get_lab_service),
    pharmacy_service: PharmacyService = Depends(get_pharmacy_service),
) -> PatientHistoryService:
    return PatientHistoryService(
        patient_service=patient_service,
        visit_service=visit_service,
        vitals_service=vitals_service,
        consultation_service=consultation_service,
        billing_service=billing_service,
        lab_service=lab_service,
        pharmacy_service=pharmacy_service,
    )

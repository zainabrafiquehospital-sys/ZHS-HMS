"""HTTP endpoint for the Patient History module: `GET /patients/{patient_id}
/history` — a single, cross-module aggregated timeline for one patient
(visits, vitals, consultations, billing, lab bills, pharmacy bills),
additive alongside (never replacing) `GET /visits?patient_id=` and
`GET /vitals/patients/{id}/history`, which stay exactly as they are for
their own existing callers.

Gated on the new `patients:history:read` permission (see
app/modules/patients/constants.py's own docstring) to even reach this
endpoint at all — but that permission alone decides nothing about
*which* sections come back. Each section is independently re-checked
against the actor's own other permissions, mirroring the exact
permission that section's own reader-facing GET route already requires
elsewhere in the app:
  - `visits`          -> `visits:read`        (GET /visits)
  - `vitals`           -> `vitals:read`         (GET /vitals/visits/{id})
  - `consultations`    -> `consultation:read`   (GET /consultations/{id})
  - `invoices`         -> `billing:read`        (GET /visits/{id}/invoices)
  - `lab_bills`         -> `lab:read`            (GET /lab/bills)
  - `pharmacy_bills`    -> `pharmacy:read`        (GET /pharmacy/bills)
A section the actor can't independently read stays `null` in the
response rather than 403ing the whole request — this endpoint's entire
point is that different roles legitimately see different slices of the
same patient's history (e.g. Reception sees Lab/Pharmacy but not
Vitals/Consultation; Doctor sees Vitals/Consultation but not
Billing/Lab/Pharmacy — confirmed directly against this app's actual
RBAC grants, not assumed), never a hard failure just because one
section isn't visible to this particular caller."""

from uuid import UUID

from fastapi import APIRouter, Depends

from app.modules.auth.dependencies import get_auth_service, require_permission
from app.modules.auth.models import User
from app.modules.auth.service import AuthService
from app.modules.billing.constants import PERMISSION_BILLING_READ
from app.modules.consultation.constants import PERMISSION_CONSULTATION_READ
from app.modules.consultation.schemas import ConsultationOut
from app.modules.lab.constants import PERMISSION_LAB_READ
from app.modules.lab.schemas import LabBillSummaryOut
from app.modules.patient_history.dependencies import get_patient_history_service
from app.modules.patient_history.schemas import PatientHistoryInvoiceOut, PatientHistoryOut
from app.modules.patient_history.service import PatientHistoryService
from app.modules.patients.constants import PERMISSION_PATIENTS_HISTORY_READ
from app.modules.patients.schemas import PatientOut
from app.modules.pharmacy.constants import PERMISSION_PHARMACY_READ
from app.modules.pharmacy.schemas import MedicineBillSummaryOut
from app.modules.visits.constants import PERMISSION_VISITS_READ
from app.modules.visits.schemas import VisitOut
from app.modules.vitals.constants import PERMISSION_VITALS_READ
from app.modules.vitals.schemas import VitalsRecordOut
from app.shared.envelope import success_envelope

router = APIRouter(prefix="/patients", tags=["patient-history"])


@router.get("/{patient_id}/history")
async def get_patient_history(
    patient_id: UUID,
    history_service: PatientHistoryService = Depends(get_patient_history_service),
    auth_service: AuthService = Depends(get_auth_service),
    actor: User = Depends(require_permission(PERMISSION_PATIENTS_HISTORY_READ)),
) -> dict:
    held = auth_service.effective_permission_codes(actor)
    include_visits = PERMISSION_VISITS_READ in held
    include_vitals = PERMISSION_VITALS_READ in held
    include_consultations = PERMISSION_CONSULTATION_READ in held
    include_invoices = PERMISSION_BILLING_READ in held
    include_lab_bills = PERMISSION_LAB_READ in held
    include_pharmacy_bills = PERMISSION_PHARMACY_READ in held

    data = await history_service.get_history(
        patient_id=patient_id,
        include_vitals=include_vitals,
        include_consultations=include_consultations,
        include_invoices=include_invoices,
        include_lab_bills=include_lab_bills,
        include_pharmacy_bills=include_pharmacy_bills,
    )

    visits_out = None
    if include_visits:
        visit_ids = [visit.id for visit in data.visits]
        items_by_visit = await history_service.get_visit_procedure_items(visit_ids)
        visits_out = [
            VisitOut.from_visit(visit, items_by_visit.get(visit.id, [])) for visit in data.visits
        ]

    response = PatientHistoryOut(
        patient=PatientOut.from_patient(data.patient),
        visits=visits_out,
        vitals=(
            [VitalsRecordOut.from_record(record) for record in data.vitals]
            if data.vitals is not None
            else None
        ),
        consultations=(
            [
                ConsultationOut.from_consultation(consultation)
                for consultation in data.consultations
            ]
            if data.consultations is not None
            else None
        ),
        invoices=(
            [PatientHistoryInvoiceOut.from_invoice(invoice) for invoice in data.invoices]
            if data.invoices is not None
            else None
        ),
        lab_bills=(
            [
                LabBillSummaryOut.from_bill(bill, item_count, payment_methods)
                for bill, item_count, payment_methods in data.lab_bills
            ]
            if data.lab_bills is not None
            else None
        ),
        pharmacy_bills=(
            [
                MedicineBillSummaryOut.from_bill(bill, item_count, payment_methods)
                for bill, item_count, payment_methods in data.pharmacy_bills
            ]
            if data.pharmacy_bills is not None
            else None
        ),
    )
    return success_envelope(response.model_dump(mode="json"))

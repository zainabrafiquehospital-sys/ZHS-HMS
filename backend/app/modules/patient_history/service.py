"""Patient History business logic — purely read-only aggregation across
Patient, Visit, Vitals, Consultation, Billing, Lab, and Pharmacy (the
same "reporting modules depend on everything they report on; nothing
depends back on them" shape app/modules/dashboard/service.py's own
docstring already establishes, §12). Owns no table and no write path of
its own — every method here composes an existing service's own
read/batch method, never bypasses to another module's repository
directly.

`patient_id` is resolved to its visits exactly once
(`VisitService.list_visits`, `page_size=200` — see that call's own
comment for why), and every other section is then batch-fetched off
that one `visit_ids` list (or, for LabBill, directly off `patient_id`
— see LabBillRepository.list_for_patient's own docstring for why that
one table alone needs no visit join) — a small, fixed number of
queries regardless of how many visits/bills/records the patient
actually has, never one query per visit."""

from dataclasses import dataclass
from uuid import UUID

from app.modules.billing.models import Invoice
from app.modules.billing.service import BillingService
from app.modules.consultation.models import Consultation
from app.modules.consultation.service import ConsultationService
from app.modules.lab.models import LabBill
from app.modules.lab.service import LabService
from app.modules.patients.models import Patient
from app.modules.patients.service import PatientService
from app.modules.pharmacy.models import MedicineBill
from app.modules.pharmacy.service import PharmacyService
from app.modules.visits.models import Visit
from app.modules.visits.service import VisitService
from app.modules.vitals.models import VitalsRecord
from app.modules.vitals.service import VitalsService

# A patient realistically accumulating more visits than this in one
# hospital's records is not a real case this build needs to handle
# today — same "current volume" reasoning as
# VitalsService.list_for_patient's own identical `page_size=50`, raised
# here since a *complete* history is this feature's whole purpose
# (unlike that narrower trend panel), not merely the last handful.
_MAX_VISITS = 200


@dataclass(frozen=True)
class PatientHistoryData:
    """Everything `PatientHistoryService.get_history` gathers for one
    patient, one field per response section. `None` on any field but
    `patient`/`visits` means "the caller didn't ask for this section"
    (see get_history's own `sections` parameter) — router.py is what
    actually decides which sections to ask for, based on the actor's
    other permissions; this service has no permission logic of its
    own."""

    patient: Patient
    visits: list[Visit]
    vitals: list[VitalsRecord] | None
    consultations: list[Consultation] | None
    invoices: list[Invoice] | None
    lab_bills: list[tuple[LabBill, int, list[str]]] | None
    pharmacy_bills: list[tuple[MedicineBill, int, list[str]]] | None


class PatientHistoryService:
    def __init__(
        self,
        patient_service: PatientService,
        visit_service: VisitService,
        vitals_service: VitalsService,
        consultation_service: ConsultationService,
        billing_service: BillingService,
        lab_service: LabService,
        pharmacy_service: PharmacyService,
    ) -> None:
        self._patient_service = patient_service
        self._visit_service = visit_service
        self._vitals_service = vitals_service
        self._consultation_service = consultation_service
        self._billing_service = billing_service
        self._lab_service = lab_service
        self._pharmacy_service = pharmacy_service

    async def get_history(
        self,
        *,
        patient_id: UUID,
        include_vitals: bool,
        include_consultations: bool,
        include_invoices: bool,
        include_lab_bills: bool,
        include_pharmacy_bills: bool,
    ) -> PatientHistoryData:
        """Raises PatientNotFoundError (via `PatientService.get_patient`)
        for an unknown/soft-deleted patient id before any other query
        runs — never a partially-built response for a patient that
        doesn't exist. Each `include_*` flag is the router's own
        permission decision, passed down rather than re-derived here —
        this service stays free of any RBAC/permission-checking concern
        of its own, matching every other module's own service/router
        split in this codebase."""
        patient = await self._patient_service.get_patient(patient_id)

        visits, _total = await self._visit_service.list_visits(
            patient_id=patient_id,
            doctor_user_id=None,
            unassigned_only=False,
            status=None,
            sort_by="created_at",
            sort_desc=False,
            page=1,
            page_size=_MAX_VISITS,
        )
        visit_ids = [visit.id for visit in visits]

        vitals = (
            await self._vitals_service.list_for_patient(patient_id=patient_id)
            if include_vitals
            else None
        )
        consultations = (
            await self._consultation_service.list_for_visits(visit_ids)
            if include_consultations
            else None
        )
        invoices = (
            await self._billing_service.list_invoices_for_visits(visit_ids)
            if include_invoices
            else None
        )
        lab_bills = (
            await self._lab_service.list_bills_for_patient(patient_id)
            if include_lab_bills
            else None
        )
        pharmacy_bills = (
            await self._pharmacy_service.list_bills_for_visits(visit_ids)
            if include_pharmacy_bills
            else None
        )

        return PatientHistoryData(
            patient=patient,
            visits=visits,
            vitals=vitals,
            consultations=consultations,
            invoices=invoices,
            lab_bills=lab_bills,
            pharmacy_bills=pharmacy_bills,
        )

    async def get_visit_procedure_items(self, visit_ids: list[UUID]):
        """Thin passthrough so the router can build `VisitOut` the exact
        same way `GET /visits` itself does (see app/modules/visits/
        router.py's `list_visits`) without importing VisitService's own
        internals directly."""
        return await self._visit_service.list_procedure_items_for_visits(visit_ids)

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
from datetime import date as date_type, datetime
from uuid import UUID

from app.modules.billing.models import Invoice
from app.modules.billing.service import BillingService
from app.modules.consultation.models import Consultation
from app.modules.consultation.service import ConsultationService
from app.modules.lab.models import LabBill
from app.modules.lab.service import LabService
from app.modules.patient_history.repository import PatientHistoryRepository
from app.modules.patients.models import Patient
from app.modules.patients.service import PatientService
from app.modules.pharmacy.models import MedicineBill
from app.modules.pharmacy.service import PharmacyService
from app.modules.visits.models import Visit, VisitProcedureItem
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

# The Patient History list's own name/MR/phone search (list_visits
# below) resolves matching Patient rows before filtering visits by
# them — a real "search-as-you-type" term realistically narrows to a
# small handful of people (a name, an MR number, or a phone number all
# identify a specific person or small family cluster), so this cap is
# generous headroom, not a tight budget; it exists only to bound a
# pathological single-character-style query, the same purpose
# PRINT_FETCH_CAP serves in features/admin/components/PatientDirectory.jsx.
_MAX_SEARCH_MATCHED_PATIENTS = 200


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


@dataclass(frozen=True)
class PatientHistoryRecord:
    """One row of `PatientHistoryService.list_records`'s unified feed —
    exactly one of `visit`/`medicine_bill`/`lab_bill` is populated,
    matching `record_type`. `router.py` turns this into a
    `PatientHistoryRecordOut`; kept as a plain dataclass here (not the
    Pydantic response model itself) for the same "service returns raw
    data, router builds the Out schema" split `get_history`/
    `PatientHistoryData` above already follow."""

    record_type: str
    queue_token: str | None
    created_at: datetime
    patient_id: UUID | None
    visit: Visit | None = None
    visit_procedure_items: list[VisitProcedureItem] | None = None
    medicine_bill: MedicineBill | None = None
    medicine_bill_item_count: int | None = None
    medicine_bill_payment_methods: list[str] | None = None
    lab_bill: LabBill | None = None
    lab_bill_item_count: int | None = None
    lab_bill_payment_methods: list[str] | None = None


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
        history_repository: PatientHistoryRepository,
    ) -> None:
        self._patient_service = patient_service
        self._visit_service = visit_service
        self._vitals_service = vitals_service
        self._consultation_service = consultation_service
        self._billing_service = billing_service
        self._lab_service = lab_service
        self._pharmacy_service = pharmacy_service
        self._history_repo = history_repository

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

    async def list_records(
        self,
        *,
        search: str | None,
        start_date: date_type | None,
        end_date: date_type | None,
        include_visits: bool,
        include_medicine_bills: bool,
        include_lab_bills: bool,
        page: int,
        page_size: int,
    ) -> tuple[list[PatientHistoryRecord], int]:
        """Backs `GET /patients/history/visits` — the Patient History
        page's own always-visible, hospital-wide feed across Visit/
        MedicineBill/LabBill (never empty-by-default the way the
        single-patient `get_history` above is), with real server-side
        pagination/search/date-range across all three, never a client-
        side approximation over a capped fetch (the same "current
        volume" convention this codebase already applies everywhere
        else real search/pagination exists).

        `search` serves two purposes at once, combined with `OR` at the
        query level (see `PatientHistoryRepository.search_feed`'s own
        docstring): resolved to matching Patient ids first, via
        `PatientService.list_patients` — this module's own "depends on
        everything it reports on" composition (see this module's own
        docstring) — *and* passed through unchanged as a direct
        `queue_token` substring match, so a token-shaped search (e.g.
        "802" or "Token #000802") finds the right row even though a
        `Patient` row has no token column of its own to search against.
        No `search` term means no filter at all — every record,
        hospital-wide, exactly matching "never an empty screen" — this
        is deliberately the page's own default state.

        `include_visits`/`include_medicine_bills`/`include_lab_bills`
        are the router's own per-actor permission decision (visits:read/
        pharmacy:read/lab:read respectively) — passed straight through
        to the repository, which drops any branch the actor can't see
        from the underlying `UNION ALL` entirely (see that method's own
        docstring); this service adds no permission logic of its own,
        matching `get_history` above."""
        patient_ids = None
        if search:
            matched_patients, _total = await self._patient_service.list_patients(
                search=search,
                sort_by="full_name",
                sort_desc=False,
                page=1,
                page_size=_MAX_SEARCH_MATCHED_PATIENTS,
            )
            patient_ids = [patient.id for patient in matched_patients]

        rows, total = await self._history_repo.search_feed(
            patient_ids=patient_ids,
            token_search=search,
            start_date=start_date,
            end_date=end_date,
            include_visits=include_visits,
            include_medicine_bills=include_medicine_bills,
            include_lab_bills=include_lab_bills,
            limit=page_size,
            offset=(page - 1) * page_size,
        )

        visit_ids = [row.id for row in rows if row.record_type == "visit"]
        medicine_bill_ids = [row.id for row in rows if row.record_type == "medicine_bill"]
        lab_bill_ids = [row.id for row in rows if row.record_type == "lab_bill"]

        visits_by_id = {visit.id: visit for visit in await self._visit_service.list_by_ids(visit_ids)}
        items_by_visit = await self._visit_service.list_procedure_items_for_visits(visit_ids)

        medicine_bills_by_id = {
            bill.id: (bill, item_count, methods)
            for bill, item_count, methods in await self._pharmacy_service.list_bills_by_ids(
                medicine_bill_ids
            )
        }
        lab_bills_by_id = {
            bill.id: (bill, item_count, methods)
            for bill, item_count, methods in await self._lab_service.list_bills_by_ids(
                lab_bill_ids
            )
        }

        records: list[PatientHistoryRecord] = []
        for row in rows:
            if row.record_type == "visit":
                visit = visits_by_id.get(row.id)
                if visit is None:
                    continue
                records.append(
                    PatientHistoryRecord(
                        record_type="visit",
                        queue_token=row.queue_token,
                        created_at=row.created_at,
                        patient_id=row.patient_id,
                        visit=visit,
                        visit_procedure_items=items_by_visit.get(visit.id, []),
                    )
                )
            elif row.record_type == "medicine_bill":
                entry = medicine_bills_by_id.get(row.id)
                if entry is None:
                    continue
                bill, item_count, methods = entry
                records.append(
                    PatientHistoryRecord(
                        record_type="medicine_bill",
                        queue_token=row.queue_token,
                        created_at=row.created_at,
                        patient_id=row.patient_id,
                        medicine_bill=bill,
                        medicine_bill_item_count=item_count,
                        medicine_bill_payment_methods=methods,
                    )
                )
            else:
                entry = lab_bills_by_id.get(row.id)
                if entry is None:
                    continue
                bill, item_count, methods = entry
                records.append(
                    PatientHistoryRecord(
                        record_type="lab_bill",
                        queue_token=row.queue_token,
                        created_at=row.created_at,
                        patient_id=row.patient_id,
                        lab_bill=bill,
                        lab_bill_item_count=item_count,
                        lab_bill_payment_methods=methods,
                    )
                )

        return records, total

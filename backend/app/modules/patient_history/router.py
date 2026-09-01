"""HTTP endpoints for the Patient History module — two, both gated on
`patients:history:read` (see app/modules/patients/constants.py's own
docstring) to even be reached at all, but built for genuinely different
purposes:

  - `GET /patients/history/visits` — the always-visible, hospital-wide,
    paginated *feed*, unified across Visit/MedicineBill/LabBill (see
    app/modules/patient_history/repository.py's own docstring for why
    a single query is allowed to span all three here). Never empty by
    default; a receptionist lands on it and sees every recent record,
    searchable by name/MR/phone/CNIC or by Token #.
  - `GET /{patient_id}/history` — a single, cross-module aggregated
    *timeline* for one already-identified patient (visits, vitals,
    consultations, billing, lab bills, pharmacy bills), additive
    alongside (never replacing) `GET /visits?patient_id=` and
    `GET /vitals/patients/{id}/history`, which stay exactly as they are
    for their own existing callers.

Both share the identical per-type/per-section permission re-check
beyond the gating `patients:history:read` permission — a role that
can't independently read a given type never sees it, in either
endpoint, mirroring the exact permission that type's own reader-facing
GET route already requires elsewhere in the app:
  - visits            -> `visits:read`        (GET /visits)
  - medicine bills      -> `pharmacy:read`      (GET /pharmacy/bills)
  - lab bills            -> `lab:read`            (GET /lab/bills)
  - vitals               -> `vitals:read`         (GET /vitals/visits/{id}, drill-down only)
  - consultations        -> `consultation:read`   (GET /consultations/{id}, drill-down only)
  - invoices             -> `billing:read`        (GET /visits/{id}/invoices, drill-down only)
In the feed, a type the actor can't read is dropped from the
underlying query entirely (never fetched then filtered); in the
drill-down, that same section comes back `null` rather than 403ing the
whole request — this pair's entire point is that different roles
legitimately see different slices of the same hospital-wide data (e.g.
Reception sees Lab/Pharmacy but not Vitals/Consultation; Doctor sees
Vitals/Consultation but not Billing/Lab/Pharmacy — confirmed directly
against this app's actual RBAC grants, not assumed), never a hard
failure just because one section/type isn't visible to this particular
caller."""

from datetime import date as date_type
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.modules.auth.dependencies import get_auth_service, require_permission
from app.modules.auth.models import User
from app.modules.auth.service import AuthService
from app.modules.billing.constants import PERMISSION_BILLING_READ
from app.modules.consultation.constants import PERMISSION_CONSULTATION_READ
from app.modules.consultation.schemas import ConsultationOut
from app.modules.lab.constants import PERMISSION_LAB_READ
from app.modules.lab.schemas import LabBillSummaryOut
from app.modules.patient_history.dependencies import get_patient_history_service
from app.modules.patient_history.schemas import (
    PatientHistoryInvoiceOut,
    PatientHistoryOut,
    PatientHistoryRecordOut,
)
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
from app.shared.pagination import PaginationMeta

router = APIRouter(prefix="/patients", tags=["patient-history"])


@router.get("/history/visits")
async def list_patient_history_records(
    search: str | None = Query(
        default=None,
        description="Name/MR/phone/CNIC (resolved to matching patients first) OR a "
        "Token # substring, matched directly against Visit/MedicineBill/LabBill's own "
        "queue_token — combined with OR, see PatientHistoryService.list_records's own "
        "docstring. Omitted entirely means every record, hospital-wide — the Patient "
        "History page's own always-visible default list, deliberately never empty.",
    ),
    start_date: date_type | None = Query(default=None),
    end_date: date_type | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    history_service: PatientHistoryService = Depends(get_patient_history_service),
    auth_service: AuthService = Depends(get_auth_service),
    actor: User = Depends(require_permission(PERMISSION_PATIENTS_HISTORY_READ)),
) -> dict:
    """Backs the Patient History page's always-visible, hospital-wide
    feed — a 2-segment path (`/patients/history/visits`), deliberately
    placed ahead of `/{patient_id}/history` in this router so it can
    never collide with a UUID path param (same precaution `/patients/
    lookup/by-phone` already uses elsewhere in this app).

    Unified across Visit/MedicineBill/LabBill (2026-09 redesign — see
    app/modules/patient_history/repository.py's own docstring for why
    a single query is allowed to span all three here): every real
    Token # in the hospital is drawn from one shared Postgres sequence
    across all three tables, so a list that only ever showed Visit rows
    was silently missing every medicine bill and lab bill, standalone
    or not — this endpoint's whole point is that the sequence a
    receptionist sees on screen should be exactly as continuous as the
    one already printed on every slip.

    Each record type is independently gated on the exact same
    permission its own reader-facing GET route already requires
    (visits:read / pharmacy:read / lab:read) — the identical per-
    section gating `GET /{patient_id}/history` below already
    establishes, just applied per-row instead of per-section: an actor
    who can't read a given type never sees it in the feed at all
    (dropped from the underlying query, not fetched-then-filtered),
    the same way that type's own section would come back `null` in the
    drill-down."""
    held = auth_service.effective_permission_codes(actor)
    include_visits = PERMISSION_VISITS_READ in held
    include_medicine_bills = PERMISSION_PHARMACY_READ in held
    include_lab_bills = PERMISSION_LAB_READ in held

    records, total = await history_service.list_records(
        search=search,
        start_date=start_date,
        end_date=end_date,
        include_visits=include_visits,
        include_medicine_bills=include_medicine_bills,
        include_lab_bills=include_lab_bills,
        page=page,
        page_size=page_size,
    )

    body = []
    for record in records:
        out = PatientHistoryRecordOut(
            record_type=record.record_type,
            queue_token=record.queue_token,
            created_at=record.created_at,
            patient_id=record.patient_id,
            visit=(
                VisitOut.from_visit(record.visit, record.visit_procedure_items or [])
                if record.visit is not None
                else None
            ),
            medicine_bill=(
                MedicineBillSummaryOut.from_bill(
                    record.medicine_bill,
                    record.medicine_bill_item_count or 0,
                    record.medicine_bill_payment_methods,
                )
                if record.medicine_bill is not None
                else None
            ),
            lab_bill=(
                LabBillSummaryOut.from_bill(
                    record.lab_bill,
                    record.lab_bill_item_count or 0,
                    record.lab_bill_payment_methods,
                )
                if record.lab_bill is not None
                else None
            ),
        )
        body.append(out.model_dump(mode="json"))

    meta = PaginationMeta(page=page, page_size=page_size, total=total).model_dump(mode="json")
    return success_envelope(body, meta)


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

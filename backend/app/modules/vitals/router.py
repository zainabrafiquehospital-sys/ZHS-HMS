"""HTTP endpoints for the Vitals module.

`print_daily_summary` (2026-08-28 addition, Step 5) depends on
`InventoryService`/`VisitService`/`PatientService` directly, alongside
`VitalsService` — the same "router composes independent per-module
services, none of them wired to depend on each other" pattern
app/modules/inventory/router.py's own `print_my_daily_usage_slip`
already uses for its `InventoryService` + `PatientService` pair, and
app/modules/reception/router.py uses throughout — not a new
`VitalsService` constructor dependency on `InventoryService`, which
would tie two otherwise-independent modules together for one print
endpoint's sake."""

from datetime import UTC, datetime
from datetime import date as date_type
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse

from app.core.config import Settings, get_settings
from app.modules.auth.dependencies import require_permission
from app.modules.auth.models import User
from app.modules.inventory.dependencies import get_inventory_service
from app.modules.inventory.service import InventoryService
from app.modules.patients.dependencies import get_patient_service
from app.modules.patients.service import PatientService
from app.modules.visits.dependencies import get_visit_service
from app.modules.visits.service import VisitService
from app.modules.vitals.constants import PERMISSION_VITALS_READ, PERMISSION_VITALS_RECORD
from app.modules.vitals.dependencies import get_vitals_service
from app.modules.vitals.schemas import RecordVitalsRequest, VitalsCreatorStatOut, VitalsRecordOut
from app.modules.vitals.service import VitalsService
from app.shared.envelope import success_envelope
from app.shared.pagination import PaginationMeta
from app.shared.printing.service import format_local_timestamp, render_vitals_daily_summary

router = APIRouter(prefix="/vitals", tags=["vitals"])


@router.post("", status_code=201)
async def record_vitals(
    payload: RecordVitalsRequest,
    vitals_service: VitalsService = Depends(get_vitals_service),
    actor: User = Depends(require_permission(PERMISSION_VITALS_RECORD)),
) -> dict:
    record = await vitals_service.record_vitals(
        actor=actor,
        visit_id=payload.visit_id,
        systolic_bp=payload.systolic_bp,
        diastolic_bp=payload.diastolic_bp,
        pulse_rate=payload.pulse_rate,
        temperature=payload.temperature,
        weight_kg=payload.weight_kg,
        height_cm=payload.height_cm,
        spo2_percent=payload.spo2_percent,
        notes=payload.notes,
    )
    return success_envelope(VitalsRecordOut.from_record(record).model_dump(mode="json"))


@router.get("/stats/by-creator")
async def get_vitals_stats_by_creator(
    vitals_service: VitalsService = Depends(get_vitals_service),
    _actor: User = Depends(require_permission(PERMISSION_VITALS_READ)),
) -> dict:
    """Read-only aggregate added for the Admin "Employee Accounts &
    Stats" page — one row per user who has recorded at least one Vitals
    reading, each with their all-time count. Not paginated: bounded by
    the number of distinct users who have ever recorded vitals (see
    VitalsRecordRepository.count_by_creator)."""
    counts = await vitals_service.count_by_creator()
    body = [
        VitalsCreatorStatOut(user_id=user_id, count=count).model_dump(mode="json")
        for user_id, count in counts.items()
    ]
    return success_envelope(body)


@router.get("/visits/{visit_id}")
async def list_for_visit(
    visit_id: UUID,
    vitals_service: VitalsService = Depends(get_vitals_service),
    _actor: User = Depends(require_permission(PERMISSION_VITALS_READ)),
) -> dict:
    records = await vitals_service.list_for_visit(visit_id)
    body = [VitalsRecordOut.from_record(record).model_dump(mode="json") for record in records]
    return success_envelope(body)


@router.get("/patients/{patient_id}/latest")
async def get_latest_for_patient(
    patient_id: UUID,
    exclude_visit_id: UUID = Query(
        ...,
        description="The in-progress visit to exclude — this endpoint answers "
        "'what were this patient's vitals on a previous visit', not this one.",
    ),
    vitals_service: VitalsService = Depends(get_vitals_service),
    _actor: User = Depends(require_permission(PERMISSION_VITALS_READ)),
) -> dict:
    """Backs the vitals-entry screen's previous-reading/trend panel.
    Returns `data: null` (not a 404) when the patient genuinely has no
    prior vitals — an absent record is a normal, expected outcome here,
    not an error condition."""
    record = await vitals_service.get_latest_for_patient(
        patient_id=patient_id, exclude_visit_id=exclude_visit_id
    )
    body = VitalsRecordOut.from_record(record).model_dump(mode="json") if record else None
    return success_envelope(body)


@router.get("/patients/{patient_id}/history")
async def list_for_patient(
    patient_id: UUID,
    vitals_service: VitalsService = Depends(get_vitals_service),
    _actor: User = Depends(require_permission(PERMISSION_VITALS_READ)),
) -> dict:
    """Backs the "Show Details" cross-visit vitals history view
    (2026-08-28 addition) — every vitals record recorded for this
    patient across every visit, newest first. Unlike `/latest` above,
    this returns the full list (possibly empty), not a single record or
    `null` — an empty list is this endpoint's own honest "no vitals on
    file at all" signal, same convention as `list_for_visit`."""
    records = await vitals_service.list_for_patient(patient_id=patient_id)
    body = [VitalsRecordOut.from_record(record).model_dump(mode="json") for record in records]
    return success_envelope(body)


@router.get("/records/mine")
async def list_my_records(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    vitals_service: VitalsService = Depends(get_vitals_service),
    actor: User = Depends(require_permission(PERMISSION_VITALS_RECORD)),
) -> dict:
    """The calling Vitals staff member's own "My Vitals Records" —
    every vitals record they have personally recorded, newest first,
    real server-side pagination, no date restriction (2026-08-28
    addition — the Vitals sibling of Reception's "My Registrations"
    and `GET /pharmacy/bills/mine`). Declared before nothing
    conflicting (no bare `/vitals/{id}` GET route exists in this
    router), but named the same "mine" convention those endpoints
    established.

    Always `actor.id`, never a request-suppliable user id — the same
    hard server-side scoping `print_daily_summary` above and every
    other "mine" endpoint in this app already establishes; there is
    structurally no way to ask for someone else's records through
    this endpoint. Gated on `vitals:record` (matching this module's
    own `print_daily_summary` precedent for an actor-scoped "my own
    work" endpoint) rather than `vitals:read` — in practice every
    Vitals staff member holds both."""
    records, total = await vitals_service.list_for_creator(
        actor.id, page=page, page_size=page_size
    )
    body = [VitalsRecordOut.from_record(record).model_dump(mode="json") for record in records]
    meta = PaginationMeta(page=page, page_size=page_size, total=total).model_dump(mode="json")
    return success_envelope(body, meta)


@router.get("/daily-summary/print", response_class=HTMLResponse)
async def print_daily_summary(
    date: date_type = Query(
        description="Calendar day (UTC) to print this user's combined daily summary for."
    ),
    vitals_service: VitalsService = Depends(get_vitals_service),
    inventory_service: InventoryService = Depends(get_inventory_service),
    visit_service: VisitService = Depends(get_visit_service),
    patient_service: PatientService = Depends(get_patient_service),
    settings: Settings = Depends(get_settings),
    actor: User = Depends(require_permission(PERMISSION_VITALS_RECORD)),
) -> HTMLResponse:
    """Step 5's combined daily PDF — Inventory items used AND Vitals
    recorded, by this actor, on one day, in one document (distinct from
    Inventory's own standalone `GET /inventory/usage/mine/print`, which
    still exists unchanged and covers only the Inventory half). Always
    `actor.id`, never a request-suppliable user id — the identical hard
    server-side "your own day only" scoping every other daily-summary
    print endpoint in this app already uses (see
    app/modules/inventory/router.py's `print_my_daily_usage_slip`)."""
    day_start = datetime(date.year, date.month, date.day)
    inventory_entries = await inventory_service.list_usage_for_creator_and_day(
        created_by=actor.id, day=day_start
    )
    vitals_records = await vitals_service.list_for_creator_and_day(
        created_by=actor.id, day=day_start
    )

    # ---- Inventory Items Used section ----
    items, _total = await inventory_service.list_items(
        search=None,
        category=None,
        low_stock_only=False,
        sort_by="name",
        sort_desc=False,
        page=1,
        page_size=1000,
    )
    items_by_id = {item.id: item for item in items}
    inventory_patient_ids = list(
        {entry.patient_id for entry in inventory_entries if entry.patient_id is not None}
    )
    inventory_patients_by_id = {
        patient.id: patient for patient in await patient_service.list_by_ids(inventory_patient_ids)
    }

    def inventory_patient_display(entry) -> str:
        if entry.manual_patient_name:
            return entry.manual_patient_name
        patient = inventory_patients_by_id.get(entry.patient_id) if entry.patient_id else None
        return f"{patient.full_name} (MR: {patient.mr_number})" if patient else "—"

    inventory_column_headers = ["Item", "Quantity", "Patient", "Reason", "Time"]
    inventory_rows = [
        [
            items_by_id[entry.item_id].name if entry.item_id in items_by_id else "Unknown item",
            str(entry.quantity),
            inventory_patient_display(entry),
            entry.reason_note or "—",
            format_local_timestamp(entry.created_at, settings.display_timezone),
        ]
        for entry in inventory_entries
    ]
    inventory_total_quantity = (
        sum((entry.quantity for entry in inventory_entries), Decimal("0"))
        if inventory_entries
        else None
    )

    # ---- Vitals Recorded section ----
    # Bounded N+1 (one staff member's one day of recordings — a
    # handful to a few dozen rows in practice, never the paginated/
    # unbounded scope other list endpoints guard against): each record
    # only carries visit_id, so its Visit (for the queue token) and
    # Patient (for name/MR) are resolved per row, the same "print is not
    # a hot path" reasoning `_load_items_by_id`'s own docstring gives.
    visits_by_id = {}
    for record in vitals_records:
        if record.visit_id not in visits_by_id:
            visits_by_id[record.visit_id] = await visit_service.get_visit(record.visit_id)
    vitals_patient_ids = list({visit.patient_id for visit in visits_by_id.values()})
    vitals_patients_by_id = {
        patient.id: patient for patient in await patient_service.list_by_ids(vitals_patient_ids)
    }

    def vitals_patient_display(visit) -> str:
        patient = vitals_patients_by_id.get(visit.patient_id)
        return f"{patient.full_name} (MR: {patient.mr_number})" if patient else "—"

    def temperature_display(record) -> str:
        if record.temperature is None or record.temperature_unit is None:
            return "—"
        unit_letter = "F" if record.temperature_unit.value == "fahrenheit" else "C"
        return f"{record.temperature} °{unit_letter}"

    vitals_column_headers = ["Patient", "Queue Token", "BP", "Pulse", "Temp", "SpO2", "Time"]
    vitals_rows = [
        [
            vitals_patient_display(visits_by_id[record.visit_id]),
            visits_by_id[record.visit_id].queue_token,
            f"{record.systolic_bp}/{record.diastolic_bp}"
            if record.systolic_bp is not None and record.diastolic_bp is not None
            else "—",
            str(record.pulse_rate) if record.pulse_rate is not None else "—",
            temperature_display(record),
            f"{record.spo2_percent}%" if record.spo2_percent is not None else "—",
            format_local_timestamp(record.created_at, settings.display_timezone),
        ]
        for record in vitals_records
    ]

    html_document = render_vitals_daily_summary(
        hospital_name=settings.app_name,
        display_timezone=settings.display_timezone,
        vitals_staff_name=actor.full_name,
        day=date,
        generated_at=datetime.now(UTC),
        inventory_column_headers=inventory_column_headers,
        inventory_numeric_columns={1},
        inventory_rows=inventory_rows,
        inventory_total_quantity=inventory_total_quantity,
        vitals_column_headers=vitals_column_headers,
        vitals_rows=vitals_rows,
    )
    return HTMLResponse(content=html_document)

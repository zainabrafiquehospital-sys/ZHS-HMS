"""HTTP endpoints for the Visit module. Visit creation and status
transitions are exposed as VisitService methods other modules' routers
call into (Reception creates; Vitals/Consultation/Billing transition) —
see schemas.py's module docstring for why there is no public visit
create/update endpoint here.

`/procedures/*` (2026-08-21 addition) is the one exception — the
admin-managed procedure catalog's own CRUD, gated on `procedures:manage`
(search on `procedures:read`, also granted to Receptionist), mirroring
app/modules/pharmacy/router.py's `/medicines/*` endpoints almost
exactly. Declared before `/{visit_id}` below — same routing-order
precaution that module's own `/bills/mine`/`/bills/stats/by-creator`
need against `/bills/{bill_id}`, otherwise FastAPI would try to parse
the literal path segment `procedures` as a `visit_id` UUID and 422."""

from datetime import date as date_type
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.modules.auth.dependencies import require_permission
from app.modules.auth.models import User
from app.modules.visits.constants import (
    PERMISSION_PROCEDURES_MANAGE,
    PERMISSION_PROCEDURES_READ,
    PERMISSION_VISITS_READ,
)
from app.modules.visits.dependencies import get_visit_service
from app.modules.visits.models import VisitStatus
from app.modules.visits.schemas import (
    CreateProcedureRequest,
    ProcedureOut,
    ProcedureSortField,
    UpdateProcedureRequest,
    VisitCreatorStatOut,
    VisitOut,
    VisitSortField,
)
from app.modules.visits.service import VisitService
from app.shared.envelope import success_envelope
from app.shared.pagination import PaginationMeta, SortOrder

router = APIRouter(prefix="/visits", tags=["visits"])


# ----------------------------------------------------------------------
# Procedure catalog — Admin-only management (2026-08-21 addition)
# ----------------------------------------------------------------------


@router.post("/procedures", status_code=201)
async def create_procedure(
    payload: CreateProcedureRequest,
    visit_service: VisitService = Depends(get_visit_service),
    actor: User = Depends(require_permission(PERMISSION_PROCEDURES_MANAGE)),
) -> dict:
    procedure = await visit_service.create_procedure(
        actor=actor, name=payload.name, price=payload.price
    )
    return success_envelope(ProcedureOut.from_procedure(procedure).model_dump(mode="json"))


@router.get("/procedures")
async def list_procedures(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    search: str | None = Query(default=None, max_length=200),
    sort_by: ProcedureSortField = Query(default=ProcedureSortField.NAME),
    sort_order: SortOrder = Query(default=SortOrder.ASC),
    visit_service: VisitService = Depends(get_visit_service),
    _actor: User = Depends(require_permission(PERMISSION_PROCEDURES_MANAGE)),
) -> dict:
    """Admin management listing — every procedure, active and inactive
    alike (see repository.py's `ProcedureRepository.list_all` docstring)."""
    procedures, total = await visit_service.list_procedures(
        search=search,
        sort_by=sort_by.value,
        sort_desc=sort_order == SortOrder.DESC,
        page=page,
        page_size=page_size,
    )
    body = [
        ProcedureOut.from_procedure(procedure).model_dump(mode="json") for procedure in procedures
    ]
    meta = PaginationMeta(page=page, page_size=page_size, total=total).model_dump(mode="json")
    return success_envelope(body, meta)


@router.get("/procedures/search")
async def search_procedures(
    search: str = Query(min_length=1, max_length=200),
    visit_service: VisitService = Depends(get_visit_service),
    _actor: User = Depends(require_permission(PERMISSION_PROCEDURES_READ)),
) -> dict:
    """Active-only, case-insensitive partial name match — backs the
    receptionist's procedure autocomplete at registration time.
    Unpaginated by design, same rationale as
    `pharmacy/router.py`'s `search_medicines`."""
    procedures = await visit_service.search_procedures(search=search)
    body = [
        ProcedureOut.from_procedure(procedure).model_dump(mode="json") for procedure in procedures
    ]
    return success_envelope(body)


@router.patch("/procedures/{procedure_id}")
async def update_procedure(
    procedure_id: UUID,
    payload: UpdateProcedureRequest,
    visit_service: VisitService = Depends(get_visit_service),
    actor: User = Depends(require_permission(PERMISSION_PROCEDURES_MANAGE)),
) -> dict:
    procedure = await visit_service.update_procedure(
        actor=actor, procedure_id=procedure_id, updates=payload.model_dump(exclude_unset=True)
    )
    return success_envelope(ProcedureOut.from_procedure(procedure).model_dump(mode="json"))


@router.delete("/procedures/{procedure_id}")
async def delete_procedure(
    procedure_id: UUID,
    visit_service: VisitService = Depends(get_visit_service),
    actor: User = Depends(require_permission(PERMISSION_PROCEDURES_MANAGE)),
) -> dict:
    """Soft-deletes a procedure catalog entry — safe regardless of
    whether it has ever been selected for a visit (see
    VisitService.delete_procedure's own docstring)."""
    await visit_service.delete_procedure(actor=actor, procedure_id=procedure_id)
    return success_envelope(None)


# ----------------------------------------------------------------------
# Visits — read-only
# ----------------------------------------------------------------------


@router.get("")
async def list_visits(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    patient_id: UUID | None = Query(default=None),
    doctor_user_id: UUID | None = Query(default=None),
    created_by: UUID | None = Query(
        default=None,
        description="Only Visits registered by this user — a real server-side filter, "
        "e.g. Reception's own \"My Registrations\" (every visit they've ever created, no "
        "date restriction) rather than a client-side approximation over a capped fetch.",
    ),
    date: date_type | None = Query(
        default=None,
        description="Only Visits created on this UTC calendar day — same interpretation "
        "as GET /pharmacy/bills's own `date` filter. Powers the Admin Overview day-view "
        "as a real server-side query instead of a client-filtered recent-visits fetch.",
    ),
    unassigned_only: bool = Query(
        default=False,
        description="If true, list only Visits with no doctor assigned yet — the Doctor "
        "Queue's unclaimed pool for fast-registration Visits Reception couldn't auto-assign.",
    ),
    status: VisitStatus | None = Query(default=None),
    sort_by: VisitSortField = Query(default=VisitSortField.CREATED_AT),
    sort_order: SortOrder = Query(default=SortOrder.DESC),
    visit_service: VisitService = Depends(get_visit_service),
    _actor: User = Depends(require_permission(PERMISSION_VISITS_READ)),
) -> dict:
    visits, total = await visit_service.list_visits(
        patient_id=patient_id,
        doctor_user_id=doctor_user_id,
        created_by=created_by,
        date=date,
        unassigned_only=unassigned_only,
        status=status,
        sort_by=sort_by.value,
        sort_desc=sort_order == SortOrder.DESC,
        page=page,
        page_size=page_size,
    )
    # Batched — one extra query for every visit on this page, not one
    # query per visit (see VisitProcedureItemRepository.list_for_visits's
    # own N+1-avoidance docstring). Empty for every pre-2026-08-21 visit,
    # by design.
    items_by_visit = await visit_service.list_procedure_items_for_visits(
        [visit.id for visit in visits]
    )
    body = [
        VisitOut.from_visit(visit, items_by_visit.get(visit.id, [])).model_dump(mode="json")
        for visit in visits
    ]
    meta = PaginationMeta(page=page, page_size=page_size, total=total).model_dump(mode="json")
    return success_envelope(body, meta)


@router.get("/stats/by-creator")
async def get_visit_stats_by_creator(
    visit_service: VisitService = Depends(get_visit_service),
    _actor: User = Depends(require_permission(PERMISSION_VISITS_READ)),
) -> dict:
    """Read-only aggregate — one row per user who has registered at
    least one Visit, each with their all-time count and total revenue.
    Not paginated: bounded by the number of distinct users who have ever
    registered a Visit, not by Visit volume itself (see
    VisitRepository.count_and_revenue_by_creator). Powers the Admin
    "Employee Accounts & Stats" page's per-receptionist "visits
    registered" column AND Reception's own "My Revenue"/"My Slips"
    tiles — a receptionist calling this (gated on the same
    `visits:read` they already hold) simply looks up their own row by
    their own user id out of this same all-users result."""
    stats = await visit_service.count_and_revenue_by_creator()
    body = [
        VisitCreatorStatOut(user_id=user_id, count=count, revenue=revenue).model_dump(mode="json")
        for user_id, (count, revenue) in stats.items()
    ]
    return success_envelope(body)


@router.get("/{visit_id}")
async def get_visit(
    visit_id: UUID,
    visit_service: VisitService = Depends(get_visit_service),
    _actor: User = Depends(require_permission(PERMISSION_VISITS_READ)),
) -> dict:
    visit = await visit_service.get_visit(visit_id)
    procedure_items = await visit_service.list_procedure_items(visit.id)
    return success_envelope(VisitOut.from_visit(visit, procedure_items).model_dump(mode="json"))

"""HTTP endpoints for the Visit module — read-only. Visit creation and
status transitions are exposed as VisitService methods other modules'
routers call into (Reception creates; Vitals/Consultation/Billing
transition) — see schemas.py's module docstring for why there is no
public create/update endpoint here."""

from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.modules.auth.dependencies import require_permission
from app.modules.auth.models import User
from app.modules.visits.constants import PERMISSION_VISITS_READ
from app.modules.visits.dependencies import get_visit_service
from app.modules.visits.models import VisitStatus
from app.modules.visits.schemas import VisitOut, VisitSortField
from app.modules.visits.service import VisitService
from app.shared.envelope import success_envelope
from app.shared.pagination import PaginationMeta, SortOrder

router = APIRouter(prefix="/visits", tags=["visits"])


@router.get("")
async def list_visits(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    patient_id: UUID | None = Query(default=None),
    doctor_user_id: UUID | None = Query(default=None),
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
        unassigned_only=unassigned_only,
        status=status,
        sort_by=sort_by.value,
        sort_desc=sort_order == SortOrder.DESC,
        page=page,
        page_size=page_size,
    )
    body = [VisitOut.from_visit(visit).model_dump(mode="json") for visit in visits]
    meta = PaginationMeta(page=page, page_size=page_size, total=total).model_dump(mode="json")
    return success_envelope(body, meta)


@router.get("/{visit_id}")
async def get_visit(
    visit_id: UUID,
    visit_service: VisitService = Depends(get_visit_service),
    _actor: User = Depends(require_permission(PERMISSION_VISITS_READ)),
) -> dict:
    visit = await visit_service.get_visit(visit_id)
    return success_envelope(VisitOut.from_visit(visit).model_dump(mode="json"))

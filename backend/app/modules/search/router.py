"""HTTP endpoint for the Search module.

Scope note (deliberate, not an oversight): this search only ever reads
Patient and Visit data — it never reaches into Billing or Attendance.
A prior architecture review flagged that a cross-cutting search
spanning RBAC-protected modules (e.g. Attendance, which is Admin/HR-only
per §8.5) would need its own per-result permission filtering to avoid
leaking data a caller's `search:read` grant alone doesn't justify. This
implementation sidesteps that risk entirely by not touching those
modules — Patient/Visit identity data is what Reception, Vitals, and
Doctor-facing search actually needs, and extending Search to more
sensitive modules later would need that per-result filtering design
addressed explicitly, not assumed away."""

from fastapi import APIRouter, Depends, Query

from app.modules.auth.dependencies import require_permission
from app.modules.auth.models import User
from app.modules.search.constants import PERMISSION_SEARCH_READ
from app.modules.search.dependencies import get_search_service
from app.modules.search.schemas import SearchResultOut
from app.modules.search.service import SearchService
from app.shared.envelope import success_envelope

router = APIRouter(prefix="/search", tags=["search"])


@router.get("")
async def search(
    query: str = Query(min_length=1, max_length=150),
    search_service: SearchService = Depends(get_search_service),
    _actor: User = Depends(require_permission(PERMISSION_SEARCH_READ)),
) -> dict:
    patients, visit = await search_service.search(query)
    return success_envelope(SearchResultOut.from_results(patients, visit).model_dump(mode="json"))

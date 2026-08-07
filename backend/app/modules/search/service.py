"""Global Search business logic (Phase 6 architecture §21): "a
centralized search service, reusable by every module... supports lookup
by MR Number, Visit ID, Queue Token, Patient Name, CNIC, Phone Number."

Deliberately thin — it owns no table and no query logic of its own; it
only composes PatientService's existing text search (already covers MR
Number/Name/CNIC/Phone Number — see app/modules/patients/repository.py)
with VisitService's Visit-ID and Queue-Token lookups. This is
intentional reuse, not new business logic (rule: no duplicate business
logic) — Search is read-only and depends on Patients/Visits one-
directionally (§12.1); nothing depends back on it."""

from uuid import UUID

from app.modules.patients.models import Patient
from app.modules.patients.service import PatientService
from app.modules.visits.exceptions import VisitNotFoundError
from app.modules.visits.models import Visit
from app.modules.visits.service import VisitService

_PATIENT_RESULT_LIMIT = 10


class SearchService:
    def __init__(self, patient_service: PatientService, visit_service: VisitService) -> None:
        self._patient_service = patient_service
        self._visit_service = visit_service

    async def search(self, query: str) -> tuple[list[Patient], Visit | None]:
        patients, _total = await self._patient_service.list_patients(
            search=query,
            sort_by="created_at",
            sort_desc=True,
            page=1,
            page_size=_PATIENT_RESULT_LIMIT,
        )

        visit = await self._visit_service.get_by_queue_token(query)
        if visit is None:
            visit = await self._try_get_visit_by_id(query)
        return patients, visit

    async def _try_get_visit_by_id(self, query: str) -> Visit | None:
        try:
            visit_id = UUID(query)
        except ValueError:
            return None
        try:
            return await self._visit_service.get_visit(visit_id)
        except VisitNotFoundError:
            return None

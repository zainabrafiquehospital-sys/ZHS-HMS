"""Dashboard business logic (Phase 6 architecture §22) — purely
read-only aggregation across Visit, Queue, and Billing (§12: "reporting
modules depend on everything they report on; nothing depends back on
them"). Owns no table, no repository, no write path of its own —
every method here composes an existing service's own read/aggregate
method, never bypasses to another module's repository directly."""

from decimal import Decimal
from uuid import UUID

from app.modules.billing.service import BillingService
from app.modules.queue.models import QueueDestination
from app.modules.queue.service import QueueService
from app.modules.visits.models import VisitStatus
from app.modules.visits.service import VisitService


class DashboardService:
    def __init__(
        self,
        visit_service: VisitService,
        queue_service: QueueService,
        billing_service: BillingService,
    ) -> None:
        self._visit_service = visit_service
        self._queue_service = queue_service
        self._billing_service = billing_service

    async def get_reception_summary(
        self,
    ) -> tuple[dict[VisitStatus, int], dict[QueueDestination, int], Decimal, int, int]:
        visit_status_counts = await self._visit_service.count_by_status()
        queue_destination_counts = await self._queue_service.count_waiting_by_destination()
        revenue_today, invoices_paid_today, open_invoices = (
            await self._billing_service.get_today_summary()
        )
        return (
            visit_status_counts,
            queue_destination_counts,
            revenue_today,
            invoices_paid_today,
            open_invoices,
        )

    async def get_doctor_summary(self, doctor_user_id: UUID) -> tuple[int, int]:
        """(waiting count, in-consultation count) for one doctor —
        scoped to `doctor_user_id` so a doctor's dashboard only ever
        reflects their own worklist, never a colleague's."""
        _waiting_visits, waiting_total = await self._visit_service.list_visits(
            patient_id=None,
            doctor_user_id=doctor_user_id,
            status=VisitStatus.WAITING_DOCTOR,
            sort_by="created_at",
            sort_desc=False,
            page=1,
            page_size=1,
        )
        _in_consultation_visits, in_consultation_total = await self._visit_service.list_visits(
            patient_id=None,
            doctor_user_id=doctor_user_id,
            status=VisitStatus.IN_CONSULTATION,
            sort_by="created_at",
            sort_desc=False,
            page=1,
            page_size=1,
        )
        return waiting_total, in_consultation_total

    async def get_vitals_summary(self) -> int:
        """Count of Visits currently waiting at the Vitals destination."""
        queue_destination_counts = await self._queue_service.count_waiting_by_destination()
        return queue_destination_counts.get(QueueDestination.VITALS, 0)

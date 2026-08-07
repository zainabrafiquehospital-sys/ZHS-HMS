"""FastAPI dependency-injection provider for the Dashboard module — see
app/modules/reception/dependencies.py's identical composition pattern."""

from fastapi import Depends

from app.modules.billing.dependencies import get_billing_service
from app.modules.billing.service import BillingService
from app.modules.dashboard.service import DashboardService
from app.modules.queue.dependencies import get_queue_service
from app.modules.queue.service import QueueService
from app.modules.visits.dependencies import get_visit_service
from app.modules.visits.service import VisitService


def get_dashboard_service(
    visit_service: VisitService = Depends(get_visit_service),
    queue_service: QueueService = Depends(get_queue_service),
    billing_service: BillingService = Depends(get_billing_service),
) -> DashboardService:
    return DashboardService(
        visit_service=visit_service, queue_service=queue_service, billing_service=billing_service
    )

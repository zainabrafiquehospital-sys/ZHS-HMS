"""Pydantic response schemas for the Dashboard module."""

from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from app.modules.queue.models import QueueDestination
from app.modules.visits.models import VisitStatus


class ReceptionDashboardOut(BaseModel):
    model_config = ConfigDict(strict=True)

    visits_by_status: dict[str, int]
    queue_waiting_by_destination: dict[str, int]
    revenue_collected_today: Decimal
    invoices_paid_today: int
    open_invoices: int

    @classmethod
    def from_summary(
        cls,
        visit_status_counts: dict[VisitStatus, int],
        queue_destination_counts: dict[QueueDestination, int],
        revenue_today: Decimal,
        invoices_paid_today: int,
        open_invoices: int,
    ) -> "ReceptionDashboardOut":
        return cls(
            visits_by_status={status.value: count for status, count in visit_status_counts.items()},
            queue_waiting_by_destination={
                dest.value: count for dest, count in queue_destination_counts.items()
            },
            revenue_collected_today=revenue_today,
            invoices_paid_today=invoices_paid_today,
            open_invoices=open_invoices,
        )


class DoctorDashboardOut(BaseModel):
    model_config = ConfigDict(strict=True)

    waiting_count: int
    in_consultation_count: int


class VitalsDashboardOut(BaseModel):
    model_config = ConfigDict(strict=True)

    waiting_count: int

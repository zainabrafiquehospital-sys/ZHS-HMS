"""HTTP endpoints for the Dashboard module — one per role-facing view,
each behind its own permission (see constants.py's module docstring)."""

from fastapi import APIRouter, Depends

from app.modules.auth.dependencies import require_permission
from app.modules.auth.models import User
from app.modules.dashboard.constants import (
    PERMISSION_DASHBOARD_DOCTOR_READ,
    PERMISSION_DASHBOARD_RECEPTION_READ,
    PERMISSION_DASHBOARD_VITALS_READ,
)
from app.modules.dashboard.dependencies import get_dashboard_service
from app.modules.dashboard.schemas import (
    DoctorDashboardOut,
    ReceptionDashboardOut,
    VitalsDashboardOut,
)
from app.modules.dashboard.service import DashboardService
from app.shared.envelope import success_envelope

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/reception")
async def get_reception_dashboard(
    dashboard_service: DashboardService = Depends(get_dashboard_service),
    _actor: User = Depends(require_permission(PERMISSION_DASHBOARD_RECEPTION_READ)),
) -> dict:
    summary = await dashboard_service.get_reception_summary()
    return success_envelope(ReceptionDashboardOut.from_summary(*summary).model_dump(mode="json"))


@router.get("/doctor")
async def get_doctor_dashboard(
    dashboard_service: DashboardService = Depends(get_dashboard_service),
    actor: User = Depends(require_permission(PERMISSION_DASHBOARD_DOCTOR_READ)),
) -> dict:
    """Always scoped to the acting doctor — never client-supplied (same
    ownership discipline as app/modules/consultation/service.py's
    doctor-identity checks)."""
    waiting_count, in_consultation_count = await dashboard_service.get_doctor_summary(actor.id)
    body = DoctorDashboardOut(
        waiting_count=waiting_count, in_consultation_count=in_consultation_count
    )
    return success_envelope(body.model_dump(mode="json"))


@router.get("/vitals")
async def get_vitals_dashboard(
    dashboard_service: DashboardService = Depends(get_dashboard_service),
    _actor: User = Depends(require_permission(PERMISSION_DASHBOARD_VITALS_READ)),
) -> dict:
    waiting_count = await dashboard_service.get_vitals_summary()
    return success_envelope(VitalsDashboardOut(waiting_count=waiting_count).model_dump(mode="json"))

from fastapi import APIRouter

from app.api.v1.health import router as health_router
from app.modules.auth.permission_router import router as permission_router
from app.modules.auth.role_router import router as role_router
from app.modules.auth.router import router as auth_router
from app.modules.auth.user_router import router as user_router
from app.modules.billing.router import router as billing_router
from app.modules.consultation.router import router as consultation_router
from app.modules.dashboard.router import router as dashboard_router
from app.modules.inventory.router import router as inventory_router
from app.modules.lab.router import router as lab_router
from app.modules.patients.router import router as patients_router
from app.modules.pharmacy.router import router as pharmacy_router
from app.modules.queue.router import router as queue_router
from app.modules.reception.router import router as reception_router
from app.modules.search.router import router as search_router
from app.modules.visits.router import router as visits_router
from app.modules.vitals.router import router as vitals_router

api_v1_router = APIRouter()
api_v1_router.include_router(health_router)
api_v1_router.include_router(auth_router)
api_v1_router.include_router(user_router)
api_v1_router.include_router(role_router)
api_v1_router.include_router(permission_router)
api_v1_router.include_router(patients_router)
api_v1_router.include_router(visits_router)
api_v1_router.include_router(queue_router)
api_v1_router.include_router(reception_router)
api_v1_router.include_router(consultation_router)
api_v1_router.include_router(vitals_router)
api_v1_router.include_router(billing_router)
api_v1_router.include_router(pharmacy_router)
api_v1_router.include_router(search_router)
api_v1_router.include_router(dashboard_router)
api_v1_router.include_router(inventory_router)
api_v1_router.include_router(lab_router)

# This completes the core OPD workflow's backend module set.

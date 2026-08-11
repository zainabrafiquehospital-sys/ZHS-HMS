"""FastAPI dependency-injection providers for the Pharmacy module — see
app/modules/billing/dependencies.py's identical composition pattern."""

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.modules.pharmacy.repository import (
    MedicineBillItemRepository,
    MedicineBillRepository,
    MedicineRepository,
)
from app.modules.pharmacy.service import PharmacyService
from app.modules.visits.dependencies import get_visit_service
from app.modules.visits.service import VisitService
from app.shared.audit.dependencies import get_audit_log_repository
from app.shared.audit.repository import AuditLogRepository


def get_medicine_repository(db: AsyncSession = Depends(get_db)) -> MedicineRepository:
    return MedicineRepository(db)


def get_medicine_bill_repository(db: AsyncSession = Depends(get_db)) -> MedicineBillRepository:
    return MedicineBillRepository(db)


def get_medicine_bill_item_repository(
    db: AsyncSession = Depends(get_db),
) -> MedicineBillItemRepository:
    return MedicineBillItemRepository(db)


def get_pharmacy_service(
    db: AsyncSession = Depends(get_db),
    medicine_repository: MedicineRepository = Depends(get_medicine_repository),
    medicine_bill_repository: MedicineBillRepository = Depends(get_medicine_bill_repository),
    medicine_bill_item_repository: MedicineBillItemRepository = Depends(
        get_medicine_bill_item_repository
    ),
    visit_service: VisitService = Depends(get_visit_service),
    audit_repository: AuditLogRepository = Depends(get_audit_log_repository),
) -> PharmacyService:
    return PharmacyService(
        session=db,
        medicine_repository=medicine_repository,
        medicine_bill_repository=medicine_bill_repository,
        medicine_bill_item_repository=medicine_bill_item_repository,
        visit_service=visit_service,
        audit_repository=audit_repository,
    )

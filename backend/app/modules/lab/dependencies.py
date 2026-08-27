"""FastAPI dependency-injection providers for the Lab module — see
app/modules/pharmacy/dependencies.py's identical composition pattern.
Depends on `PatientService`, never `VisitService` (confirmed design —
this module has no dependency on the Visit system at all)."""

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.modules.lab.repository import (
    LabBillItemRepository,
    LabBillPaymentRepository,
    LabBillRepository,
    LabTestRepository,
)
from app.modules.lab.service import LabService
from app.modules.patients.dependencies import get_patient_service
from app.modules.patients.service import PatientService
from app.shared.audit.dependencies import get_audit_log_repository
from app.shared.audit.repository import AuditLogRepository


def get_lab_test_repository(db: AsyncSession = Depends(get_db)) -> LabTestRepository:
    return LabTestRepository(db)


def get_lab_bill_repository(db: AsyncSession = Depends(get_db)) -> LabBillRepository:
    return LabBillRepository(db)


def get_lab_bill_item_repository(db: AsyncSession = Depends(get_db)) -> LabBillItemRepository:
    return LabBillItemRepository(db)


def get_lab_bill_payment_repository(
    db: AsyncSession = Depends(get_db),
) -> LabBillPaymentRepository:
    return LabBillPaymentRepository(db)


def get_lab_service(
    db: AsyncSession = Depends(get_db),
    lab_test_repository: LabTestRepository = Depends(get_lab_test_repository),
    lab_bill_repository: LabBillRepository = Depends(get_lab_bill_repository),
    lab_bill_item_repository: LabBillItemRepository = Depends(get_lab_bill_item_repository),
    lab_bill_payment_repository: LabBillPaymentRepository = Depends(
        get_lab_bill_payment_repository
    ),
    patient_service: PatientService = Depends(get_patient_service),
    audit_repository: AuditLogRepository = Depends(get_audit_log_repository),
) -> LabService:
    return LabService(
        session=db,
        lab_test_repository=lab_test_repository,
        lab_bill_repository=lab_bill_repository,
        lab_bill_item_repository=lab_bill_item_repository,
        lab_bill_payment_repository=lab_bill_payment_repository,
        patient_service=patient_service,
        audit_repository=audit_repository,
    )

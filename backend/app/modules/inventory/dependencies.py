"""FastAPI dependency-injection providers for the Inventory module — see
app/modules/billing/dependencies.py's identical composition pattern."""

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.modules.inventory.repository import (
    InventoryItemRepository,
    InventoryMainStockReceiptRepository,
    InventoryRestockRequestRepository,
    InventoryTransferRepository,
    InventoryUsageEntryRepository,
)
from app.modules.inventory.service import InventoryService
from app.modules.patients.dependencies import get_patient_service
from app.modules.patients.service import PatientService
from app.modules.visits.dependencies import get_visit_service
from app.modules.visits.service import VisitService
from app.shared.audit.dependencies import get_audit_log_repository
from app.shared.audit.repository import AuditLogRepository


def get_inventory_item_repository(db: AsyncSession = Depends(get_db)) -> InventoryItemRepository:
    return InventoryItemRepository(db)


def get_inventory_main_stock_receipt_repository(
    db: AsyncSession = Depends(get_db),
) -> InventoryMainStockReceiptRepository:
    return InventoryMainStockReceiptRepository(db)


def get_inventory_transfer_repository(
    db: AsyncSession = Depends(get_db),
) -> InventoryTransferRepository:
    return InventoryTransferRepository(db)


def get_inventory_usage_entry_repository(
    db: AsyncSession = Depends(get_db),
) -> InventoryUsageEntryRepository:
    return InventoryUsageEntryRepository(db)


def get_inventory_restock_request_repository(
    db: AsyncSession = Depends(get_db),
) -> InventoryRestockRequestRepository:
    return InventoryRestockRequestRepository(db)


def get_inventory_service(
    db: AsyncSession = Depends(get_db),
    item_repository: InventoryItemRepository = Depends(get_inventory_item_repository),
    receipt_repository: InventoryMainStockReceiptRepository = Depends(
        get_inventory_main_stock_receipt_repository
    ),
    transfer_repository: InventoryTransferRepository = Depends(get_inventory_transfer_repository),
    usage_repository: InventoryUsageEntryRepository = Depends(get_inventory_usage_entry_repository),
    request_repository: InventoryRestockRequestRepository = Depends(
        get_inventory_restock_request_repository
    ),
    patient_service: PatientService = Depends(get_patient_service),
    visit_service: VisitService = Depends(get_visit_service),
    audit_repository: AuditLogRepository = Depends(get_audit_log_repository),
) -> InventoryService:
    return InventoryService(
        session=db,
        item_repository=item_repository,
        receipt_repository=receipt_repository,
        transfer_repository=transfer_repository,
        usage_repository=usage_repository,
        request_repository=request_repository,
        patient_service=patient_service,
        visit_service=visit_service,
        audit_repository=audit_repository,
    )

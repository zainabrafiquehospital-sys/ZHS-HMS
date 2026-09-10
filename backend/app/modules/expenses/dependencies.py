"""FastAPI dependency-injection providers for the Expense module — same
compose-existing-providers pattern as app/modules/lab/dependencies.py.
`ExpenseService` needs the configured display timezone (Asia/Karachi by
default) to resolve 'today' for the same-day-only rules, so `Settings`
is injected here and only its `display_timezone` string handed down."""

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.dependencies import get_db
from app.modules.expenses.repository import ExpenseRepository
from app.modules.expenses.service import ExpenseService
from app.shared.audit.dependencies import get_audit_log_repository
from app.shared.audit.repository import AuditLogRepository


def get_expense_repository(db: AsyncSession = Depends(get_db)) -> ExpenseRepository:
    return ExpenseRepository(db)


def get_expense_service(
    db: AsyncSession = Depends(get_db),
    expense_repository: ExpenseRepository = Depends(get_expense_repository),
    audit_repository: AuditLogRepository = Depends(get_audit_log_repository),
    settings: Settings = Depends(get_settings),
) -> ExpenseService:
    return ExpenseService(
        session=db,
        expense_repository=expense_repository,
        audit_repository=audit_repository,
        display_timezone=settings.display_timezone,
    )

"""FastAPI dependency-injection provider for the shared, module-agnostic
audit log (app/shared/audit/repository.py) — every feature module's own
dependencies.py depends on this, mirroring how every module already
depends on app/core/dependencies.py's `get_db`. Deliberately lives here,
not inside any one feature module's dependencies.py: `AuditLogRepository`
is infrastructure every module uses as a peer, not something one feature
module (e.g. patients) should "own" on behalf of the others — that would
create an inappropriate module-to-module dependency the one-directional
architecture (Phase 6 §12) doesn't call for."""

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.shared.audit.repository import AuditLogRepository


def get_audit_log_repository(db: AsyncSession = Depends(get_db)) -> AuditLogRepository:
    return AuditLogRepository(db)

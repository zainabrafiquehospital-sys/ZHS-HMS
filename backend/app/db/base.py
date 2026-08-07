from datetime import datetime

from sqlalchemy import DateTime
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared declarative base. Feature modules define their models against
    this base via app/shared/base_entity.py's BaseEntity mixin.

    `type_annotation_map` makes every `Mapped[datetime]` column
    timezone-aware (`TIMESTAMPTZ`) by default, project-wide — the standard
    required by the Phase 0 architecture document — without needing to
    repeat `DateTime(timezone=True)` on every timestamp column.

    Deliberately contains NOTHING else — in particular, no feature-module
    model imports. See app/db/model_registry.py for why that responsibility
    was split into its own file rather than living here, as it originally
    did with only one feature module (auth) registered."""

    type_annotation_map = {datetime: DateTime(timezone=True)}

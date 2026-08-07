from enum import Enum as PyEnum

from pydantic import BaseModel


class SortOrder(str, PyEnum):
    """Shared ascending/descending direction for any paginated,
    sortable listing endpoint (`GET /users`, `GET /roles`, and future
    ones) — factored out here, alongside `PaginationParams`/
    `PaginationMeta`, once a second module needed the exact same enum
    `user_schemas.py` originally defined for itself. Each module keeps
    its own `*SortField` enum (e.g. `UserSortField`, `RoleSortField`),
    since which columns are sortable is genuinely module-specific; only
    the direction is generic."""

    ASC = "asc"
    DESC = "desc"


class PaginationParams(BaseModel):
    page: int = 1
    page_size: int = 20

    @property
    def limit(self) -> int:
        return self.page_size

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


class PaginationMeta(BaseModel):
    page: int
    page_size: int
    total: int

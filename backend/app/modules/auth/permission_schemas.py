"""Pydantic request/response schemas for the Permission Management
module (Phase 5 Step 4) — its own file, mirroring `role_schemas.py`'s
shape and conventions exactly.

`code` appears in `CreatePermissionRequest` but deliberately nowhere in
`UpdatePermissionRequest` — it is immutable after creation (see
permission_service.py's module docstring for why). Any `code` key a
client sends to the update endpoint is silently ignored, the same
default behavior every other schema in this codebase already has for
fields absent from its type (e.g. `UpdateUserRequest` never accepting
`status`).

`group` appears only in the response (`PermissionOut`), never in either
request — it is always derived from `code`'s prefix
(`validators.derive_permission_group`), never independently supplied;
see the `Permission` model's docstring for why."""

from datetime import datetime
from enum import Enum as PyEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.auth.models import Permission
from app.modules.auth.validators import validate_permission_code


class PermissionSortField(str, PyEnum):
    CREATED_AT = "created_at"
    CODE = "code"
    GROUP = "group"
    DISPLAY_NAME = "display_name"


# ---------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------


class CreatePermissionRequest(BaseModel):
    model_config = ConfigDict(strict=True)

    code: str = Field(min_length=3, max_length=100)
    display_name: str = Field(min_length=1, max_length=150)
    description: str | None = Field(default=None, max_length=2000)

    @field_validator("code")
    @classmethod
    def _validate_code(cls, value: str) -> str:
        validate_permission_code(value)
        return value


class UpdatePermissionRequest(BaseModel):
    """All fields optional for PATCH-style partial update — see
    `user_schemas.py`'s module docstring for the `exclude_unset`
    semantics `PermissionService` relies on. `display_name` may not be
    cleared to `null` (mirrors `name` on `UpdateRoleRequest`);
    `description` may (nullable, purely cosmetic)."""

    model_config = ConfigDict(strict=True)

    display_name: str | None = Field(default=None, min_length=1, max_length=150)
    description: str | None = Field(default=None, max_length=2000)


# ---------------------------------------------------------------------
# Responses
# ---------------------------------------------------------------------


class PermissionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    group: str
    display_name: str
    description: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_permission(cls, permission: Permission) -> "PermissionOut":
        return cls(
            id=permission.id,
            code=permission.code,
            group=permission.group,
            display_name=permission.display_name,
            description=permission.description,
            created_at=permission.created_at,
            updated_at=permission.updated_at,
        )

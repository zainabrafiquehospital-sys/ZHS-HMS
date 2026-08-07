"""Shared Pydantic field-type aliases used across request schemas.

`LaxUUID`: a plain `uuid.UUID` usable inside a model with
`ConfigDict(strict=True)`. JSON has no native UUID representation, so
every real client sends one as a string — but Pydantic v2's strict mode,
unlike `EmailStr` (whose own validator already treats a JSON string as
the only sensible input regardless of model-level strictness), requires
an in-memory `uuid.UUID` instance and rejects that string outright. A
bare per-field `Field(strict=False)` does not fix this when the field is
a container parametrized by `UUID` (e.g. `list[UUID]`) — Pydantic v2
does not propagate a field-level strictness override into a
parametrized generic's inner type — so the override has to sit on the
`UUID` type itself via `Annotated`, which is what this alias captures
once for every request schema (across modules) that needs a UUID, or a
list of UUIDs, from a JSON body under strict mode.

Plain (non-container) `Enum` fields hit this same strict-mode rejection
of a JSON string but have no equivalent shared alias here — each module
defines its own enum type (`PatientGender`, and future modules' own),
so there is nothing generic to factor out; each such field instead
takes a local `Field(strict=False)` directly, which — for a
non-container field — is sufficient on its own (see `LaxUUID`'s
docstring for why that stops being true only once the field becomes a
parametrized generic).

`LaxDecimal`: the identical problem, for `decimal.Decimal` — JSON has no
native decimal representation either (a real client sends a number or a
numeric string, e.g. `100.50`), and `ConfigDict(strict=True)` rejects
both a JSON number *and* a JSON string for a plain `Decimal` field
outright (verified empirically — unlike `date`, this isn't even a
one-representation problem; `Decimal` under strict mode accepts nothing
JSON can natively express). Discovered when the Billing module (Phase 6)
became the first schema in this codebase to accept money fields under a
strict model. Money is intentionally never `float` anywhere in this
codebase (see app/modules/billing/models.py's module docstring) —
`LaxDecimal` is what makes that possible at the request-schema boundary
too, not just the database column type."""

from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

LaxUUID = Annotated[UUID, Field(strict=False)]
LaxDecimal = Annotated[Decimal, Field(strict=False)]


class RoleSummary(BaseModel):
    """A role's id+name — the minimal projection needed anywhere a
    response embeds "which roles" without embedding a full `RoleOut`
    (which additionally carries permissions, hierarchy, and audit
    timestamps a caller displaying e.g. a user's role badges doesn't
    need). Originally defined in `user_schemas.py` for `UserAdminOut.roles`
    (Phase 5 Step 2); relocated here in Phase 5 Step 5 once
    `permission_router.py`'s "roles for a permission" endpoint needed
    the identical shape — the same deduplication `SortOrder` (Phase 5
    Step 3) and `LaxUUID` (this file, Phase 5 Step 4) already went
    through when a second module needed something a single module had
    originally defined for itself."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str

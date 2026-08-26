"""add inventory manager self service signup role

Revision ID: d3d6140ba992
Revises: 5df1ba802fd7
Create Date: 2026-08-26 12:40:00.000000

Adds "Inventory Manager" as a third self-service signup role, following
the exact Doctor precedent (8c263fc375ec/5f822ef61239) — with one real
difference in shape, not just substance: Doctor needed *two* migrations
because the first one (a rename) turned out to match zero rows in
production (there was no `demo-doctor-demo` role there at all — see
5f822ef61239's own docstring for that incident). This module investigated
that exact question *before* writing this migration, directly against
both dev and production (`railway connect postgres`, read-only): neither
environment has any Inventory-Manager-shaped role under any name, ad hoc
or otherwise — production's `role` table holds exactly admin/Doctor/
Receptionist/Vitals, and dev matches. So there is nothing to rename;
this migration creates the role fresh, in one pass, idempotently, and
should need no 5f822ef61239-style follow-up.

Two things, mirroring 8c263fc375ec's own two-things shape:

1. Extends `user_signup_role`'s CHECK constraint to allow
   `'inventory_manager'` alongside the existing `'receptionist'`/
   `'vitals'`/`'doctor'` values — same drop-and-recreate-by-hand
   approach (autogenerate does not diff the SQL body of an existing
   named CHECK constraint).

2. Creates the "Inventory Manager" role (get-or-create, so this is a
   no-op if it somehow already exists) and grants it exactly
   `inventory:read`/`inventory:manage` — both already exist as
   Permission rows as of 5df1ba802fd7, this migration's own
   `down_revision`; no new permissions invented here, only a new role
   and its grants. `inventory:record_usage`/`inventory:request_restock`
   are deliberately NOT granted here — those are Vitals' actions, not
   the Inventory Manager's (see app/modules/inventory/constants.py's
   own docstring), and 5df1ba802fd7 already granted them to the
   existing Vitals role.

Idempotent throughout, same `ON CONFLICT ... WHERE deleted_at IS NULL
DO NOTHING` approach against the existing partial unique index on
`role_permission` as every prior RBAC migration in this file already
establishes.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from uuid6 import uuid7

# revision identifiers, used by Alembic.
revision: str = "d3d6140ba992"
down_revision: str | None = "5df1ba802fd7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ORIGINAL_VALUES = ("receptionist", "vitals", "doctor")
_NEW_VALUES = ("receptionist", "vitals", "doctor", "inventory_manager")

_ROLE_NAME = "Inventory Manager"
_ROLE_DESCRIPTION = (
    "Ward/Emergency Inventory Management — catalog, Main Stock receipts, "
    "transfers to Emergency Stock, and restock-request fulfillment/rejection. "
    "Created fresh (no pre-existing role to rename — confirmed directly against "
    "both dev and production) by d3d6140ba992 so self-service Inventory Manager "
    "signup approval has a real role to resolve to on every environment."
)
_ROLE_PERMISSION_CODES = ("inventory:read", "inventory:manage")


def _in_clause(values: tuple[str, ...]) -> str:
    return "signup_role IN (" + ", ".join(f"'{value}'" for value in values) + ")"


def upgrade() -> None:
    op.drop_constraint("user_signup_role", "user", type_="check")
    op.create_check_constraint("user_signup_role", "user", _in_clause(_NEW_VALUES))

    conn = op.get_bind()
    role_row = conn.execute(
        sa.text("SELECT id FROM role WHERE name = :name AND deleted_at IS NULL"),
        {"name": _ROLE_NAME},
    ).first()
    if role_row is not None:
        role_id = role_row[0]
    else:
        role_id = uuid7()
        conn.execute(
            sa.text(
                "INSERT INTO role (id, name, description, is_system_role, is_active) "
                "VALUES (:id, :name, :description, true, true)"
            ),
            {"id": role_id, "name": _ROLE_NAME, "description": _ROLE_DESCRIPTION},
        )

    for code in _ROLE_PERMISSION_CODES:
        permission_row = conn.execute(
            sa.text("SELECT id FROM permission WHERE code = :code"), {"code": code}
        ).first()
        if permission_row is None:
            raise RuntimeError(
                f"expected permission {code!r} to already exist; "
                "this migration only grants existing permissions, never creates new ones"
            )
        conn.execute(
            sa.text(
                "INSERT INTO role_permission (id, role_id, permission_id) "
                "VALUES (:id, :role_id, :permission_id) "
                "ON CONFLICT (role_id, permission_id) WHERE deleted_at IS NULL DO NOTHING"
            ),
            {"id": uuid7(), "role_id": role_id, "permission_id": permission_row[0]},
        )


def downgrade() -> None:
    # Fails if any row already has signup_role = 'inventory_manager' —
    # expected and correct, same reasoning as 8c263fc375ec's own
    # downgrade: a downgrade that narrows an allowed-value set cannot
    # silently discard data that no longer satisfies it.
    op.drop_constraint("user_signup_role", "user", type_="check")
    op.create_check_constraint("user_signup_role", "user", _in_clause(_ORIGINAL_VALUES))

    # Revokes only the permission grants this migration is responsible
    # for — deliberately does not delete the "Inventory Manager" role
    # row itself, same reasoning as 5f822ef61239's/5df1ba802fd7's own
    # downgrades: it may have real users attached by the time anyone
    # downgrades.
    conn = op.get_bind()
    role_row = conn.execute(
        sa.text("SELECT id FROM role WHERE name = :name AND deleted_at IS NULL"),
        {"name": _ROLE_NAME},
    ).first()
    if role_row is None:
        return
    role_id = role_row[0]

    placeholders = ", ".join(f":code{i}" for i in range(len(_ROLE_PERMISSION_CODES)))
    params = {f"code{i}": code for i, code in enumerate(_ROLE_PERMISSION_CODES)}
    params["role_id"] = role_id
    conn.execute(
        sa.text(
            "DELETE FROM role_permission "
            "WHERE role_id = :role_id AND permission_id IN ("
            f"SELECT id FROM permission WHERE code IN ({placeholders})"
            ")"
        ),
        params,
    )

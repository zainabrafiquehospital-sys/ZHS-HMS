"""add inventory create_item permission and grants

Revision ID: db52db377c16
Revises: d128bf38b66e
Create Date: 2026-09-07 20:55:42.793337

Adds the narrow `inventory:create_item` permission — "add a new row to
the catalog, and nothing else" — following the exact "split by actor
and by action" precedent 5df1ba802fd7 established for
`inventory:record_usage`/`inventory:request_restock` (Vitals' own
narrow actions, split from `inventory:manage`).

The user wants BOTH the Inventory Manager and Vitals to be able to add
catalog items, but Vitals must NOT gain receive/transfer/restock-
fulfillment (those stay `inventory:manage`-only). `POST /inventory/items`
now accepts `inventory:create_item` OR `inventory:manage`
(require_any_permission), so:
  - grant `inventory:create_item` to `admin` (the "admin holds every
    permission that exists" invariant — same reasoning as 5df1ba802fd7's
    own admin grants), `Inventory Manager`, and `Vitals`.

Idempotent throughout — get-or-create the Permission row by `code`, and
`INSERT ... ON CONFLICT (role_id, permission_id) WHERE deleted_at IS
NULL DO NOTHING` against the existing partial unique index on
`role_permission`, exactly as 5df1ba802fd7/d3d6140ba992 already do.

No schema/table change: item soft-delete (the sibling change shipping
with this) reuses the `deleted_at` column every `BaseEntity` row
already has, and every item read path already filters it.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from uuid6 import uuid7

# revision identifiers, used by Alembic.
revision: str = "db52db377c16"
down_revision: str | None = "d128bf38b66e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CODE = "inventory:create_item"
_DISPLAY_NAME = "Add Inventory Items"
_DESCRIPTION = (
    "Add a new item to the inventory catalog. Does not grant Main Stock receipts, "
    "transfers to Emergency Stock, restock-request fulfillment, or item deletion."
)
_ROLE_NAMES = ("admin", "Inventory Manager", "Vitals")


def _get_or_create_permission(conn) -> object:
    row = conn.execute(
        sa.text("SELECT id FROM permission WHERE code = :code"), {"code": _CODE}
    ).first()
    if row is not None:
        return row[0]
    permission_id = uuid7()
    conn.execute(
        sa.text(
            'INSERT INTO permission (id, code, "group", display_name, description) '
            "VALUES (:id, :code, :group, :display_name, :description)"
        ),
        {
            "id": permission_id,
            "code": _CODE,
            "group": _CODE.split(":", 1)[0],
            "display_name": _DISPLAY_NAME,
            "description": _DESCRIPTION,
        },
    )
    return permission_id


def upgrade() -> None:
    conn = op.get_bind()
    permission_id = _get_or_create_permission(conn)

    for role_name in _ROLE_NAMES:
        role_row = conn.execute(
            sa.text("SELECT id FROM role WHERE name = :name AND deleted_at IS NULL"),
            {"name": role_name},
        ).first()
        if role_row is None:
            raise RuntimeError(f"expected role {role_name!r} to already exist")
        conn.execute(
            sa.text(
                "INSERT INTO role_permission (id, role_id, permission_id) "
                "VALUES (:id, :role_id, :permission_id) "
                "ON CONFLICT (role_id, permission_id) WHERE deleted_at IS NULL DO NOTHING"
            ),
            {"id": uuid7(), "role_id": role_row[0], "permission_id": permission_id},
        )


def downgrade() -> None:
    conn = op.get_bind()
    permission_row = conn.execute(
        sa.text("SELECT id FROM permission WHERE code = :code"), {"code": _CODE}
    ).first()
    if permission_row is None:
        return
    permission_id = permission_row[0]

    for role_name in _ROLE_NAMES:
        role_row = conn.execute(
            sa.text("SELECT id FROM role WHERE name = :name AND deleted_at IS NULL"),
            {"name": role_name},
        ).first()
        if role_row is None:
            continue
        conn.execute(
            sa.text(
                "DELETE FROM role_permission "
                "WHERE role_id = :role_id AND permission_id = :permission_id"
            ),
            {"role_id": role_row[0], "permission_id": permission_id},
        )

    # The Permission row itself is deliberately left in place — same
    # reasoning as 5df1ba802fd7's/4ad5462d0835's own downgrades:
    # removing a Permission row is a schema-adjacent action this
    # migration's upgrade never promised to cleanly reverse, and it may
    # have other grants attached by the time anyone downgrades.

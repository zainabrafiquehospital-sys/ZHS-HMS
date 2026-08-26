"""grant inventory permissions to admin and vitals

Revision ID: 5df1ba802fd7
Revises: 34031b5db2af
Create Date: 2026-08-26 11:48:32.284882

Creates the four `inventory:*` permission rows (they exist nowhere yet —
this is a brand-new module, unlike e.g. 4ad5462d0835's `reception:
view_slip`, which only needed a Role grant because the permission itself
was also new there) and grants:

- All four to the existing `admin` role. Unlike 4ad5462d0835 (which did
  NOT need to grant its new `reception:view_slip` to admin, because
  admin already held the broader `reception:register_visit` from the
  original launch-bootstrap seed, which alone satisfied that endpoint's
  `require_any_permission` check), there is no broader pre-existing
  permission that covers Inventory at all — admin needs every one of
  these granted explicitly here, or the "admin holds every permission
  that exists" invariant `scripts/seed_launch_bootstrap.py` establishes
  on a fresh install silently breaks on this already-seeded database the
  moment this module ships.
- `inventory:read`/`inventory:record_usage`/`inventory:request_restock`
  (not `inventory:manage`, which is Inventory-Manager-only) to the
  existing `Vitals` role — Vitals records usage and raises restock
  requests starting with this module's frontend rollout.

The brand-new "Inventory Manager" role itself is deliberately NOT
created here — it doesn't exist yet; that's a later, separate migration
alongside the self-service-signup rollout (the exact same two-step
shape `8c263fc375ec`/`5f822ef61239` already established for Doctor:
role/signup wiring first, RBAC-only additions to already-existing roles
can and do ship independently).

Idempotent throughout, same `ON CONFLICT ... WHERE deleted_at IS NULL
DO NOTHING` approach against the existing partial unique index on
`role_permission` as 4ad5462d0835/5f822ef61239 already established, and
the same find-or-create-by-code shape for the Permission rows themselves.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from uuid6 import uuid7

# revision identifiers, used by Alembic.
revision: str = "5df1ba802fd7"
down_revision: str | None = "34031b5db2af"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PERMISSIONS: tuple[tuple[str, str, str], ...] = (
    (
        "inventory:read",
        "View Inventory",
        "View the inventory catalog, both stock levels, transfer/usage history, and "
        "restock requests.",
    ),
    (
        "inventory:manage",
        "Manage Inventory",
        "Manage the inventory catalog, record Main Stock receipts, transfer stock to "
        "Emergency Stock, and fulfill/reject restock requests.",
    ),
    (
        "inventory:record_usage",
        "Record Inventory Usage",
        "Record an Emergency Stock item as used against a patient.",
    ),
    (
        "inventory:request_restock",
        "Request Inventory Restock",
        "Raise a restock request against a low/out Emergency Stock item.",
    ),
)

_ADMIN_CODES = [code for code, _, _ in _PERMISSIONS]
_VITALS_CODES = ["inventory:read", "inventory:record_usage", "inventory:request_restock"]


def _get_or_create_permission(conn, code: str, display_name: str, description: str):
    row = conn.execute(
        sa.text("SELECT id FROM permission WHERE code = :code"), {"code": code}
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
            "code": code,
            "group": code.split(":", 1)[0],
            "display_name": display_name,
            "description": description,
        },
    )
    return permission_id


def _grant(conn, *, role_name: str, permission_id) -> None:
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


def upgrade() -> None:
    conn = op.get_bind()

    permission_ids_by_code = {
        code: _get_or_create_permission(conn, code, display_name, description)
        for code, display_name, description in _PERMISSIONS
    }

    for code in _ADMIN_CODES:
        _grant(conn, role_name="admin", permission_id=permission_ids_by_code[code])

    for code in _VITALS_CODES:
        _grant(conn, role_name="Vitals", permission_id=permission_ids_by_code[code])


def downgrade() -> None:
    conn = op.get_bind()

    for role_name, codes in (("admin", _ADMIN_CODES), ("Vitals", _VITALS_CODES)):
        role_row = conn.execute(
            sa.text("SELECT id FROM role WHERE name = :name AND deleted_at IS NULL"),
            {"name": role_name},
        ).first()
        if role_row is None:
            continue
        placeholders = ", ".join(f":code{i}" for i in range(len(codes)))
        params = {f"code{i}": code for i, code in enumerate(codes)}
        params["role_id"] = role_row[0]
        conn.execute(
            sa.text(
                "DELETE FROM role_permission "
                "WHERE role_id = :role_id AND permission_id IN ("
                f"SELECT id FROM permission WHERE code IN ({placeholders})"
                ")"
            ),
            params,
        )
    # The four Permission rows themselves are deliberately left in place —
    # same reasoning as 4ad5462d0835's own downgrade: removing a
    # Permission row is a schema-adjacent action this migration's own
    # upgrade never promised to cleanly reverse, and it may have other
    # grants attached by the time anyone downgrades.

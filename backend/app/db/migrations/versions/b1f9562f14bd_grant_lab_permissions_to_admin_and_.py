"""grant lab permissions to admin and receptionist

Revision ID: b1f9562f14bd
Revises: 26d08c008ed7
Create Date: 2026-08-27 21:50:00.000000

Creates the five `lab:*` permission rows (they exist nowhere yet — this
is a brand-new module, same shape as 5df1ba802fd7's identical
`inventory:*` addition) and grants:

- All five to the existing `admin` role — there is no broader
  pre-existing permission that covers Lab at all, so admin needs every
  one of these granted explicitly here, or the "admin holds every
  permission that exists" invariant `scripts/seed_launch_bootstrap.py`
  establishes on a fresh install silently breaks on this already-seeded
  database the moment this module ships (same reasoning 5df1ba802fd7's
  own docstring already gives for Inventory).
- `lab:read`/`lab:bill` (not `lab:manage`/`lab:update_bill`/
  `lab:delete_bill`, all three Admin-only) to the existing
  `Receptionist` role — confirmed design: Reception operates Laboratory
  billing directly, the same existing role that already handles Visit
  registration and Pharmacy's own `pharmacy:read`/`pharmacy:bill`, no
  new role or signup flow needed for this module at all.

Idempotent throughout, same `ON CONFLICT ... WHERE deleted_at IS NULL
DO NOTHING` approach against the existing partial unique index on
`role_permission` as 5df1ba802fd7 already established, and the same
find-or-create-by-code shape for the Permission rows themselves.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from uuid6 import uuid7

# revision identifiers, used by Alembic.
revision: str = "b1f9562f14bd"
down_revision: str | None = "26d08c008ed7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PERMISSIONS: tuple[tuple[str, str, str], ...] = (
    (
        "lab:read",
        "View Lab Bills",
        "View the lab test catalog and every lab bill, its tests, and its payment status.",
    ),
    (
        "lab:bill",
        "Create Lab Bills",
        "Search the lab test catalog and build/finalize a lab bill.",
    ),
    (
        "lab:manage",
        "Manage Lab Test Catalog",
        "Create, edit, and deactivate lab tests in the price list.",
    ),
    (
        "lab:update_bill",
        "Correct Lab Bills",
        "Correct a mistakenly-entered lab bill's manual patient details or discount.",
    ),
    (
        "lab:delete_bill",
        "Delete Lab Bills",
        "Delete a mistakenly-created lab bill that has no recorded payment.",
    ),
)

_ADMIN_CODES = [code for code, _, _ in _PERMISSIONS]
_RECEPTIONIST_CODES = ["lab:read", "lab:bill"]


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

    for code in _RECEPTIONIST_CODES:
        _grant(conn, role_name="Receptionist", permission_id=permission_ids_by_code[code])


def downgrade() -> None:
    conn = op.get_bind()

    for role_name, codes in (("admin", _ADMIN_CODES), ("Receptionist", _RECEPTIONIST_CODES)):
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
    # The five Permission rows themselves are deliberately left in place
    # — same reasoning 5df1ba802fd7's own downgrade already gives.

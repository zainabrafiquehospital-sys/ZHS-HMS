"""add patients history read permission

Revision ID: 6935f2038643
Revises: 946aa0d850df
Create Date: 2026-08-31 20:40:14.444695

Creates the new `patients:history:read` permission (gates the
cross-module "Patient History" search page — see
app/modules/patient_history/router.py) and grants it to every role that
feature is meant to reach: `Receptionist`, `Vitals`, and `Doctor` (all
three already exist as real roles — see 5f822ef61239's own precedent
for "Doctor" specifically). `admin` is deliberately not granted here —
it already gets every Permission row automatically via
scripts/seed_launch_bootstrap.py's own "admin holds the full catalog"
step, and that remains true for this one too without a separate grant.

Same `_get_or_create_permission`/`_grant` shape and the same
`ON CONFLICT ... WHERE deleted_at IS NULL DO NOTHING` idempotency as
4ad5462d0835 (which created `reception:view_slip` the identical way) —
safe to run against an environment that already has some or all of
these grants.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from uuid6 import uuid7

# revision identifiers, used by Alembic.
revision: str = "6935f2038643"
down_revision: str | None = "946aa0d850df"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CODE = "patients:history:read"
_DISPLAY_NAME = "View Patient History"
_DESCRIPTION = (
    "View a patient's full aggregated history (visits, vitals, consultations, billing, "
    "lab bills, pharmacy bills) via the cross-module Patient History search. Each "
    "section within the response is further scoped to whichever of those the actor "
    "already holds read access to on their own — this permission only gates reaching "
    "the search itself."
)

_GRANTED_TO_ROLES = ("Receptionist", "Vitals", "Doctor")


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

    permission_id = _get_or_create_permission(conn, _CODE, _DISPLAY_NAME, _DESCRIPTION)
    for role_name in _GRANTED_TO_ROLES:
        _grant(conn, role_name=role_name, permission_id=permission_id)


def downgrade() -> None:
    conn = op.get_bind()

    for role_name in _GRANTED_TO_ROLES:
        conn.execute(
            sa.text(
                "DELETE FROM role_permission WHERE role_id = ("
                "  SELECT id FROM role WHERE name = :role_name AND deleted_at IS NULL"
                ") AND permission_id = ("
                "  SELECT id FROM permission WHERE code = :code"
                ")"
            ),
            {"role_name": role_name, "code": _CODE},
        )
    # The Permission row itself is deliberately left in place — same
    # reasoning as 4ad5462d0835's own downgrade for `reception:view_slip`.

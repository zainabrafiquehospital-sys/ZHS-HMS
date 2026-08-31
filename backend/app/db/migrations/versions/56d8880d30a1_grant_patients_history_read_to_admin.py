"""grant patients history read to admin

Revision ID: 56d8880d30a1
Revises: 6935f2038643
Create Date: 2026-08-31 23:53:00.409552

Fixes a real bug found via live testing: 6935f2038643's own downgrade
comment claimed admin "gets it automatically via scripts/
seed_launch_bootstrap.py's own 'admin holds the full catalog' step" —
true only for a *fresh* environment where that script is (re-)run
after this permission already exists in the catalog. On an
already-bootstrapped environment (every real one, including this
project's own dev database), that script has already run once, in the
past, and nothing re-runs its "grant admin every catalog permission"
loop just because a later migration adds a new Permission row —
confirmed directly: `admin` held every other permission but not this
one, and the Patient History page silently rendered nothing useful
for an admin account (every section requires the section's own read
permission on top of `patients:history:read`, so missing the latter
made the whole page a dead end). Grants it explicitly here instead of
relying on that assumption.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from uuid6 import uuid7

# revision identifiers, used by Alembic.
revision: str = "56d8880d30a1"
down_revision: str | None = "6935f2038643"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CODE = "patients:history:read"


def upgrade() -> None:
    conn = op.get_bind()

    permission_row = conn.execute(
        sa.text("SELECT id FROM permission WHERE code = :code"), {"code": _CODE}
    ).first()
    if permission_row is None:
        raise RuntimeError(f"expected permission {_CODE!r} to already exist (see 6935f2038643)")
    permission_id = permission_row[0]

    role_row = conn.execute(
        sa.text("SELECT id FROM role WHERE name = 'admin' AND deleted_at IS NULL")
    ).first()
    if role_row is None:
        raise RuntimeError("expected role 'admin' to already exist")

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
    conn.execute(
        sa.text(
            "DELETE FROM role_permission WHERE role_id = ("
            "  SELECT id FROM role WHERE name = 'admin' AND deleted_at IS NULL"
            ") AND permission_id = ("
            "  SELECT id FROM permission WHERE code = :code"
            ")"
        ),
        {"code": _CODE},
    )

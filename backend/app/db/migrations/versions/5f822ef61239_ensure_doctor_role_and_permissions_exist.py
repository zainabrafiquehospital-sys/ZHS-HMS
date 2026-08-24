"""ensure doctor role and permissions exist

Revision ID: 5f822ef61239
Revises: 8c263fc375ec
Create Date: 2026-08-24 17:02:11.000000

Follow-up to 8c263fc375ec, written after verifying that migration's
actual effect directly against the live production database rather
than trusting its clean deploy-log exit alone: production never had a
`demo-doctor-demo` role to rename in the first place (that ad hoc
role, and the one existing "Doctor Demo" account holding it, are local
dev-environment artifacts only) — so 8c263fc375ec's rename `UPDATE`
matched zero rows there, and production is left with no "Doctor" role
at all. `UserService.approve_signup` would raise `RoleNotFoundError`
the moment anyone actually tried to approve a Doctor self-service
signup in production.

Idempotent by construction rather than "only run if missing", so it
self-heals correctly on every environment regardless of starting
state:
- dev already has a "Doctor" role (from 8c263fc375ec's rename) — this
  migration is a no-op there beyond confirming every permission below
  is already granted (it is, per that role's own history).
- production has no "Doctor" role at all — this migration creates one
  and grants it the exact permission set confirmed directly against
  dev's own "Doctor" role before writing this file: consultation:start/
  manage/read, billing:submit_charge, dashboard:doctor:read,
  queue:read, visits:read, vitals:read. No new permissions invented —
  every one of these already exists as a `permission` row (granted to
  other roles already), only the grant to a "Doctor" role is new where
  missing.

Raw SQL via `op.get_bind()`, not the ORM/repositories `scripts/
seed_launch_bootstrap.py` uses for the same get-or-create pattern —
migrations in this codebase never import application code, consistent
with every other migration in this directory. Role-permission grants
use `ON CONFLICT ... WHERE deleted_at IS NULL DO NOTHING` against
`ix_role_permission_role_id_permission_id_active` (the same partial
unique index RolePermission's own model already declares), so this is
safe to run against a role that already holds some or all of these
permissions without erroring or duplicating a grant.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from uuid6 import uuid7

# revision identifiers, used by Alembic.
revision: str = "5f822ef61239"
down_revision: str | None = "8c263fc375ec"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DOCTOR_PERMISSION_CODES = (
    "consultation:start",
    "consultation:manage",
    "consultation:read",
    "billing:submit_charge",
    "dashboard:doctor:read",
    "queue:read",
    "visits:read",
    "vitals:read",
)

_ROLE_DESCRIPTION = (
    "Doctor consultation workflow, mid-consult vitals requests, and "
    "billing charge requests — created (or, on an environment where it "
    "already existed under a different name, confirmed) by "
    "5f822ef61239 so self-service Doctor signup approval has a real "
    "role to resolve to on every environment."
)


def upgrade() -> None:
    conn = op.get_bind()

    role_row = conn.execute(
        sa.text("SELECT id FROM role WHERE name = 'Doctor' AND deleted_at IS NULL")
    ).first()
    if role_row is not None:
        role_id = role_row[0]
    else:
        role_id = uuid7()
        conn.execute(
            sa.text(
                "INSERT INTO role (id, name, description, is_system_role, is_active) "
                "VALUES (:id, 'Doctor', :description, true, true)"
            ),
            {"id": role_id, "description": _ROLE_DESCRIPTION},
        )

    for code in _DOCTOR_PERMISSION_CODES:
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
    # Revokes only the permission grants this migration is responsible
    # for — deliberately does not delete the "Doctor" role row itself,
    # which may pre-date this migration (dev, via 8c263fc375ec's rename)
    # or may already have real users/other grants attached by the time
    # anyone downgrades; removing it here risks orphaning either.
    conn = op.get_bind()
    role_row = conn.execute(
        sa.text("SELECT id FROM role WHERE name = 'Doctor' AND deleted_at IS NULL")
    ).first()
    if role_row is None:
        return
    role_id = role_row[0]

    placeholders = ", ".join(f":code{i}" for i in range(len(_DOCTOR_PERMISSION_CODES)))
    params = {f"code{i}": code for i, code in enumerate(_DOCTOR_PERMISSION_CODES)}
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

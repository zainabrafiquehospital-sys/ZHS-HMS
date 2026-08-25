"""grant patients read to doctor and vitals plus reception view slip

Revision ID: 4ad5462d0835
Revises: 5f822ef61239
Create Date: 2026-08-25 09:10:00.000000

Two independent RBAC fixes, both found investigating a live production
bug report (Doctor Queue's PATIENT column stuck on "…"):

1. Neither the Doctor nor the Vitals role holds `patients:read` —
   confirmed directly against the live database before writing this
   migration. `usePatientsForVisits` (frontend/src/features/patients/
   hooks/usePatientsForVisits.js, shared by DoctorQueueList.jsx and the
   Vitals worklist) calls `GET /patients/{id}` per unique patient,
   gated on that permission; every call 403s, the join never
   populates, and the component's own `patient ? ... : '…'` fallback
   renders permanently — not a stuck loading state or a broken join,
   an unhandled 403 that looks identical to one. Grants `patients:read`
   to both roles (idempotent — a no-op if either already somehow holds
   it).

2. Doctors need to view (not manage) a registration slip from the
   Doctor Queue's new "View Slip" button
   (GET /reception/visits/{id}/slip/print), which was gated on
   `reception:register_visit` — the composite register/cancel-visit
   capability, far broader than "view a slip" and not something a
   Doctor should hold. Rather than granting that, this creates a new,
   narrower `reception:view_slip` permission and grants it to Doctor
   only — Reception's own access to the same endpoint is unaffected
   (see app/modules/reception/dependencies.py's new
   `require_any_permission`, which the endpoint now uses instead of
   `require_permission`: `reception:register_visit` alone still
   satisfies it for Reception, `reception:view_slip` is the new,
   narrower path for Doctor).

Idempotent throughout, same `ON CONFLICT ... WHERE deleted_at IS NULL
DO NOTHING` approach against the existing partial unique index on
`role_permission` as 5f822ef61239 already established.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from uuid6 import uuid7

# revision identifiers, used by Alembic.
revision: str = "4ad5462d0835"
down_revision: str | None = "5f822ef61239"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_VIEW_SLIP_CODE = "reception:view_slip"
_VIEW_SLIP_DISPLAY_NAME = "View Registration Slip"
_VIEW_SLIP_DESCRIPTION = (
    "View/print a visit's registration slip without the full reception:register_visit "
    "capability — e.g. a doctor checking what was registered (procedures, discount, "
    "payment status) from the Doctor Queue."
)


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

    patients_read_row = conn.execute(
        sa.text("SELECT id FROM permission WHERE code = 'patients:read'")
    ).first()
    if patients_read_row is None:
        raise RuntimeError("expected permission 'patients:read' to already exist")
    patients_read_id = patients_read_row[0]
    _grant(conn, role_name="Doctor", permission_id=patients_read_id)
    _grant(conn, role_name="Vitals", permission_id=patients_read_id)

    view_slip_id = _get_or_create_permission(
        conn, _VIEW_SLIP_CODE, _VIEW_SLIP_DISPLAY_NAME, _VIEW_SLIP_DESCRIPTION
    )
    _grant(conn, role_name="Doctor", permission_id=view_slip_id)


def downgrade() -> None:
    conn = op.get_bind()

    for role_name, code in (
        ("Doctor", "patients:read"),
        ("Vitals", "patients:read"),
        ("Doctor", _VIEW_SLIP_CODE),
    ):
        conn.execute(
            sa.text(
                "DELETE FROM role_permission WHERE role_id = ("
                "  SELECT id FROM role WHERE name = :role_name AND deleted_at IS NULL"
                ") AND permission_id = ("
                "  SELECT id FROM permission WHERE code = :code"
                ")"
            ),
            {"role_name": role_name, "code": code},
        )
    # The `reception:view_slip` Permission row itself is deliberately
    # left in place, same reasoning as 5f822ef61239's own downgrade for
    # the "Doctor" role row: it may have other grants attached by the
    # time anyone downgrades, and removing a Permission row is a
    # schema-adjacent action this migration's own upgrade never
    # promised to be able to cleanly reverse.

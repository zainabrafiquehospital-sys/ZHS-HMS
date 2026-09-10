"""create expense table and expenses permissions

Revision ID: 535215ba6d04
Revises: db52db377c16
Create Date: 2026-09-10 12:00:00.000000

Additive, going-forward only — the Expense Tracking feature for the
Receptionist role.

1. `expense` table (BaseEntity shape): `receptionist_id` (required FK to
   user), `amount` (Numeric(10,2), CHECK > 0), `reason`,
   `recipient_name`, `expense_date` (a real Date column holding the
   Asia/Karachi calendar day the expense was logged — set server-side,
   never a client value). Two indexes: `(receptionist_id, expense_date)`
   for a receptionist's own per-day list and the Net Revenue deduction
   path, and `(expense_date)` for Admin's cross-receptionist per-day
   list/breakdown.

2. Two permissions (find-or-create by code, same shape 5df1ba802fd7
   uses):
   - `expenses:log` — granted to the `Receptionist` role and `admin`.
   - `expenses:read_all` — granted to `admin` only.
   Idempotent `INSERT ... ON CONFLICT (role_id, permission_id) WHERE
   deleted_at IS NULL DO NOTHING` against the existing partial unique
   index on `role_permission`.

No backfill, no data migration of any existing row.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from uuid6 import uuid7

# revision identifiers, used by Alembic.
revision: str = "535215ba6d04"
down_revision: str | None = "db52db377c16"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PERMISSIONS: tuple[tuple[str, str, str], ...] = (
    (
        "expenses:log",
        "Log Cash Expenses",
        "Log a same-day cash expense (amount, reason, recipient) and view, edit, or "
        "delete your own expenses while the day is still current.",
    ),
    (
        "expenses:read_all",
        "View All Expenses",
        "View every receptionist's cash expenses for a day and the per-receptionist "
        "breakdown. Admin only.",
    ),
)
_GRANTS: dict[str, tuple[str, ...]] = {
    "expenses:log": ("Receptionist", "admin"),
    "expenses:read_all": ("admin",),
}


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


def upgrade() -> None:
    op.create_table(
        "expense",
        sa.Column("receptionist_id", sa.Uuid(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("reason", sa.String(length=200), nullable=False),
        sa.Column("recipient_name", sa.String(length=150), nullable=False),
        sa.Column("expense_date", sa.Date(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.CheckConstraint("amount > 0", name="ck_expense_amount_positive"),
        sa.ForeignKeyConstraint(["created_by"], ["user.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["user.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["receptionist_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_expense_receptionist_id_expense_date",
        "expense",
        ["receptionist_id", "expense_date"],
        unique=False,
    )
    op.create_index("ix_expense_expense_date", "expense", ["expense_date"], unique=False)

    conn = op.get_bind()
    permission_ids_by_code = {
        code: _get_or_create_permission(conn, code, display_name, description)
        for code, display_name, description in _PERMISSIONS
    }
    for code, role_names in _GRANTS.items():
        permission_id = permission_ids_by_code[code]
        for role_name in role_names:
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
    codes = [code for code, _, _ in _PERMISSIONS]
    placeholders = ", ".join(f":code{i}" for i in range(len(codes)))
    params = {f"code{i}": code for i, code in enumerate(codes)}
    conn.execute(
        sa.text(
            "DELETE FROM role_permission WHERE permission_id IN ("
            f"SELECT id FROM permission WHERE code IN ({placeholders}))"
        ),
        params,
    )
    # Permission rows themselves are left in place — same reasoning as
    # 5df1ba802fd7's own downgrade.

    op.drop_index("ix_expense_expense_date", table_name="expense")
    op.drop_index("ix_expense_receptionist_id_expense_date", table_name="expense")
    op.drop_table("expense")

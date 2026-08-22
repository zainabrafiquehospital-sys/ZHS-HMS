"""add visit payment tracking

Revision ID: 954a7e0c382a
Revises: 6f0b9add24e8
Create Date: 2026-08-22 11:30:43.859285

Purely additive, mirroring the itemized-procedures migration
(6f0b9add24e8) immediately before it: one new table (`visit_payment`)
and three new *nullable* columns on `visit` (`amount_paid`,
`payment_status`, `paid_at`) — no existing row is ever touched or
backfilled. `payment_status IS NULL` is the permanent signal "this
visit predates payment tracking" every reader (print, the admin edit/
delete guard, the Pending Revenue aggregate) branches on; see
app/modules/visits/models.py's `Visit.payment_status` docstring for the
full rationale, including why this deliberately does NOT follow the
`payment_method` column's own "backfill to the one known-correct value"
precedent.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "954a7e0c382a"
down_revision: str | None = "6f0b9add24e8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PAYMENT_METHOD_ENUM = sa.Enum(
    "cash",
    "bank_transfer",
    "jazzcash",
    "easypaisa",
    "card",
    name="payment_method",
    native_enum=False,
    create_constraint=True,
    length=20,
)

_VISIT_PAYMENT_STATUS_ENUM = sa.Enum(
    "unpaid",
    "partially_paid",
    "paid",
    name="visit_payment_status",
    native_enum=False,
    create_constraint=True,
    length=20,
)


def upgrade() -> None:
    op.create_table(
        "visit_payment",
        sa.Column("visit_id", sa.Uuid(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("payment_method", _PAYMENT_METHOD_ENUM, nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.CheckConstraint("amount > 0", name="ck_visit_payment_amount_positive"),
        sa.ForeignKeyConstraint(["created_by"], ["user.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["user.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["visit_id"], ["visit.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_visit_payment_visit_id", "visit_payment", ["visit_id"], unique=False)

    # All three nullable, no backfill — see this migration's own
    # module docstring for why.
    op.add_column("visit", sa.Column("amount_paid", sa.Numeric(precision=10, scale=2), nullable=True))
    op.add_column("visit", sa.Column("payment_status", _VISIT_PAYMENT_STATUS_ENUM, nullable=True))
    op.add_column("visit", sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True))

    # NULL-safe by ordinary SQL CHECK semantics — a NULL amount_paid
    # (every pre-existing visit) always passes both, no explicit
    # "OR amount_paid IS NULL" needed. See models.py's own comment.
    op.create_check_constraint(
        "ck_visit_amount_paid_non_negative", "visit", "amount_paid >= 0"
    )
    op.create_check_constraint(
        "ck_visit_amount_paid_not_exceeding_amount", "visit", "amount_paid <= amount"
    )


def downgrade() -> None:
    op.drop_constraint("ck_visit_amount_paid_not_exceeding_amount", "visit", type_="check")
    op.drop_constraint("ck_visit_amount_paid_non_negative", "visit", type_="check")
    op.drop_column("visit", "paid_at")
    op.drop_column("visit", "payment_status")
    op.drop_column("visit", "amount_paid")
    op.drop_index("ix_visit_payment_visit_id", table_name="visit_payment")
    op.drop_table("visit_payment")

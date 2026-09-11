"""add stock_quantity to medicine

Revision ID: 31ec60d291fe
Revises: 535215ba6d04
Create Date: 2026-09-11 04:23:37.683693

Additive, going-forward only — the Pharmacy medicine stock-tracking
feature. One `Integer` column on `medicine`, NOT NULL, `server_default`
0 so every existing row is backfilled to 0 atomically in the same
`ADD COLUMN` (no separate UPDATE pass needed, unlike dcbd18f38b39's
nullable-then-backfill-then-NOT-NULL dance — that was for a Numeric with
no natural SQL literal default; `0` is). The `server_default` is kept,
not dropped: `stock_quantity` genuinely defaults to 0 for a brand-new
medicine (added via the price-list form, stock received separately),
matching the model's own `default=0`.

`CHECK (stock_quantity >= 0)` is absolute — a bill sale that would drive
it negative (only reachable via `create_bill`'s explicit override flag)
clamps the decrement at 0 in the service, so the constraint is a real
backstop, not just belt-and-braces. Mirrors every other
non-negative-quantity CHECK in this codebase (`inventory_item.
main_stock_level >= 0`, `medicine_bill.amount_paid >= 0`, ...).

No new permission rows: the stock-management endpoint reuses the
existing `pharmacy:manage` grant.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "31ec60d291fe"
down_revision: str | None = "535215ba6d04"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "medicine",
        sa.Column(
            "stock_quantity",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.create_check_constraint(
        "ck_medicine_stock_quantity_non_negative", "medicine", "stock_quantity >= 0"
    )


def downgrade() -> None:
    op.drop_constraint("ck_medicine_stock_quantity_non_negative", "medicine", type_="check")
    op.drop_column("medicine", "stock_quantity")

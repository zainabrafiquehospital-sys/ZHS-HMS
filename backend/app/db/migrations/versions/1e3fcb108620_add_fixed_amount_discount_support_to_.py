"""add fixed amount discount support to billing invoice

Revision ID: 1e3fcb108620
Revises: 259575518b9d
Create Date: 2026-08-12 23:21:33.529182

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "1e3fcb108620"
down_revision: str | None = "259575518b9d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # `discount_amount` — added nullable first (existing invoices have
    # no value yet), backfilled to 0.00 (no pre-existing invoice was
    # ever discounted; this feature did not exist before now), then
    # made NOT NULL. `discount_reason` stays nullable — it is only ever
    # populated when `discount_amount > 0` (see BillingService.
    # generate_invoice's docstring).
    op.add_column(
        "invoice",
        sa.Column("discount_amount", sa.Numeric(precision=10, scale=2), nullable=True),
    )
    op.add_column("invoice", sa.Column("discount_reason", sa.String(length=200), nullable=True))
    op.execute("UPDATE invoice SET discount_amount = 0.00")
    op.alter_column("invoice", "discount_amount", nullable=False)
    op.create_check_constraint(
        "ck_invoice_discount_amount_non_negative", "invoice", "discount_amount >= 0"
    )


def downgrade() -> None:
    op.drop_constraint("ck_invoice_discount_amount_non_negative", "invoice", type_="check")
    op.drop_column("invoice", "discount_reason")
    op.drop_column("invoice", "discount_amount")

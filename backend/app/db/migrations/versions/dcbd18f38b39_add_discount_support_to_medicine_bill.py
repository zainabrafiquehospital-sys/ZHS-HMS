"""add discount support to medicine bill

Revision ID: dcbd18f38b39
Revises: b73e8bf4527b
Create Date: 2026-08-19 16:28:17.938606

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "dcbd18f38b39"
down_revision: str | None = "b73e8bf4527b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Mirrors 1e3fcb108620's identical Invoice discount migration exactly:
    # `discount_amount` added nullable first (existing bills have no
    # value yet), backfilled to 0.00 (no pre-existing bill was ever
    # discounted; this feature did not exist before now), then made NOT
    # NULL. `discount_reason` stays nullable — unlike Invoice's own
    # discount_reason, it is optional even when discount_amount > 0 (a
    # deliberate difference for this feature, see PharmacyService.
    # create_bill's docstring).
    op.add_column(
        "medicine_bill",
        sa.Column("discount_amount", sa.Numeric(precision=10, scale=2), nullable=True),
    )
    op.add_column(
        "medicine_bill", sa.Column("discount_reason", sa.String(length=200), nullable=True)
    )
    op.execute("UPDATE medicine_bill SET discount_amount = 0.00")
    op.alter_column("medicine_bill", "discount_amount", nullable=False)
    op.create_check_constraint(
        "ck_medicine_bill_discount_amount_non_negative", "medicine_bill", "discount_amount >= 0"
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_medicine_bill_discount_amount_non_negative", "medicine_bill", type_="check"
    )
    op.drop_column("medicine_bill", "discount_reason")
    op.drop_column("medicine_bill", "discount_amount")

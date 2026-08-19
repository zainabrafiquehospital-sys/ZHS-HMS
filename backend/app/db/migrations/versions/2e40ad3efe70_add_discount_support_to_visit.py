"""add discount support to visit

Revision ID: 2e40ad3efe70
Revises: dcbd18f38b39
Create Date: 2026-08-19 18:10:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "2e40ad3efe70"
down_revision: str | None = "dcbd18f38b39"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Mirrors dcbd18f38b39's identical MedicineBill discount migration
    # exactly: `discount_amount` added nullable first (existing visits
    # have no value yet), backfilled to 0.00 (no pre-existing visit was
    # ever discounted; this feature did not exist before now), then made
    # NOT NULL. `discount_reason` stays nullable — optional even when
    # discount_amount > 0, same product decision as the medicine-bill
    # discount (see VisitService.register_visit's docstring).
    op.add_column(
        "visit", sa.Column("discount_amount", sa.Numeric(precision=10, scale=2), nullable=True)
    )
    op.add_column("visit", sa.Column("discount_reason", sa.String(length=200), nullable=True))
    op.execute("UPDATE visit SET discount_amount = 0.00")
    op.alter_column("visit", "discount_amount", nullable=False)
    op.create_check_constraint(
        "ck_visit_discount_amount_non_negative", "visit", "discount_amount >= 0"
    )


def downgrade() -> None:
    op.drop_constraint("ck_visit_discount_amount_non_negative", "visit", type_="check")
    op.drop_column("visit", "discount_reason")
    op.drop_column("visit", "discount_amount")

"""add carried by name to inventory transfer

Revision ID: 52488f320729
Revises: d3d6140ba992
Create Date: 2026-08-27 19:43:27.990613

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "52488f320729"
down_revision: str | None = "d3d6140ba992"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Same shape as 86d5b20afa17 (medicine_bill.queue_token) — nullable,
    # no backfill, and stays nullable forever: pre-existing transfer
    # rows predate "who carried it" entirely, so there is no honest
    # value to write back for them. Every transfer created from this
    # migration onward is required (at the request-schema level, see
    # TransferStockRequest/FulfillRestockRequestRequest) to supply one.
    op.add_column(
        "inventory_transfer", sa.Column("carried_by_name", sa.String(length=150), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("inventory_transfer", "carried_by_name")

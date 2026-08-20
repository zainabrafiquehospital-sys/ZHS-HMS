"""add unified queue token to medicine bill

Revision ID: 86d5b20afa17
Revises: 996d7b2f2ae6
Create Date: 2026-08-20 13:20:28.852334

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "86d5b20afa17"
down_revision: str | None = "996d7b2f2ae6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Deliberately DIFFERENT shape from every other additive-column
    # migration this codebase has (e.g. dcbd18f38b39's discount_amount):
    # those backfill a correct historical value and then go NOT NULL.
    # There is no honest value to backfill here — pre-existing medicine
    # bills were never assigned a token at all (their printed number was
    # just a UUID fragment, see MedicineBill.queue_token's own docstring
    # and app/modules/pharmacy/service.py's `_generate_queue_token`) — so
    # this column is added nullable and MUST stay nullable forever. No
    # UPDATE/backfill step, no subsequent `alter_column(nullable=False)`.
    # Existing bills keep `queue_token = NULL` and keep printing their old
    # UUID-fragment fallback; only bills created after this migration draw
    # a real token, from the exact same Postgres sequence
    # (`visit_queue_token_seq`, see app/modules/visits/constants.py's
    # QUEUE_TOKEN_SEQUENCE_NAME) that Visit's own queue_token already
    # uses — the unification is that both modules draw from one literal
    # sequence object, not that old rows get renumbered.
    op.add_column("medicine_bill", sa.Column("queue_token", sa.String(length=20), nullable=True))
    # Unique partial index mirroring ix_visit_queue_token_active's exact
    # shape — collisions are structurally impossible (one shared
    # sequence), this is for lookup integrity/performance, not
    # collision prevention.
    op.create_index(
        "ix_medicine_bill_queue_token_active",
        "medicine_bill",
        ["queue_token"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_medicine_bill_queue_token_active",
        table_name="medicine_bill",
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.drop_column("medicine_bill", "queue_token")

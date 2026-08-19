"""add payment method to invoice and medicine bill payments

Revision ID: 996d7b2f2ae6
Revises: 2e40ad3efe70
Create Date: 2026-08-19 18:08:52.113652

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "996d7b2f2ae6"
down_revision: str | None = "2e40ad3efe70"
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


def upgrade() -> None:
    # Mirrors the discount migrations' identical nullable-first,
    # backfill, then-NOT-NULL pattern (see e.g. dcbd18f38b39, 2e40ad3efe70)
    # — added nullable first (existing payment rows have no value yet),
    # backfilled to 'cash' (every payment recorded before this feature
    # existed genuinely was cash — the only method this system had any
    # concept of; this is a correct backfill of a known fact, not a
    # guess), then made NOT NULL.
    op.add_column("invoice_payment", sa.Column("payment_method", _PAYMENT_METHOD_ENUM, nullable=True))
    op.execute("UPDATE invoice_payment SET payment_method = 'cash'")
    op.alter_column("invoice_payment", "payment_method", nullable=False)

    op.add_column(
        "medicine_bill_payment", sa.Column("payment_method", _PAYMENT_METHOD_ENUM, nullable=True)
    )
    op.execute("UPDATE medicine_bill_payment SET payment_method = 'cash'")
    op.alter_column("medicine_bill_payment", "payment_method", nullable=False)


def downgrade() -> None:
    op.drop_column("medicine_bill_payment", "payment_method")
    op.drop_column("invoice_payment", "payment_method")

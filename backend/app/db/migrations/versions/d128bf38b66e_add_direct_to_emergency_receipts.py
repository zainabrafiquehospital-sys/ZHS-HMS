"""add direct-to-emergency receipts

Revision ID: d128bf38b66e
Revises: 0220c555921a
Create Date: 2026-09-05 16:20:00.000000

Additive, going-forward only — a new ledger table,
`inventory_emergency_direct_receipt`, alongside (never replacing)
`inventory_main_stock_receipt`/`inventory_transfer`: real-world
operation at this hospital turned out to never actually route stock
through a physical Main Stock warehouse — deliveries arrive addressed
directly to Emergency Stock, and the two-step Receive-then-Transfer
flow was a forced extra step with no corresponding physical event
behind it. This gives the Inventory Manager a second, equally
legitimate way to increase `emergency_stock_level` without touching
`main_stock_level` at all — see `InventoryEmergencyDirectReceipt`'s own
model docstring for the full rationale.

Also adds `inventory_restock_request.fulfilled_by_direct_receipt_id` —
a new nullable FK alongside the existing `fulfilled_by_transfer_id`, so
a request can be auto-resolved by a direct receipt exactly the way one
is already resolved by a transfer (see `InventoryRestockRequest.
fulfilled_by_direct_receipt_id`'s own docstring). Existing requests/
transfers and their own FK are completely unaffected.

No backfill, no NOT NULL, no data migration of any existing row — Main
Stock's own tables/columns/screens are untouched and stay fully
available.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d128bf38b66e"
down_revision: str | None = "0220c555921a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "inventory_emergency_direct_receipt",
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("received_on", sa.Date(), nullable=False),
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
        sa.CheckConstraint(
            "quantity > 0", name="ck_inventory_emergency_direct_receipt_quantity_positive"
        ),
        sa.ForeignKeyConstraint(["created_by"], ["user.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["item_id"],
            ["inventory_item.id"],
        ),
        sa.ForeignKeyConstraint(["updated_by"], ["user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_inventory_emergency_direct_receipt_item_id",
        "inventory_emergency_direct_receipt",
        ["item_id"],
        unique=False,
    )
    op.add_column(
        "inventory_restock_request",
        sa.Column("fulfilled_by_direct_receipt_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "inventory_restock_request_fulfilled_by_direct_receipt_id_fkey",
        "inventory_restock_request",
        "inventory_emergency_direct_receipt",
        ["fulfilled_by_direct_receipt_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "inventory_restock_request_fulfilled_by_direct_receipt_id_fkey",
        "inventory_restock_request",
        type_="foreignkey",
    )
    op.drop_column("inventory_restock_request", "fulfilled_by_direct_receipt_id")
    op.drop_index(
        "ix_inventory_emergency_direct_receipt_item_id",
        table_name="inventory_emergency_direct_receipt",
    )
    op.drop_table("inventory_emergency_direct_receipt")

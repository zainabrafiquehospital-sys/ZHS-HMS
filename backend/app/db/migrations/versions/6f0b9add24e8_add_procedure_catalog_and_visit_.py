"""add procedure catalog and visit procedure item tables

Revision ID: 6f0b9add24e8
Revises: 86d5b20afa17
Create Date: 2026-08-21 16:57:53.957977

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "6f0b9add24e8"
down_revision: str | None = "86d5b20afa17"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Purely additive — two new tables, nothing else. Confirmed,
    # explicit design decision: no existing `visit` row is touched or
    # backfilled in any way. Every visit registered before this ships
    # keeps its original single `procedure`/`amount` fields as its only
    # record of what was billed, forever — see app/modules/visits/
    # models.py's `VisitProcedureItem` docstring for the full rationale.
    op.create_table(
        "procedure",
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("price", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
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
        sa.CheckConstraint("price > 0", name="ck_procedure_price_positive"),
        sa.ForeignKeyConstraint(["created_by"], ["user.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_procedure_is_active", "procedure", ["is_active"], unique=False)
    op.create_index("ix_procedure_name", "procedure", ["name"], unique=False)
    op.create_table(
        "visit_procedure_item",
        sa.Column("visit_id", sa.Uuid(), nullable=False),
        # Nullable — None for a manual/free-typed entry, the per-item
        # discriminator between a catalog-linked row and a manual one
        # (see models.py's own docstring).
        sa.Column("procedure_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("amount", sa.Numeric(precision=10, scale=2), nullable=False),
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
        sa.CheckConstraint("amount > 0", name="ck_visit_procedure_item_amount_positive"),
        sa.ForeignKeyConstraint(["created_by"], ["user.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["procedure_id"], ["procedure.id"]),
        sa.ForeignKeyConstraint(["updated_by"], ["user.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["visit_id"], ["visit.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_visit_procedure_item_visit_id", "visit_procedure_item", ["visit_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_visit_procedure_item_visit_id", table_name="visit_procedure_item")
    op.drop_table("visit_procedure_item")
    op.drop_index("ix_procedure_name", table_name="procedure")
    op.drop_index("ix_procedure_is_active", table_name="procedure")
    op.drop_table("procedure")

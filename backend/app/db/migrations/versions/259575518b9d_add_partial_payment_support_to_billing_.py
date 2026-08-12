"""add partial payment support to billing and pharmacy

Revision ID: 259575518b9d
Revises: a08c97460b1f
Create Date: 2026-08-12 06:02:27.230333

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "259575518b9d"
down_revision: str | None = "a08c97460b1f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # `invoice_payment` — the audit trail for Invoice.amount_paid, which
    # stays exactly as it was (a maintained running total; see
    # app/modules/billing/models.py's InvoicePayment docstring).
    op.create_table(
        "invoice_payment",
        sa.Column("invoice_id", sa.Uuid(), nullable=False),
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
        sa.CheckConstraint("amount > 0", name="ck_invoice_payment_amount_positive"),
        sa.ForeignKeyConstraint(["created_by"], ["user.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["invoice_id"], ["invoice.id"]),
        sa.ForeignKeyConstraint(["updated_by"], ["user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_invoice_payment_invoice_id", "invoice_payment", ["invoice_id"], unique=False
    )

    # `medicine_bill_payment` — the identical role for MedicineBill.
    op.create_table(
        "medicine_bill_payment",
        sa.Column("medicine_bill_id", sa.Uuid(), nullable=False),
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
        sa.CheckConstraint("amount > 0", name="ck_medicine_bill_payment_amount_positive"),
        sa.ForeignKeyConstraint(["created_by"], ["user.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["medicine_bill_id"], ["medicine_bill.id"]),
        sa.ForeignKeyConstraint(["updated_by"], ["user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_medicine_bill_payment_medicine_bill_id",
        "medicine_bill_payment",
        ["medicine_bill_id"],
        unique=False,
    )

    # `medicine_bill` gains amount_paid/status/paid_at — added nullable
    # first (existing rows have no value yet), backfilled, then made
    # NOT NULL. Every medicine bill that already exists predates this
    # payment feature entirely: the old flow was "Finalize & Print"
    # collecting cash atomically at the counter in one step, so every
    # pre-existing bill is backfilled as already fully PAID (amount_paid
    # = total_amount, paid_at = created_at) rather than defaulted to
    # UNPAID/0 — the latter would misrepresent real, already-collected
    # sales as an outstanding backlog that never existed. Only bills
    # created *after* this migration go through the new explicit
    # create-then-record_payment flow and start genuinely UNPAID.
    op.add_column(
        "medicine_bill",
        sa.Column("amount_paid", sa.Numeric(precision=10, scale=2), nullable=True),
    )
    op.add_column(
        "medicine_bill",
        sa.Column(
            "status",
            sa.Enum(
                "unpaid",
                "partially_paid",
                "paid",
                name="medicine_bill_status",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            nullable=True,
        ),
    )
    op.add_column("medicine_bill", sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True))
    op.execute(
        "UPDATE medicine_bill SET amount_paid = total_amount, status = 'paid', "
        "paid_at = created_at"
    )
    op.alter_column("medicine_bill", "amount_paid", nullable=False)
    op.alter_column("medicine_bill", "status", nullable=False)
    op.create_check_constraint(
        "ck_medicine_bill_amount_paid_non_negative", "medicine_bill", "amount_paid >= 0"
    )
    op.create_check_constraint(
        "ck_medicine_bill_amount_paid_not_exceeding_total",
        "medicine_bill",
        "amount_paid <= total_amount",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_medicine_bill_amount_paid_not_exceeding_total", "medicine_bill", type_="check"
    )
    op.drop_constraint("ck_medicine_bill_amount_paid_non_negative", "medicine_bill", type_="check")
    op.drop_column("medicine_bill", "paid_at")
    op.drop_column("medicine_bill", "status")
    op.drop_column("medicine_bill", "amount_paid")
    op.drop_index("ix_medicine_bill_payment_medicine_bill_id", table_name="medicine_bill_payment")
    op.drop_table("medicine_bill_payment")
    op.drop_index("ix_invoice_payment_invoice_id", table_name="invoice_payment")
    op.drop_table("invoice_payment")

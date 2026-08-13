"""add manual patient details to medicine bill

Revision ID: b73e8bf4527b
Revises: 1e3fcb108620
Create Date: 2026-08-13 04:08:18.334042

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b73e8bf4527b"
down_revision: str | None = "1e3fcb108620"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # All three nullable, no backfill — this is brand-new optional
    # display-only data with no prior equivalent column to migrate
    # from; every pre-existing medicine_bill row simply has NULL here,
    # which trivially satisfies both CHECK constraints below.
    op.add_column(
        "medicine_bill", sa.Column("manual_patient_name", sa.String(length=150), nullable=True)
    )
    op.add_column("medicine_bill", sa.Column("manual_patient_age", sa.Integer(), nullable=True))
    op.add_column(
        "medicine_bill", sa.Column("manual_patient_phone", sa.String(length=20), nullable=True)
    )
    op.create_check_constraint(
        "ck_medicine_bill_not_both_visit_and_manual_patient",
        "medicine_bill",
        "NOT (visit_id IS NOT NULL AND manual_patient_name IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_medicine_bill_manual_patient_fields_all_or_none",
        "medicine_bill",
        "(manual_patient_name IS NULL AND manual_patient_age IS NULL "
        "AND manual_patient_phone IS NULL) OR (manual_patient_name IS NOT NULL "
        "AND manual_patient_age IS NOT NULL AND manual_patient_phone IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_medicine_bill_manual_patient_fields_all_or_none", "medicine_bill", type_="check"
    )
    op.drop_constraint(
        "ck_medicine_bill_not_both_visit_and_manual_patient", "medicine_bill", type_="check"
    )
    op.drop_column("medicine_bill", "manual_patient_phone")
    op.drop_column("medicine_bill", "manual_patient_age")
    op.drop_column("medicine_bill", "manual_patient_name")

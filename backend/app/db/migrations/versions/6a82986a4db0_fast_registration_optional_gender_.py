"""fast registration: optional gender, optional doctor, visit amount

Revision ID: 6a82986a4db0
Revises: 55dff255a73f
Create Date: 2026-08-07 03:00:51.147629

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "6a82986a4db0"
down_revision: str | None = "55dff255a73f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Three changes for Phase 6 fast-registration (§2-§5):

    - `patient.gender` becomes nullable — only full_name/age_years/
      phone_number are compulsory at registration; gender may be filled
      in later.
    - `visit.doctor_user_id` becomes nullable — doctor assignment is
      always automatic (an online doctor, if any) and must never block
      registration; NULL means "unclaimed", claimed by whichever doctor
      starts the consultation first (see consultation/service.py).
    - `visit.amount` is added, NOT NULL — the procedure's price, entered
      once by Reception at registration so Billing never asks for it a
      second time."""
    op.alter_column("patient", "gender", existing_type=sa.VARCHAR(length=10), nullable=True)
    op.add_column("visit", sa.Column("amount", sa.Numeric(precision=10, scale=2), nullable=False))
    op.create_check_constraint("ck_visit_amount_positive", "visit", "amount > 0")
    op.alter_column("visit", "doctor_user_id", existing_type=sa.UUID(), nullable=True)


def downgrade() -> None:
    op.alter_column("visit", "doctor_user_id", existing_type=sa.UUID(), nullable=False)
    op.drop_constraint("ck_visit_amount_positive", "visit", type_="check")
    op.drop_column("visit", "amount")
    op.alter_column("patient", "gender", existing_type=sa.VARCHAR(length=10), nullable=False)

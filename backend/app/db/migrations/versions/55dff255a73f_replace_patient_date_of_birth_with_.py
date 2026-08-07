"""replace patient date of birth with required age years

Revision ID: 55dff255a73f
Revises: c42408d9c420
Create Date: 2026-08-07 01:50:15.435366

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "55dff255a73f"
down_revision: str | None = "c42408d9c420"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Removes `date_of_birth` entirely and promotes the former
    `approximate_age_years` fallback to the sole, required `age_years`
    column (see app/modules/patients/models.py's module comment).

    Existing rows: the application-level "exactly one of date_of_birth
    or approximate_age_years" rule (the pre-this-migration
    `PatientIdentityFields` validator) guarantees every row already has
    at least one of the two, so the backfill below is exhaustive — a row
    with `approximate_age_years` already set keeps it verbatim; a row
    that only had `date_of_birth` gets a one-time age computed from it
    *at migration time* to avoid data loss. This is the only place in
    the system age is ever computed from a date — the application itself
    never derives age from a date, before or after this migration."""
    op.add_column("patient", sa.Column("age_years", sa.Integer(), nullable=True))
    op.execute(
        """
        UPDATE patient
        SET age_years = COALESCE(
            approximate_age_years,
            EXTRACT(YEAR FROM age(CURRENT_DATE, date_of_birth))::integer
        )
        WHERE age_years IS NULL
        """
    )
    op.alter_column("patient", "age_years", nullable=False)
    op.drop_column("patient", "approximate_age_years")
    op.drop_column("patient", "date_of_birth")


def downgrade() -> None:
    """Schema-reversible, not data-reversible: the original
    `date_of_birth` values were destroyed by `upgrade()` (age alone
    cannot reconstruct a birth date) and are not restored here. This
    recreates the pre-migration columns, nullable, and moves every
    row's `age_years` into `approximate_age_years` (the field it was
    promoted from) so no data is lost on the way back down."""
    op.add_column(
        "patient", sa.Column("date_of_birth", sa.Date(), autoincrement=False, nullable=True)
    )
    op.add_column(
        "patient",
        sa.Column("approximate_age_years", sa.Integer(), autoincrement=False, nullable=True),
    )
    op.execute("UPDATE patient SET approximate_age_years = age_years")
    op.drop_column("patient", "age_years")

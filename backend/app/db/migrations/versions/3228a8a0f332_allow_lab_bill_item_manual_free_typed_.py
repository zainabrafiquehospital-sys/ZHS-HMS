"""allow lab bill item manual free-typed lines

Revision ID: 3228a8a0f332
Revises: 725541d900c0
Create Date: 2026-08-28 14:29:23.964442

Purely additive/relaxing — no existing row is touched, no data is
rewritten. `lab_bill_item.lab_test_id` (a FK to the catalog) and
`lab_bill_item.category_snapshot` (the catalog test's own category,
snapshotted at billing time) both move from NOT NULL to nullable, so a
line can now represent a manual/free-typed test with no catalog entry
at all — the exact same shape `visit_procedure_item.procedure_id`
already has for a Visit's own manual procedure lines (see
`app/modules/lab/models.py`'s `LabBillItem` docstring for the full
rationale). Every row written before this migration already has both
columns populated, so relaxing the constraint changes nothing about
any of them; only new rows written after this migration can actually
have either column NULL.

`lab_bill_item.lab_test_name_snapshot`/`unit_price_snapshot` are
unaffected — both stay NOT NULL, since a manual line still needs a
name and a price, just not a catalog link.

Downgrade re-adds both NOT NULL constraints directly (standard Alembic
behavior, not the "best-effort" shape 725541d900c0's own downgrade
needed) — this is expected to fail loudly with a NotNullViolation if
any manual line (written after this migration shipped) still exists at
downgrade time, which is the correct behavior for reversing a
constraint relaxation: the schema genuinely cannot go back to requiring
a catalog link while nullable data exists.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3228a8a0f332"
down_revision: str | None = "725541d900c0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("lab_bill_item", "lab_test_id", existing_type=sa.Uuid(), nullable=True)
    op.alter_column(
        "lab_bill_item",
        "category_snapshot",
        existing_type=sa.VARCHAR(length=20),
        nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "lab_bill_item",
        "category_snapshot",
        existing_type=sa.VARCHAR(length=20),
        nullable=False,
    )
    op.alter_column("lab_bill_item", "lab_test_id", existing_type=sa.Uuid(), nullable=False)

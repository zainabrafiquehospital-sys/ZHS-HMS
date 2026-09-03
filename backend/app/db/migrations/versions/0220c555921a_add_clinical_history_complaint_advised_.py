"""add clinical history complaint advised to consultation

Revision ID: 0220c555921a
Revises: 56d8880d30a1
Create Date: 2026-09-03 20:48:53.850075

Additive, going-forward only — three new nullable free-text columns on
`consultation` (`history_of`, `complaint_of`, `advised`) backing the
H/O / C/O / Adv boxes of the doctor's prescription slip (the pre-printed
hospital-letterhead print layout). `diagnosis`/`prescription` already
map 1:1 to that slip's Dx/Rx sections and are untouched; `notes` stays
the general clinical-notes field it always was and is not printed on
the slip.

No backfill and no NOT NULL: every consultation that predates this
feature keeps NULL for all three, which the print template renders as
an honest empty box. Mirrors `1e3fcb108620`'s additive-column shape,
minus that migration's backfill/NOT-NULL step (these three are
genuinely optional per-consultation, exactly like `notes`/`diagnosis`/
`prescription` already are).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0220c555921a"
down_revision: str | None = "56d8880d30a1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("consultation", sa.Column("history_of", sa.Text(), nullable=True))
    op.add_column("consultation", sa.Column("complaint_of", sa.Text(), nullable=True))
    op.add_column("consultation", sa.Column("advised", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("consultation", "advised")
    op.drop_column("consultation", "complaint_of")
    op.drop_column("consultation", "history_of")

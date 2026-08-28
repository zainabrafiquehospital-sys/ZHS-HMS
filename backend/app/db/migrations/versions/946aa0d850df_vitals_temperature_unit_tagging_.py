"""vitals temperature unit tagging fahrenheit going forward

Revision ID: 946aa0d850df
Revises: 3228a8a0f332
Create Date: 2026-08-28 16:12:20.865074

Confirmed design: going-forward only. Every `vitals_record` written
from this point on stores a Fahrenheit reading (see
`VitalsService.record_vitals`'s own docstring — the unit is always
server-stamped, never client-suppliable). Every row already in the
table keeps its exact original number, completely untouched — this
migration never rewrites a single value, only renames the column
(`temperature_celsius` -> `temperature`, a plain `RENAME COLUMN`, not a
drop+recreate) and adds a new `temperature_unit` companion column,
backfilled to `'celsius'` for exactly the rows that already have a
reading (a row with no reading gets no unit either — nothing to tag).
`temperature`/`temperature_unit` are enforced to travel together via
`ck_vitals_record_temperature_unit_paired` — one is NULL if and only if
the other is.

Every future reader of this table must consult a row's own
`temperature_unit` before displaying or classifying its `temperature`
— never assume one globally; a history view spanning both eras will
show both units at once, each correctly labeled.

Downgrade is a real, reversible schema change (unlike 725541d900c0's
own necessarily best-effort downgrade) with one caveat worth noting:
any row written as FAHRENHEIT after this migration shipped has its raw
number silently reinterpreted as Celsius by the rename-back — the same
class of caveat every schema downgrade in this app already carries when
new data exists that the old schema was never designed to hold.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "946aa0d850df"
down_revision: str | None = "3228a8a0f332"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TEMPERATURE_UNIT = sa.Enum(
    "celsius",
    "fahrenheit",
    name="vitals_record_temperature_unit",
    native_enum=False,
    create_constraint=True,
    length=20,
)


def upgrade() -> None:
    op.alter_column("vitals_record", "temperature_celsius", new_column_name="temperature")
    op.add_column("vitals_record", sa.Column("temperature_unit", _TEMPERATURE_UNIT, nullable=True))

    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE vitals_record SET temperature_unit = 'celsius' WHERE temperature IS NOT NULL"
        )
    )

    op.create_check_constraint(
        "ck_vitals_record_temperature_unit_paired",
        "vitals_record",
        "(temperature IS NULL) = (temperature_unit IS NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_vitals_record_temperature_unit_paired", "vitals_record", type_="check")
    op.drop_column("vitals_record", "temperature_unit")
    op.alter_column("vitals_record", "temperature", new_column_name="temperature_celsius")

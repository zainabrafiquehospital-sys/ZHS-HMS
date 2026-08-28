"""seed lab test catalog from existing procedures

Revision ID: 725541d900c0
Revises: b1f9562f14bd
Create Date: 2026-08-27 21:52:00.000000

One-time data seed, confirmed design: this clinic's Procedure catalog
(app/modules/visits/models.py's `Procedure`) currently mixes genuine
Visit procedures together with 22 entries that are unmistakably lab/
imaging tests — confirmed by directly inspecting the real production
catalog before writing this migration (23 active procedures total,
only "CHECK-UP" is a genuine general visit procedure). Categorized here
as Pathology (blood/urine/serology) vs. Radiology/Imaging (scans) — a
judgment call with no source-of-truth column to derive it from (the
`procedure` table itself has no category), reviewable directly in this
migration.

This migration inserts these 22 name+price pairs directly into the new
`lab_test` table as literal values — it never reads from, writes to, or
otherwise touches the `procedure` table in any way. Every pre-existing
Visit built from one of these 22 procedures, and every Procedure row
itself, is completely unaffected: old visit slips render exactly as
they always have. `created_by`/`updated_by` are NULL on every seeded
row — this is system-seeded catalog data, not created by any real
user's action, the same convention this codebase already uses wherever
that distinction matters.

Deactivating the now-redundant Procedure rows (so Reception stops
being offered "CBC" etc. twice, once under Procedures and once under
the new Lab Test catalog) is a deliberate follow-up left to a manual
admin action once Reception has actually shifted to using the
Laboratory module for new bills — never automated here.

Idempotent: re-running this migration a second time would insert
duplicate rows (there is no natural unique key to conflict against —
two genuinely different tests could coincidentally share a name), so
this is guarded to only run once via a marker check against the count
of rows already in `lab_test`.

`downgrade()` is a best-effort undo, not a guaranteed one (Step 6
fix, found via a real round-trip test against actually-billed data):
a seeded test that has since been referenced by a `LabBillItem` is
left in place rather than the delete failing outright on a foreign-key
violation — see that function's own docstring.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from uuid6 import uuid7

# revision identifiers, used by Alembic.
revision: str = "725541d900c0"
down_revision: str | None = "b1f9562f14bd"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (name, category, price) — copied verbatim from production's real
# procedure catalog at investigation time (2026-08-27). See this
# migration's own module docstring for the categorization rationale.
_PATHOLOGY_TESTS: tuple[tuple[str, str], ...] = (
    ("ANTI HCV SCREENING", "500.00"),
    ("BETA HCG", "1500.00"),
    ("BLOOD GROUP", "300.00"),
    ("BLOOD SUGAR RANDOM", "300.00"),
    ("CBC", "600.00"),
    ("FSH", "1250.00"),
    ("HBA1C", "1150.00"),
    ("HBSAG SCREENING", "500.00"),
    ("HIV", "500.00"),
    ("LFT", "1200.00"),
    ("LH", "1250.00"),
    ("RFT", "1200.00"),
    ("THYROID FUNCTIONAL TEST (T3,T4,TSH)", "3000.00"),
    ("TSH", "1250.00"),
    ("URINE COMPLETE", "300.00"),
)
_RADIOLOGY_TESTS: tuple[tuple[str, str], ...] = (
    ("ABD SCAN", "1500.00"),
    ("ANOMALY SCAN", "2000.00"),
    ("COLOR DOPPLER", "1500.00"),
    ("DIRECT SCAN", "1000.00"),
    ("KUB", "1000.00"),
    ("OBS SCAN", "1000.00"),
    ("PELVIC SCAN", "1000.00"),
)


def upgrade() -> None:
    conn = op.get_bind()

    already_seeded = conn.execute(sa.text("SELECT COUNT(*) FROM lab_test")).scalar_one()
    if already_seeded > 0:
        return

    rows = [
        {"id": uuid7(), "name": name, "category": "pathology", "price": price}
        for name, price in _PATHOLOGY_TESTS
    ] + [
        {"id": uuid7(), "name": name, "category": "radiology", "price": price}
        for name, price in _RADIOLOGY_TESTS
    ]
    conn.execute(
        sa.text(
            "INSERT INTO lab_test (id, name, category, price, is_active) "
            "VALUES (:id, :name, :category, :price, TRUE)"
        ),
        rows,
    )


def downgrade() -> None:
    """Best-effort cleanup, never a hard failure: a seeded test that has
    since been billed (a `lab_bill_item.lab_test_id` FK pointing at it)
    is deliberately left in place rather than raising a
    ForeignKeyViolation — confirmed via a real round-trip test against
    real billing data (Step 6 verification) that the naive unconditional
    DELETE this migration originally shipped with crashes the instant
    any of these 22 tests has actually been used, which in real usage
    is virtually guaranteed to be true almost immediately after this
    module ships. Downgrading a one-time data seed can only ever be a
    best-effort undo of what's still safe to remove; it must never
    cascade-delete real billing history to force the removal through."""
    conn = op.get_bind()
    all_names = [name for name, _ in (*_PATHOLOGY_TESTS, *_RADIOLOGY_TESTS)]
    placeholders = ", ".join(f":name{i}" for i in range(len(all_names)))
    params = {f"name{i}": name for i, name in enumerate(all_names)}
    conn.execute(
        sa.text(
            f"DELETE FROM lab_test WHERE name IN ({placeholders}) AND created_by IS NULL "
            "AND id NOT IN (SELECT DISTINCT lab_test_id FROM lab_bill_item)"
        ),
        params,
    )

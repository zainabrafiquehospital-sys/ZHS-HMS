"""add user signup_role for multi-role self-service signup

Revision ID: 0c928477b446
Revises: d1fb51975400
Create Date: 2026-08-08 10:19:04.769416

Adds `user.signup_role` — records which role a self-service signup
requested (Receptionist or, as of this build, Vitals staff), so
`UserService.approve_signup` can grant the actual requested role
instead of the Receptionist-only assumption the previous build made.
Mirrors `d1fb51975400`'s own `user.shift` column exactly: a nullable,
`native_enum=False` enum column with a CHECK constraint, same reasoning
(most accounts — admin, doctors, User-Management-created staff — never
went through self-service signup and have no requested role to
record).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0c928477b446"
down_revision: str | None = "d1fb51975400"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "user",
        sa.Column(
            "signup_role",
            sa.Enum(
                "receptionist",
                "vitals",
                name="user_signup_role",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("user", "signup_role")

"""add doctor self service signup role

Revision ID: 8c263fc375ec
Revises: 954a7e0c382a
Create Date: 2026-08-24 16:14:48.021807

Two things, both prerequisites for a third self-service signup role
(Doctor, alongside Receptionist/Vitals — see signup_schemas.SignupRole/
models.SignupRole and UserService.approve_signup's own
`_SIGNUP_ROLE_TO_ROLE_NAME` mapping):

1. Renames the `role` row doctors already hold from `demo-doctor-demo`
   to `Doctor`. Investigated directly against the live database before
   writing this migration: doctors were never given a properly-named
   role the way Receptionist/Vitals were (the seed script's own
   comments confirm Vitals went through exactly this same
   `demo-vitals-demo` -> `Vitals` formalization already) — they were
   left on the original ad hoc demo-account role name. Same row, same
   id, same granted permissions, same existing account(s) — only the
   `name` column changes, so `_SIGNUP_ROLE_TO_ROLE_NAME` can map onto a
   real "Doctor" name instead of shipping the informal demo name into a
   permanent production mapping. A plain `UPDATE ... WHERE name = ...`
   rather than an ORM operation, consistent with how this file only
   touches raw rows, not application state.

2. Extends `user_signup_role`'s CHECK constraint (see
   0c928477b446_add_user_signup_role_for_multi_role_.py, the migration
   that introduced it) to allow `'doctor'` alongside the existing
   `'receptionist'`/`'vitals'` values — same drop-and-recreate-by-hand
   approach as 22faf2677ebe_extend_auth_audit_event_type_for_user_.py's
   own docstring explains (autogenerate does not diff the SQL body of
   an existing named CHECK constraint).
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8c263fc375ec"
down_revision: str | None = "954a7e0c382a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ORIGINAL_VALUES = ("receptionist", "vitals")
_NEW_VALUES = ("receptionist", "vitals", "doctor")


def _in_clause(values: tuple[str, ...]) -> str:
    return "signup_role IN (" + ", ".join(f"'{value}'" for value in values) + ")"


def upgrade() -> None:
    op.execute(
        "UPDATE role SET name = 'Doctor' " "WHERE name = 'demo-doctor-demo' AND deleted_at IS NULL"
    )
    op.drop_constraint("user_signup_role", "user", type_="check")
    op.create_check_constraint("user_signup_role", "user", _in_clause(_NEW_VALUES))


def downgrade() -> None:
    # Fails if any row already has signup_role = 'doctor' — expected and
    # correct, same reasoning as 22faf2677ebe's own downgrade: a
    # downgrade that narrows an allowed-value set cannot silently
    # discard data that no longer satisfies it.
    op.drop_constraint("user_signup_role", "user", type_="check")
    op.create_check_constraint("user_signup_role", "user", _in_clause(_ORIGINAL_VALUES))
    op.execute(
        "UPDATE role SET name = 'demo-doctor-demo' " "WHERE name = 'Doctor' AND deleted_at IS NULL"
    )

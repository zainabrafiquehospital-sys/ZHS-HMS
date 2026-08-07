"""Shared helper for translating a raw database `IntegrityError` into
the specific unique constraint that caused it.

Found during production QA hardening (post Phase 5): every "check
existence, then insert" duplicate-prevention pattern in this codebase
(`RoleService.create_role`/`update_role`, `PermissionService.
create_permission`, `UserService.create_user`/`update_user`,
`AuthService.register`) has an inherent TOCTOU race — two concurrent
requests can both pass the pre-check (neither sees the other's
not-yet-committed row) and both attempt the insert/update. Postgres's
own unique index correctly rejects the second one, but until this fix
nothing caught that rejection: it propagated as a raw, unhandled
`IntegrityError` all the way to the generic `Exception` handler,
producing an opaque 500 instead of the clean 409/422 the exact same
duplicate would get outside the race window. The application-level
pre-check remains valuable (it gives a fast, clean error in the
overwhelmingly common non-racing case and avoids a wasted round-trip to
the database for the racing case) — this closes the gap for when it
loses the race, keeping the database constraint as the actual source of
truth per this project's stated database rules ("always prefer database
constraints over application-only validation")."""

from sqlalchemy.exc import IntegrityError


def unique_violation_constraint_name(exc: IntegrityError) -> str | None:
    """The Postgres constraint name that caused `exc`, or `None` if it
    can't be determined (e.g. `exc` isn't actually a unique-violation).
    asyncpg surfaces the constraint name on the underlying
    `UniqueViolationError`, reachable via `exc.orig.__cause__` — one
    level below what SQLAlchemy's asyncpg dialect wraps it in."""
    cause = getattr(exc.orig, "__cause__", None)
    return getattr(cause, "constraint_name", None)

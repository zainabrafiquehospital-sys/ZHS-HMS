"""Local-development-only convenience seed script.

Creates one Admin-role user with a fixed, well-known email/password, for
developers who want a ready-to-use admin login on their own machine
without generating (and having to dig up) a random password the way
`seed_launch_bootstrap.py` does for its own admin account.

This is deliberately a *separate* script, not a flag on
`seed_launch_bootstrap.py` — that script is the production bootstrap
(see its own module docstring) and is intentionally left untouched here.
Rather than re-deriving "every permission the Admin role normally has"
(and risking the two definitions drifting apart the next time a
PERMISSION_* constant is added anywhere in the codebase), this script
imports `PERMISSION_CATALOG` and the `_get_or_create_*`/`_ensure_*`
helpers directly from `seed_launch_bootstrap` and reuses them verbatim —
same permission catalog, same "admin" role, same grant-everything loop,
same idempotent find-or-create pattern. `scripts/` has no `__init__.py`
(it isn't a package elsewhere in this codebase); this still imports
cleanly as an implicit namespace package as long as `backend/` is on
`PYTHONPATH`, i.e. when run the same way as `seed_launch_bootstrap.py`
itself (see this file's own "Usage" note below). Importing the module
only defines names — its `main()` only runs under
`if __name__ == "__main__":`, so nothing in `seed_launch_bootstrap.py`
executes as a side effect of this import.

**Local-only, by design and by a hard runtime check.** This account uses
a fixed, publicly-known password and skips the forced-password-change
flag — acceptable for a throwaway local database, never for a shared or
production one. Before touching the database at all, `_assert_safe_to_run`
refuses to proceed unless both of the following hold:
  1. `Settings.app_env` is not `"production"` (mirrors `Settings.
     is_production`, see app/core/config.py).
  2. The configured `DATABASE_URL`'s hostname is on a small allowlist of
     recognizably-local hosts (`localhost`, `127.0.0.1`, `::1`, and
     `postgres` — the service name `docker-compose.yml` gives the local
     Postgres container). This is an *allowlist*, not a blocklist of
     "known production hosts" (e.g. `*.railway.app`) — a blocklist only
     catches connection strings that happen to match a guessed pattern;
     an allowlist refuses everything by default and only proceeds for
     hosts this script can positively confirm are local, which is what
     actually keeps this safe against a Railway/production
     `DATABASE_URL` (or any other unrecognized remote host) accidentally
     sitting in `.env` when this is run.

Idempotent: if a user with this email already exists, prints a message
and exits cleanly — never errors, never creates a duplicate, never
touches that existing user's password or status.

Usage (from backend/, same as seed_launch_bootstrap.py):
    .venv/Scripts/python.exe scripts/seed_local_admin.py
"""

import asyncio
import sys
from urllib.parse import urlparse

from app.core.config import Settings, get_settings
from app.db import model_registry  # noqa: F401  (registers all models on Base.metadata)
from app.db.session import async_session_factory
from app.modules.auth.models import User, UserStatus
from app.modules.auth.password_service import PasswordService
from app.modules.auth.repository import (
    PermissionRepository,
    RolePermissionRepository,
    RoleRepository,
    UserRepository,
    UserRoleRepository,
)
from app.shared.audit.repository import AuditLogRepository
from scripts.seed_launch_bootstrap import (
    PERMISSION_CATALOG,
    _ensure_role_has_permission,
    _ensure_user_has_role,
    _get_or_create_permission,
    _get_or_create_role,
)

LOCAL_ADMIN_EMAIL = "localtest123@gmail.com"
LOCAL_ADMIN_PASSWORD = "ZainabHospital2026!"
LOCAL_ADMIN_FULL_NAME = "Local Test Admin"

# See this module's docstring — an allowlist of hostnames this script
# will accept as "definitely local", not a blocklist of production ones.
_LOCAL_DATABASE_HOSTS = {"localhost", "127.0.0.1", "::1", "postgres"}


def _assert_safe_to_run(settings: Settings) -> None:
    if settings.is_production:
        print(
            "Refusing to run: APP_ENV is 'production'. This script creates a "
            "fixed-password local dev account and must never run against a "
            "production deployment.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    host = (urlparse(settings.database_url).hostname or "").lower()
    if host not in _LOCAL_DATABASE_HOSTS:
        print(
            f"Refusing to run: DATABASE_URL host '{host}' is not a recognized "
            f"local database host ({', '.join(sorted(_LOCAL_DATABASE_HOSTS))}). "
            "This looks like it could be a remote/production database "
            "(e.g. Railway) — this script must only ever run against a local "
            "database. If this really is your local database, add its host "
            "to _LOCAL_DATABASE_HOSTS in this script.",
            file=sys.stderr,
        )
        raise SystemExit(1)


async def main() -> None:
    settings = get_settings()
    _assert_safe_to_run(settings)

    async with async_session_factory() as session:
        user_repo = UserRepository(session)

        existing = await user_repo.get_by_email(LOCAL_ADMIN_EMAIL)
        if existing is not None:
            print(f"{LOCAL_ADMIN_EMAIL} already exists — nothing to do.")
            return

        permission_repo = PermissionRepository(session)
        role_repo = RoleRepository(session)
        role_permission_repo = RolePermissionRepository(session)
        user_role_repo = UserRoleRepository(session)
        audit_repo = AuditLogRepository(session)
        password_service = PasswordService()

        print("== 1. Permission catalog ==")
        permissions_by_code = {}
        for code, display_name, description in PERMISSION_CATALOG:
            permission, _created = await _get_or_create_permission(
                permission_repo, code, display_name, description
            )
            permissions_by_code[code] = permission
        await session.commit()
        print(f"  {len(PERMISSION_CATALOG)} permissions in catalog.")

        print("== 2. admin role ==")
        admin_role, admin_role_created = await _get_or_create_role(
            role_repo, "admin", "Full system access — created by the launch bootstrap seed script."
        )
        await session.commit()
        granted = 0
        for permission in permissions_by_code.values():
            if await _ensure_role_has_permission(role_permission_repo, admin_role, permission.id):
                granted += 1
        await session.commit()
        print(
            f"  role {'created' if admin_role_created else 'already existed'}; "
            f"granted {granted} new permission(s)."
        )

        print("== 3. Local admin user ==")
        user = User(
            email=LOCAL_ADMIN_EMAIL,
            full_name=LOCAL_ADMIN_FULL_NAME,
            password_hash=await password_service.hash(LOCAL_ADMIN_PASSWORD),
            status=UserStatus.ACTIVE,
            is_email_verified=True,
            must_change_password=False,
        )
        await user_repo.add(user)
        await session.commit()
        await _ensure_user_has_role(user_role_repo, user, admin_role)
        await session.commit()

        await audit_repo.record(
            module="auth",
            action="auth.local_admin_seeded",
            entity_type="user",
            entity_id=user.id,
            actor_user_id=None,
            metadata={"email": user.email},
        )
        await session.commit()

        print("\n" + "=" * 70)
        print("LOCAL ADMIN ACCOUNT CREATED (local dev only — do not use in production)")
        print("=" * 70)
        print(f"  email:    {LOCAL_ADMIN_EMAIL}")
        print(f"  password: {LOCAL_ADMIN_PASSWORD}")
        print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())

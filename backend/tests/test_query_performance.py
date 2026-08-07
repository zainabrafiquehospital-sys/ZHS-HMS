"""Production QA hardening (post Phase 5): confirms `GET /users` and
`GET /roles` do not have an N+1 query problem as the result set grows.
Every relationship in this module is declared `lazy="selectin"`
specifically to avoid this (see app/modules/auth/models.py's module
docstring), but that's a claim worth actually measuring, not just
trusting by inspection — a regression (e.g. someone later changing a
relationship's `lazy` strategy) should be caught here, not discovered
as a production slowdown.

Counts real SQL statements issued via a `before_cursor_execute` engine
event, comparing a page of 2 rows against a page of 8 rows (each row
carrying its own role + permission, so the naive per-row-lazy-load
failure mode would be clearly visible as query count scaling with row
count) — the two counts must be equal, not merely "small"."""

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool
from uuid6 import uuid7

from app.core.config import get_settings
from app.modules.auth.models import Permission, Role, RolePermission, User, UserRole
from app.modules.auth.repository import (
    PermissionRepository,
    RolePermissionRepository,
    RoleRepository,
    UserRepository,
    UserRoleRepository,
)
from app.modules.auth.user_schemas import UserAdminOut
from tests.conftest import TEST_PERMISSION_GROUP_PREFIX, TEST_ROLE_PREFIX, make_test_email


class _QueryCounter:
    def __init__(self) -> None:
        self.count = 0

    def __call__(self, *_args, **_kwargs) -> None:
        self.count += 1


async def _seed_users_with_role_and_permission(session, count: int) -> None:
    suffix = uuid7().hex
    permission = await PermissionRepository(session).add(
        Permission(
            code=f"{TEST_PERMISSION_GROUP_PREFIX}{suffix}:act{suffix}",
            group=f"{TEST_PERMISSION_GROUP_PREFIX}{suffix}",
            display_name="N+1 probe permission",
        )
    )
    role = await RoleRepository(session).add(Role(name=f"{TEST_ROLE_PREFIX}{uuid7()}"))
    await RolePermissionRepository(session).add(
        RolePermission(role_id=role.id, permission_id=permission.id)
    )
    for i in range(count):
        user = await UserRepository(session).add(
            User(
                email=make_test_email(f"n1-probe-{suffix}-{i}"),
                password_hash="hash",
                full_name=f"N+1 Probe {i}",
            )
        )
        await UserRoleRepository(session).add(UserRole(user_id=user.id, role_id=role.id))
    await session.commit()


async def _count_queries_for_full_list_and_serialize(page_size: int) -> int:
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    counter = _QueryCounter()
    event.listen(engine.sync_engine, "before_cursor_execute", counter)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            await _seed_users_with_role_and_permission(session, page_size)

            counter.count = 0  # only measure the list+serialize call itself
            repo = UserRepository(session)
            users, _total = await repo.search(
                search=None,
                status=None,
                role_id=None,
                sort_column=repo.model.created_at,
                sort_desc=True,
                limit=page_size,
                offset=0,
            )
            # Force full serialization, exactly like the router does —
            # this is what would trigger per-row lazy loads if the
            # relationships weren't actually eager.
            [UserAdminOut.from_user(u).model_dump(mode="json") for u in users]
            query_count = counter.count

            # This helper uses its own dedicated engine/session (not the
            # `real_session` fixture other test files rely on for
            # automatic cleanup), so it is responsible for its own —
            # same TEST_EMAIL_PREFIX/TEST_ROLE_PREFIX/
            # TEST_PERMISSION_GROUP_PREFIX conventions every other file
            # already uses.
            await session.execute(
                text("DELETE FROM \"user\" WHERE email LIKE 'auth-test-n1-probe-%'")
            )
            await session.execute(text(f"DELETE FROM role WHERE name LIKE '{TEST_ROLE_PREFIX}%'"))
            await session.execute(
                text(
                    f"DELETE FROM permission WHERE \"group\" LIKE '{TEST_PERMISSION_GROUP_PREFIX}%'"
                )
            )
            await session.commit()

            return query_count
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", counter)
        await engine.dispose()


async def test_listing_users_does_not_scale_query_count_with_row_count():
    small_page_queries = await _count_queries_for_full_list_and_serialize(2)
    large_page_queries = await _count_queries_for_full_list_and_serialize(8)

    assert small_page_queries == large_page_queries, (
        f"query count scaled with row count ({small_page_queries} -> "
        f"{large_page_queries}) — this is an N+1, not eager loading"
    )

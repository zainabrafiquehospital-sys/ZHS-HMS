from datetime import UTC, datetime

from uuid6 import uuid7

from app.modules.auth.models import Permission, Role, RolePermission, User, UserRole
from app.modules.auth.repository import (
    ROLE_SORTABLE_COLUMNS,
    PermissionRepository,
    RolePermissionRepository,
    RoleRepository,
    UserRepository,
    UserRoleRepository,
)
from tests.conftest import make_test_email


def _role_name() -> str:
    return f"role-{uuid7()}"[:50]


async def _make_role(
    db_session, *, name: str | None = None, description: str | None = None, is_active: bool = True
) -> Role:
    role = Role(name=name or _role_name(), description=description, is_active=is_active)
    return await RoleRepository(db_session).add(role)


async def _make_permission(db_session) -> Permission:
    code = f"grp{uuid7().hex}:act{uuid7().hex}"
    permission = Permission(
        code=code, group=code.split(":", 1)[0], display_name="Repo Test Permission"
    )
    return await PermissionRepository(db_session).add(permission)


async def test_get_by_name_finds_active_role(db_session):
    role = await _make_role(db_session)

    found = await RoleRepository(db_session).get_by_name(role.name)

    assert found is not None
    assert found.id == role.id


async def test_get_by_name_returns_none_when_missing(db_session):
    assert await RoleRepository(db_session).get_by_name("role-does-not-exist") is None


async def test_search_filters_by_text_across_name_and_description(db_session):
    repo = RoleRepository(db_session)
    target = await _make_role(db_session, description="zebra-search-unique-zz")
    await _make_role(db_session, description="unrelated description")

    roles, total = await repo.search(
        search="zebra-search-unique-zz",
        is_active=None,
        sort_column=ROLE_SORTABLE_COLUMNS["created_at"],
        sort_desc=True,
        limit=20,
        offset=0,
    )

    assert total == 1
    assert roles[0].id == target.id


async def test_search_filters_by_is_active(db_session):
    repo = RoleRepository(db_session)
    await _make_role(db_session, description="filter-active-zz", is_active=True)
    inactive = await _make_role(db_session, description="filter-active-zz", is_active=False)

    roles, total = await repo.search(
        search="filter-active-zz",
        is_active=False,
        sort_column=ROLE_SORTABLE_COLUMNS["created_at"],
        sort_desc=True,
        limit=20,
        offset=0,
    )

    assert total == 1
    assert roles[0].id == inactive.id


async def test_search_excludes_soft_deleted_roles(db_session):
    repo = RoleRepository(db_session)
    role = await _make_role(db_session, description="soft-deleted-search-zz")
    await repo.soft_delete(role, deleted_at=datetime.now(UTC))

    roles, total = await repo.search(
        search="soft-deleted-search-zz",
        is_active=None,
        sort_column=ROLE_SORTABLE_COLUMNS["created_at"],
        sort_desc=True,
        limit=20,
        offset=0,
    )

    assert total == 0
    assert roles == []


async def test_search_sorts_and_paginates(db_session):
    repo = RoleRepository(db_session)
    unique = str(uuid7())[:8]
    await _make_role(db_session, name=f"role-a-{unique}", description=f"sort-{unique}")
    await _make_role(db_session, name=f"role-b-{unique}", description=f"sort-{unique}")
    await _make_role(db_session, name=f"role-c-{unique}", description=f"sort-{unique}")

    first_page, total = await repo.search(
        search=f"sort-{unique}",
        is_active=None,
        sort_column=ROLE_SORTABLE_COLUMNS["name"],
        sort_desc=False,
        limit=2,
        offset=0,
    )
    second_page, _ = await repo.search(
        search=f"sort-{unique}",
        is_active=None,
        sort_column=ROLE_SORTABLE_COLUMNS["name"],
        sort_desc=False,
        limit=2,
        offset=2,
    )

    assert total == 3
    assert [r.name for r in first_page] == [f"role-a-{unique}", f"role-b-{unique}"]
    assert [r.name for r in second_page] == [f"role-c-{unique}"]


async def test_count_active_for_role(db_session):
    role = await _make_role(db_session)
    user = await UserRepository(db_session).add(
        User(
            email=make_test_email("count-active-role"),
            password_hash="hash",
            full_name="Count Active Role User",
        )
    )
    user_role_repo = UserRoleRepository(db_session)
    assert await user_role_repo.count_active_for_role(role.id) == 0

    user_role = await user_role_repo.add(UserRole(user_id=user.id, role_id=role.id))
    assert await user_role_repo.count_active_for_role(role.id) == 1

    await user_role_repo.soft_delete(user_role, deleted_at=datetime.now(UTC))
    assert await user_role_repo.count_active_for_role(role.id) == 0


async def test_role_permission_get_active_finds_active_grant(db_session):
    role = await _make_role(db_session)
    permission = await _make_permission(db_session)
    role_permission_repo = RolePermissionRepository(db_session)

    assert await role_permission_repo.get_active(role.id, permission.id) is None

    grant = await role_permission_repo.add(
        RolePermission(role_id=role.id, permission_id=permission.id)
    )
    found = await role_permission_repo.get_active(role.id, permission.id)
    assert found is not None
    assert found.id == grant.id


async def test_role_permission_get_active_excludes_soft_deleted(db_session):
    role = await _make_role(db_session)
    permission = await _make_permission(db_session)
    role_permission_repo = RolePermissionRepository(db_session)
    grant = await role_permission_repo.add(
        RolePermission(role_id=role.id, permission_id=permission.id)
    )

    await role_permission_repo.soft_delete(grant, deleted_at=datetime.now(UTC))

    assert await role_permission_repo.get_active(role.id, permission.id) is None

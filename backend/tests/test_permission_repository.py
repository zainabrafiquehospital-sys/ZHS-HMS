from datetime import UTC, datetime

from uuid6 import uuid7

from app.modules.auth.models import Permission, Role, RolePermission
from app.modules.auth.repository import (
    PERMISSION_SORTABLE_COLUMNS,
    PermissionRepository,
    RolePermissionRepository,
    RoleRepository,
)


def _unique_code() -> str:
    suffix = uuid7().hex
    return f"grp{suffix}:act{suffix}"


async def _make_permission(
    db_session,
    *,
    code: str | None = None,
    display_name: str = "Test Permission",
    description: str | None = None,
) -> Permission:
    code = code or _unique_code()
    permission = Permission(
        code=code,
        group=code.split(":", 1)[0],
        display_name=display_name,
        description=description,
    )
    return await PermissionRepository(db_session).add(permission)


async def test_get_by_code_finds_active_permission(db_session):
    permission = await _make_permission(db_session)

    found = await PermissionRepository(db_session).get_by_code(permission.code)

    assert found is not None
    assert found.id == permission.id


async def test_get_by_code_returns_none_when_missing(db_session):
    assert await PermissionRepository(db_session).get_by_code("does:notexist") is None


async def test_search_filters_by_text_across_code_display_name_description(db_session):
    repo = PermissionRepository(db_session)
    target = await _make_permission(
        db_session, display_name="Zebra Search Target", description="unrelated"
    )
    await _make_permission(db_session, display_name="Something Else")

    permissions, total = await repo.search(
        search="Zebra Search Target",
        group=None,
        sort_column=PERMISSION_SORTABLE_COLUMNS["created_at"],
        sort_desc=True,
        limit=20,
        offset=0,
    )

    assert total == 1
    assert permissions[0].id == target.id


async def test_search_filters_by_group(db_session):
    repo = PermissionRepository(db_session)
    unique = uuid7().hex
    group_a = f"grpa{unique}"
    group_b = f"grpb{unique}"
    target = await _make_permission(db_session, code=f"{group_a}:action")
    await _make_permission(db_session, code=f"{group_b}:action")

    permissions, total = await repo.search(
        search=unique,
        group=group_a,
        sort_column=PERMISSION_SORTABLE_COLUMNS["created_at"],
        sort_desc=True,
        limit=20,
        offset=0,
    )

    assert total == 1
    assert permissions[0].id == target.id


async def test_search_excludes_soft_deleted_permissions(db_session):
    repo = PermissionRepository(db_session)
    permission = await _make_permission(db_session, display_name="Soft Deleted Search Target Zz")
    await repo.soft_delete(permission, deleted_at=datetime.now(UTC))

    permissions, total = await repo.search(
        search="Soft Deleted Search Target Zz",
        group=None,
        sort_column=PERMISSION_SORTABLE_COLUMNS["created_at"],
        sort_desc=True,
        limit=20,
        offset=0,
    )

    assert total == 0
    assert permissions == []


async def test_search_sorts_and_paginates(db_session):
    repo = PermissionRepository(db_session)
    unique = uuid7().hex
    await _make_permission(db_session, code=f"sortgrp{unique}:aaa")
    await _make_permission(db_session, code=f"sortgrp{unique}:bbb")
    await _make_permission(db_session, code=f"sortgrp{unique}:ccc")

    first_page, total = await repo.search(
        search=unique,
        group=None,
        sort_column=PERMISSION_SORTABLE_COLUMNS["code"],
        sort_desc=False,
        limit=2,
        offset=0,
    )
    second_page, _ = await repo.search(
        search=unique,
        group=None,
        sort_column=PERMISSION_SORTABLE_COLUMNS["code"],
        sort_desc=False,
        limit=2,
        offset=2,
    )

    assert total == 3
    assert [p.code for p in first_page] == [f"sortgrp{unique}:aaa", f"sortgrp{unique}:bbb"]
    assert [p.code for p in second_page] == [f"sortgrp{unique}:ccc"]


async def test_count_active_for_permission(db_session):
    permission = await _make_permission(db_session)
    role = await RoleRepository(db_session).add(Role(name=f"role-{uuid7()}"[:50]))
    role_permission_repo = RolePermissionRepository(db_session)
    assert await role_permission_repo.count_active_for_permission(permission.id) == 0

    role_permission = await role_permission_repo.add(
        RolePermission(role_id=role.id, permission_id=permission.id)
    )
    assert await role_permission_repo.count_active_for_permission(permission.id) == 1

    await role_permission_repo.soft_delete(role_permission, deleted_at=datetime.now(UTC))
    assert await role_permission_repo.count_active_for_permission(permission.id) == 0

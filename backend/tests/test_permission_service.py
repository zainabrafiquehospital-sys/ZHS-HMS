from datetime import UTC, datetime

import pytest
from uuid6 import uuid7

from app.core.exceptions import ValidationError
from app.modules.auth.exceptions import (
    InvalidPermissionCodeError,
    PermissionCodeAlreadyExistsError,
    PermissionInUseError,
    PermissionNotFoundError,
)
from app.modules.auth.models import Role, RolePermission
from app.modules.auth.repository import RolePermissionRepository, RoleRepository
from tests.conftest import TEST_PERMISSION_GROUP_PREFIX, TEST_ROLE_PREFIX, make_test_email

_PASSWORD = "Str0ng!Passw0rd#2026"


def _unique_code() -> str:
    suffix = uuid7().hex
    return f"{TEST_PERMISSION_GROUP_PREFIX}{suffix}:act{suffix}"


async def _register(auth_service, suffix: str):
    return await auth_service.register(
        email=make_test_email(suffix), password=_PASSWORD, full_name="Permission Test Actor"
    )


# ---------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------


async def test_create_permission_derives_group_from_code(permission_service, auth_service):
    actor = await _register(auth_service, "create-perm-actor")
    code = _unique_code()

    permission = await permission_service.create_permission(
        actor=actor, code=code, display_name="Test Action", description="A test permission"
    )

    assert permission.code == code
    assert permission.group == code.split(":", 1)[0]
    assert permission.display_name == "Test Action"
    assert permission.created_by == actor.id


async def test_create_permission_rejects_duplicate_code(permission_service, auth_service):
    actor = await _register(auth_service, "create-perm-dup-actor")
    code = _unique_code()
    await permission_service.create_permission(
        actor=actor, code=code, display_name="First", description=None
    )

    with pytest.raises(PermissionCodeAlreadyExistsError):
        await permission_service.create_permission(
            actor=actor, code=code, display_name="Second", description=None
        )


@pytest.mark.parametrize(
    "bad_code",
    [
        "nocolon",
        "TooManyUpper:action",
        ":emptygroup",
        "emptyaction:",
        "group:action:extra",
        "has space:action",
    ],
)
async def test_create_permission_rejects_malformed_code(permission_service, auth_service, bad_code):
    actor = await _register(auth_service, f"create-perm-bad-{uuid7().hex[:8]}")

    with pytest.raises(InvalidPermissionCodeError):
        await permission_service.create_permission(
            actor=actor, code=bad_code, display_name="Bad", description=None
        )


# ---------------------------------------------------------------------
# Get / List
# ---------------------------------------------------------------------


async def test_get_permission_raises_not_found(permission_service):
    with pytest.raises(PermissionNotFoundError):
        await permission_service.get_permission(uuid7())


async def test_list_permissions_filters_by_search(permission_service, auth_service):
    actor = await _register(auth_service, "list-perm-actor")
    code = _unique_code()
    await permission_service.create_permission(
        actor=actor, code=code, display_name="Listable Permission", description=None
    )

    permissions, total = await permission_service.list_permissions(
        search=code,
        group=None,
        sort_by="created_at",
        sort_desc=True,
        page=1,
        page_size=20,
    )

    assert total == 1
    assert permissions[0].code == code


# ---------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------


async def test_update_permission_changes_display_name(permission_service, auth_service):
    actor = await _register(auth_service, "update-perm-actor")
    permission = await permission_service.create_permission(
        actor=actor, code=_unique_code(), display_name="Old Name", description=None
    )

    updated = await permission_service.update_permission(
        actor=actor, permission_id=permission.id, updates={"display_name": "New Name"}
    )

    assert updated.display_name == "New Name"
    assert updated.updated_by == actor.id


async def test_update_permission_no_updates_is_a_noop(permission_service, auth_service):
    actor = await _register(auth_service, "update-perm-noop-actor")
    permission = await permission_service.create_permission(
        actor=actor, code=_unique_code(), display_name="Name", description=None
    )

    result = await permission_service.update_permission(
        actor=actor, permission_id=permission.id, updates={}
    )

    assert result.id == permission.id


async def test_update_permission_rejects_clearing_display_name(permission_service, auth_service):
    actor = await _register(auth_service, "update-perm-clear-actor")
    permission = await permission_service.create_permission(
        actor=actor, code=_unique_code(), display_name="Name", description=None
    )

    with pytest.raises(ValidationError):
        await permission_service.update_permission(
            actor=actor, permission_id=permission.id, updates={"display_name": None}
        )


async def test_update_permission_allows_clearing_description(permission_service, auth_service):
    actor = await _register(auth_service, "update-perm-clear-desc-actor")
    permission = await permission_service.create_permission(
        actor=actor, code=_unique_code(), display_name="Name", description="has one"
    )

    updated = await permission_service.update_permission(
        actor=actor, permission_id=permission.id, updates={"description": None}
    )

    assert updated.description is None


async def test_update_permission_ignores_code_key(permission_service, auth_service):
    """`code` is immutable — even a caller that bypasses the schema and
    passes a `code` key directly to the service must not have it
    applied. Only `display_name`/`description` are ever inspected."""
    actor = await _register(auth_service, "update-perm-code-actor")
    permission = await permission_service.create_permission(
        actor=actor, code=_unique_code(), display_name="Name", description=None
    )
    original_code = permission.code

    updated = await permission_service.update_permission(
        actor=actor,
        permission_id=permission.id,
        updates={"code": "should:notapply", "display_name": "Renamed"},
    )

    assert updated.code == original_code
    assert updated.display_name == "Renamed"


# ---------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------


async def test_delete_permission_success(permission_service, auth_service):
    actor = await _register(auth_service, "delete-perm-actor")
    permission = await permission_service.create_permission(
        actor=actor, code=_unique_code(), display_name="Name", description=None
    )

    await permission_service.delete_permission(actor=actor, permission_id=permission.id)

    with pytest.raises(PermissionNotFoundError):
        await permission_service.get_permission(permission.id)


async def test_delete_permission_blocked_when_in_use(
    permission_service, auth_service, real_session
):
    actor = await _register(auth_service, "delete-perm-in-use-actor")
    permission = await permission_service.create_permission(
        actor=actor, code=_unique_code(), display_name="Name", description=None
    )
    role = await RoleRepository(real_session).add(
        Role(name=f"{TEST_ROLE_PREFIX}{uuid7()}", is_active=True)
    )
    role_permission_repo = RolePermissionRepository(real_session)
    role_permission = await role_permission_repo.add(
        RolePermission(role_id=role.id, permission_id=permission.id)
    )
    await real_session.commit()

    with pytest.raises(PermissionInUseError):
        await permission_service.delete_permission(actor=actor, permission_id=permission.id)

    # Once the grant is removed, deletion succeeds.
    await role_permission_repo.soft_delete(role_permission, deleted_at=datetime.now(UTC))
    await real_session.commit()
    await permission_service.delete_permission(actor=actor, permission_id=permission.id)


# ---------------------------------------------------------------------
# Role <-> Permission Assignment (Phase 5 Step 5) — read-only inverse
# ---------------------------------------------------------------------


async def test_get_roles_for_permission_returns_granted_roles(
    permission_service, role_service, auth_service
):
    actor = await _register(auth_service, "roles-for-perm-actor")
    permission = await permission_service.create_permission(
        actor=actor, code=_unique_code(), display_name="Name", description=None
    )
    role = await role_service.create_role(
        actor=actor, name=f"{TEST_ROLE_PREFIX}{uuid7()}", description=None, parent_role_id=None
    )
    await role_service.assign_permissions(
        actor=actor, role_id=role.id, permission_ids=[permission.id]
    )

    roles = await permission_service.get_roles_for_permission(permission.id)

    assert [r.id for r in roles] == [role.id]


async def test_get_roles_for_permission_excludes_revoked_grant(
    permission_service, role_service, auth_service
):
    actor = await _register(auth_service, "roles-for-perm-revoked-actor")
    permission = await permission_service.create_permission(
        actor=actor, code=_unique_code(), display_name="Name", description=None
    )
    role = await role_service.create_role(
        actor=actor, name=f"{TEST_ROLE_PREFIX}{uuid7()}", description=None, parent_role_id=None
    )
    await role_service.assign_permissions(
        actor=actor, role_id=role.id, permission_ids=[permission.id]
    )
    await role_service.remove_permissions(
        actor=actor, role_id=role.id, permission_ids=[permission.id]
    )

    roles = await permission_service.get_roles_for_permission(permission.id)

    assert roles == []


async def test_get_roles_for_permission_raises_not_found(permission_service):
    with pytest.raises(PermissionNotFoundError):
        await permission_service.get_roles_for_permission(uuid7())

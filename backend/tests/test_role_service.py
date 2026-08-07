import pytest
from sqlalchemy import select
from uuid6 import uuid7

from app.core.exceptions import ValidationError
from app.modules.auth.exceptions import (
    InvalidParentRoleError,
    PermissionNotFoundError,
    RoleInUseError,
    RoleNameAlreadyExistsError,
    RoleNotFoundError,
    SystemRoleProtectedError,
)
from app.modules.auth.models import AuditEventType, AuditLog, Permission, Role
from app.modules.auth.repository import PermissionRepository, RoleRepository
from tests.conftest import TEST_PERMISSION_GROUP_PREFIX, TEST_ROLE_PREFIX, make_test_email

_PASSWORD = "Str0ng!Passw0rd#2026"


async def _register(auth_service, suffix: str):
    return await auth_service.register(
        email=make_test_email(suffix), password=_PASSWORD, full_name="Role Test Actor"
    )


async def _make_role_direct(
    real_session,
    *,
    is_system_role: bool = False,
    is_active: bool = True,
    parent_role_id=None,
) -> Role:
    role = await RoleRepository(real_session).add(
        Role(
            name=f"{TEST_ROLE_PREFIX}{uuid7()}",
            is_system_role=is_system_role,
            is_active=is_active,
            parent_role_id=parent_role_id,
        )
    )
    await real_session.commit()
    return role


async def _make_permission_direct(real_session) -> Permission:
    suffix = uuid7().hex
    code = f"{TEST_PERMISSION_GROUP_PREFIX}{suffix}:act{suffix}"
    permission = await PermissionRepository(real_session).add(
        Permission(code=code, group=code.split(":", 1)[0], display_name="Role Test Permission")
    )
    await real_session.commit()
    return permission


async def _count_audit_events(real_session, event_type: AuditEventType, **metadata_filter) -> int:
    """Test-only introspection: `AuditRepository` deliberately has no
    query methods beyond `record()` (persistence-only, per this
    module's own convention), so this queries `AuditLog` directly
    rather than adding a production method whose only caller would be
    this test file."""
    stmt = select(AuditLog).where(AuditLog.event_type == event_type)
    result = await real_session.execute(stmt)
    rows = result.scalars().all()
    return sum(
        1
        for row in rows
        if row.metadata_ is not None
        and all(row.metadata_.get(key) == value for key, value in metadata_filter.items())
    )


# ---------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------


async def test_create_role_success(role_service, auth_service):
    actor = await _register(auth_service, "create-role-actor")
    name = f"{TEST_ROLE_PREFIX}{uuid7()}"

    role = await role_service.create_role(
        actor=actor, name=name, description="A test role", parent_role_id=None
    )

    assert role.name == name
    assert role.is_system_role is False
    assert role.is_active is True
    assert role.created_by == actor.id


async def test_create_role_rejects_duplicate_name(role_service, auth_service):
    actor = await _register(auth_service, "create-role-dup-actor")
    name = f"{TEST_ROLE_PREFIX}{uuid7()}"
    await role_service.create_role(actor=actor, name=name, description=None, parent_role_id=None)

    with pytest.raises(RoleNameAlreadyExistsError):
        await role_service.create_role(
            actor=actor, name=name, description=None, parent_role_id=None
        )


async def test_create_role_rejects_unknown_parent(role_service, auth_service):
    actor = await _register(auth_service, "create-role-unknown-parent")

    with pytest.raises(InvalidParentRoleError):
        await role_service.create_role(
            actor=actor,
            name=f"{TEST_ROLE_PREFIX}{uuid7()}",
            description=None,
            parent_role_id=uuid7(),
        )


async def test_create_role_rejects_inactive_parent(role_service, auth_service, real_session):
    actor = await _register(auth_service, "create-role-inactive-parent")
    parent = await _make_role_direct(real_session, is_active=False)

    with pytest.raises(InvalidParentRoleError):
        await role_service.create_role(
            actor=actor,
            name=f"{TEST_ROLE_PREFIX}{uuid7()}",
            description=None,
            parent_role_id=parent.id,
        )


async def test_create_role_accepts_active_parent(role_service, auth_service, real_session):
    actor = await _register(auth_service, "create-role-valid-parent")
    parent = await _make_role_direct(real_session)

    role = await role_service.create_role(
        actor=actor,
        name=f"{TEST_ROLE_PREFIX}{uuid7()}",
        description=None,
        parent_role_id=parent.id,
    )

    assert role.parent_role_id == parent.id


# ---------------------------------------------------------------------
# Get / List
# ---------------------------------------------------------------------


async def test_get_role_raises_not_found(role_service):
    with pytest.raises(RoleNotFoundError):
        await role_service.get_role(uuid7())


async def test_list_roles_filters_by_search(role_service, auth_service):
    actor = await _register(auth_service, "list-roles-actor")
    name = f"{TEST_ROLE_PREFIX}{uuid7()}"
    await role_service.create_role(actor=actor, name=name, description=None, parent_role_id=None)

    roles, total = await role_service.list_roles(
        search=name,
        is_active=None,
        sort_by="created_at",
        sort_desc=True,
        page=1,
        page_size=20,
    )

    assert total == 1
    assert roles[0].name == name


# ---------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------


async def test_update_role_renames_successfully(role_service, auth_service):
    actor = await _register(auth_service, "update-role-actor")
    role = await role_service.create_role(
        actor=actor, name=f"{TEST_ROLE_PREFIX}{uuid7()}", description=None, parent_role_id=None
    )
    new_name = f"{TEST_ROLE_PREFIX}{uuid7()}"

    updated = await role_service.update_role(
        actor=actor, role_id=role.id, updates={"name": new_name}
    )

    assert updated.name == new_name
    assert updated.updated_by == actor.id


async def test_update_role_no_updates_is_a_noop(role_service, auth_service):
    actor = await _register(auth_service, "update-role-noop-actor")
    role = await role_service.create_role(
        actor=actor, name=f"{TEST_ROLE_PREFIX}{uuid7()}", description=None, parent_role_id=None
    )

    result = await role_service.update_role(actor=actor, role_id=role.id, updates={})

    assert result.id == role.id


async def test_update_role_rejects_duplicate_name(role_service, auth_service):
    actor = await _register(auth_service, "update-role-dup-actor")
    existing_name = f"{TEST_ROLE_PREFIX}{uuid7()}"
    await role_service.create_role(
        actor=actor, name=existing_name, description=None, parent_role_id=None
    )
    role = await role_service.create_role(
        actor=actor, name=f"{TEST_ROLE_PREFIX}{uuid7()}", description=None, parent_role_id=None
    )

    with pytest.raises(RoleNameAlreadyExistsError):
        await role_service.update_role(
            actor=actor, role_id=role.id, updates={"name": existing_name}
        )


async def test_update_role_rejects_clearing_name(role_service, auth_service):
    actor = await _register(auth_service, "update-role-clear-name-actor")
    role = await role_service.create_role(
        actor=actor, name=f"{TEST_ROLE_PREFIX}{uuid7()}", description=None, parent_role_id=None
    )

    with pytest.raises(ValidationError):
        await role_service.update_role(actor=actor, role_id=role.id, updates={"name": None})


async def test_update_role_rejects_clearing_is_active(role_service, auth_service):
    actor = await _register(auth_service, "update-role-clear-active-actor")
    role = await role_service.create_role(
        actor=actor, name=f"{TEST_ROLE_PREFIX}{uuid7()}", description=None, parent_role_id=None
    )

    with pytest.raises(ValidationError):
        await role_service.update_role(actor=actor, role_id=role.id, updates={"is_active": None})


async def test_update_role_allows_clearing_description_and_parent(
    role_service, auth_service, real_session
):
    actor = await _register(auth_service, "update-role-clear-desc-actor")
    parent = await _make_role_direct(real_session)
    role = await role_service.create_role(
        actor=actor,
        name=f"{TEST_ROLE_PREFIX}{uuid7()}",
        description="has a description",
        parent_role_id=parent.id,
    )

    updated = await role_service.update_role(
        actor=actor,
        role_id=role.id,
        updates={"description": None, "parent_role_id": None},
    )

    assert updated.description is None
    assert updated.parent_role_id is None


async def test_update_role_toggles_is_active(role_service, auth_service):
    actor = await _register(auth_service, "update-role-toggle-actor")
    role = await role_service.create_role(
        actor=actor, name=f"{TEST_ROLE_PREFIX}{uuid7()}", description=None, parent_role_id=None
    )

    deactivated = await role_service.update_role(
        actor=actor, role_id=role.id, updates={"is_active": False}
    )

    assert deactivated.is_active is False


async def test_update_role_rejects_self_as_parent(role_service, auth_service):
    actor = await _register(auth_service, "update-role-self-parent-actor")
    role = await role_service.create_role(
        actor=actor, name=f"{TEST_ROLE_PREFIX}{uuid7()}", description=None, parent_role_id=None
    )

    with pytest.raises(InvalidParentRoleError):
        await role_service.update_role(
            actor=actor, role_id=role.id, updates={"parent_role_id": role.id}
        )


async def test_update_role_rejects_deeper_cycle(role_service, auth_service):
    actor = await _register(auth_service, "update-role-cycle-actor")
    grandparent = await role_service.create_role(
        actor=actor, name=f"{TEST_ROLE_PREFIX}{uuid7()}", description=None, parent_role_id=None
    )
    parent = await role_service.create_role(
        actor=actor,
        name=f"{TEST_ROLE_PREFIX}{uuid7()}",
        description=None,
        parent_role_id=grandparent.id,
    )
    # grandparent -> parent already exists; making grandparent's parent
    # be `parent` would close the loop grandparent -> parent -> grandparent.
    with pytest.raises(InvalidParentRoleError):
        await role_service.update_role(
            actor=actor, role_id=grandparent.id, updates={"parent_role_id": parent.id}
        )


# ---------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------


async def test_delete_role_success(role_service, auth_service):
    actor = await _register(auth_service, "delete-role-actor")
    role = await role_service.create_role(
        actor=actor, name=f"{TEST_ROLE_PREFIX}{uuid7()}", description=None, parent_role_id=None
    )

    await role_service.delete_role(actor=actor, role_id=role.id)

    with pytest.raises(RoleNotFoundError):
        await role_service.get_role(role.id)


async def test_delete_role_blocked_for_system_role(role_service, auth_service, real_session):
    actor = await _register(auth_service, "delete-role-system-actor")
    role = await _make_role_direct(real_session, is_system_role=True)

    with pytest.raises(SystemRoleProtectedError):
        await role_service.delete_role(actor=actor, role_id=role.id)


async def test_delete_role_blocked_when_in_use(role_service, auth_service, user_service):
    actor = await _register(auth_service, "delete-role-in-use-actor")
    target = await _register(auth_service, "delete-role-in-use-target")
    role = await role_service.create_role(
        actor=actor, name=f"{TEST_ROLE_PREFIX}{uuid7()}", description=None, parent_role_id=None
    )
    await user_service.assign_roles(actor=actor, user_id=target.id, role_ids=[role.id])

    with pytest.raises(RoleInUseError):
        await role_service.delete_role(actor=actor, role_id=role.id)

    # Once the assignment is removed, deletion succeeds.
    await user_service.remove_roles(actor=actor, user_id=target.id, role_ids=[role.id])
    await role_service.delete_role(actor=actor, role_id=role.id)


# ---------------------------------------------------------------------
# Role <-> Permission Assignment (Phase 5 Step 5)
# ---------------------------------------------------------------------


async def test_assign_permissions_grants_and_is_idempotent(
    role_service, auth_service, real_session
):
    actor = await _register(auth_service, "assign-perm-actor")
    role = await role_service.create_role(
        actor=actor, name=f"{TEST_ROLE_PREFIX}{uuid7()}", description=None, parent_role_id=None
    )
    permission = await _make_permission_direct(real_session)

    updated = await role_service.assign_permissions(
        actor=actor, role_id=role.id, permission_ids=[permission.id]
    )
    active_ids = {rp.permission_id for rp in updated.role_permissions if rp.deleted_at is None}
    assert active_ids == {permission.id}
    assert (
        await _count_audit_events(
            real_session,
            AuditEventType.PERMISSION_GRANTED,
            role_id=str(role.id),
            permission_id=str(permission.id),
        )
        == 1
    )

    # Re-assigning the same permission must not raise, must not
    # duplicate the grant, and must NOT emit a second audit event.
    again = await role_service.assign_permissions(
        actor=actor, role_id=role.id, permission_ids=[permission.id]
    )
    active_ids_again = {rp.permission_id for rp in again.role_permissions if rp.deleted_at is None}
    assert active_ids_again == {permission.id}
    assert (
        await _count_audit_events(
            real_session,
            AuditEventType.PERMISSION_GRANTED,
            role_id=str(role.id),
            permission_id=str(permission.id),
        )
        == 1
    )


async def test_assign_permissions_audit_metadata_is_human_readable(
    role_service, auth_service, real_session
):
    actor = await _register(auth_service, "assign-perm-metadata-actor")
    role = await role_service.create_role(
        actor=actor, name=f"{TEST_ROLE_PREFIX}{uuid7()}", description=None, parent_role_id=None
    )
    permission = await _make_permission_direct(real_session)

    await role_service.assign_permissions(
        actor=actor, role_id=role.id, permission_ids=[permission.id]
    )

    stmt = select(AuditLog).where(AuditLog.event_type == AuditEventType.PERMISSION_GRANTED)
    result = await real_session.execute(stmt)
    matching = [
        row
        for row in result.scalars().all()
        if row.metadata_ is not None and row.metadata_.get("permission_id") == str(permission.id)
    ]
    assert len(matching) == 1
    metadata = matching[0].metadata_
    assert metadata["role_name"] == role.name
    assert metadata["permission_code"] == permission.code


async def test_assign_permissions_rejects_unknown_permission(role_service, auth_service):
    actor = await _register(auth_service, "assign-perm-unknown-actor")
    role = await role_service.create_role(
        actor=actor, name=f"{TEST_ROLE_PREFIX}{uuid7()}", description=None, parent_role_id=None
    )

    with pytest.raises(PermissionNotFoundError):
        await role_service.assign_permissions(
            actor=actor, role_id=role.id, permission_ids=[uuid7()]
        )


async def test_remove_permissions_revokes_and_is_idempotent(
    role_service, auth_service, real_session
):
    actor = await _register(auth_service, "remove-perm-actor")
    role = await role_service.create_role(
        actor=actor, name=f"{TEST_ROLE_PREFIX}{uuid7()}", description=None, parent_role_id=None
    )
    permission = await _make_permission_direct(real_session)
    await role_service.assign_permissions(
        actor=actor, role_id=role.id, permission_ids=[permission.id]
    )

    updated = await role_service.remove_permissions(
        actor=actor, role_id=role.id, permission_ids=[permission.id]
    )
    active_ids = {rp.permission_id for rp in updated.role_permissions if rp.deleted_at is None}
    assert active_ids == set()
    assert (
        await _count_audit_events(
            real_session,
            AuditEventType.PERMISSION_REVOKED,
            role_id=str(role.id),
            permission_id=str(permission.id),
        )
        == 1
    )

    # Removing again (nothing active left to remove) must not raise and
    # must NOT emit a second audit event.
    await role_service.remove_permissions(
        actor=actor, role_id=role.id, permission_ids=[permission.id]
    )
    assert (
        await _count_audit_events(
            real_session,
            AuditEventType.PERMISSION_REVOKED,
            role_id=str(role.id),
            permission_id=str(permission.id),
        )
        == 1
    )


async def test_remove_permissions_on_ungranted_permission_is_a_noop(
    role_service, auth_service, real_session
):
    actor = await _register(auth_service, "remove-perm-noop-actor")
    role = await role_service.create_role(
        actor=actor, name=f"{TEST_ROLE_PREFIX}{uuid7()}", description=None, parent_role_id=None
    )
    permission = await _make_permission_direct(real_session)

    result = await role_service.remove_permissions(
        actor=actor, role_id=role.id, permission_ids=[permission.id]
    )

    assert result.id == role.id
    assert (
        await _count_audit_events(
            real_session,
            AuditEventType.PERMISSION_REVOKED,
            role_id=str(role.id),
            permission_id=str(permission.id),
        )
        == 0
    )


async def test_replace_permissions_sets_exact_set(role_service, auth_service, real_session):
    actor = await _register(auth_service, "replace-perm-actor")
    role = await role_service.create_role(
        actor=actor, name=f"{TEST_ROLE_PREFIX}{uuid7()}", description=None, parent_role_id=None
    )
    permission_a = await _make_permission_direct(real_session)
    permission_b = await _make_permission_direct(real_session)
    await role_service.assign_permissions(
        actor=actor, role_id=role.id, permission_ids=[permission_a.id]
    )

    updated = await role_service.replace_permissions(
        actor=actor, role_id=role.id, permission_ids=[permission_b.id]
    )

    active_ids = {rp.permission_id for rp in updated.role_permissions if rp.deleted_at is None}
    assert active_ids == {permission_b.id}


async def test_replace_permissions_is_diff_based_and_leaves_unchanged_grant_untouched(
    role_service, auth_service, real_session
):
    """The explicit requirement: replace must never delete-everything-
    and-recreate-everything. A permission present both before and after
    must keep its original grant row (same id, same original grant) and
    must not generate a spurious GRANT+REVOKE audit pair."""
    actor = await _register(auth_service, "replace-perm-diff-actor")
    role = await role_service.create_role(
        actor=actor, name=f"{TEST_ROLE_PREFIX}{uuid7()}", description=None, parent_role_id=None
    )
    permission_keep = await _make_permission_direct(real_session)
    permission_drop = await _make_permission_direct(real_session)
    permission_new = await _make_permission_direct(real_session)
    before = await role_service.assign_permissions(
        actor=actor,
        role_id=role.id,
        permission_ids=[permission_keep.id, permission_drop.id],
    )
    kept_grant_id_before = next(
        rp.id
        for rp in before.role_permissions
        if rp.permission_id == permission_keep.id and rp.deleted_at is None
    )

    updated = await role_service.replace_permissions(
        actor=actor,
        role_id=role.id,
        permission_ids=[permission_keep.id, permission_new.id],
    )

    active = {rp.permission_id: rp.id for rp in updated.role_permissions if rp.deleted_at is None}
    assert set(active.keys()) == {permission_keep.id, permission_new.id}
    # Same grant row, not soft-deleted-then-recreated.
    assert active[permission_keep.id] == kept_grant_id_before
    # Only the actual diff was audited: one revoke (drop), one grant (new) —
    # never a spurious pair for the unchanged permission.
    assert (
        await _count_audit_events(
            real_session,
            AuditEventType.PERMISSION_REVOKED,
            role_id=str(role.id),
            permission_id=str(permission_keep.id),
        )
        == 0
    )
    assert (
        await _count_audit_events(
            real_session,
            AuditEventType.PERMISSION_GRANTED,
            role_id=str(role.id),
            permission_id=str(permission_keep.id),
        )
        == 1  # only from the original assign_permissions call above
    )
    assert (
        await _count_audit_events(
            real_session,
            AuditEventType.PERMISSION_REVOKED,
            role_id=str(role.id),
            permission_id=str(permission_drop.id),
        )
        == 1
    )
    assert (
        await _count_audit_events(
            real_session,
            AuditEventType.PERMISSION_GRANTED,
            role_id=str(role.id),
            permission_id=str(permission_new.id),
        )
        == 1
    )


async def test_replace_permissions_empty_list_clears_all(role_service, auth_service, real_session):
    actor = await _register(auth_service, "replace-perm-empty-actor")
    role = await role_service.create_role(
        actor=actor, name=f"{TEST_ROLE_PREFIX}{uuid7()}", description=None, parent_role_id=None
    )
    permission = await _make_permission_direct(real_session)
    await role_service.assign_permissions(
        actor=actor, role_id=role.id, permission_ids=[permission.id]
    )

    updated = await role_service.replace_permissions(
        actor=actor, role_id=role.id, permission_ids=[]
    )

    assert all(rp.deleted_at is not None for rp in updated.role_permissions)


async def test_replace_permissions_rejects_unknown_permission(
    role_service, auth_service, real_session
):
    actor = await _register(auth_service, "replace-perm-unknown-actor")
    role = await role_service.create_role(
        actor=actor, name=f"{TEST_ROLE_PREFIX}{uuid7()}", description=None, parent_role_id=None
    )

    with pytest.raises(PermissionNotFoundError):
        await role_service.replace_permissions(
            actor=actor, role_id=role.id, permission_ids=[uuid7()]
        )

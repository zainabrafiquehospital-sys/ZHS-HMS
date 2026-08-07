from uuid import UUID

import pytest
from sqlalchemy.exc import IntegrityError

from app.modules.auth.models import Role, User


async def test_role_gets_a_uuid7_primary_key(db_session):
    role = Role(name="DOCTOR")
    db_session.add(role)
    await db_session.flush()

    assert isinstance(role.id, UUID)
    assert role.id.version == 7


async def test_role_timestamps_are_timezone_aware(db_session):
    role = Role(name="NURSE")
    db_session.add(role)
    await db_session.flush()

    assert role.created_at.tzinfo is not None
    assert role.updated_at.tzinfo is not None


async def test_role_defaults(db_session):
    role = Role(name="RECEPTIONIST")
    db_session.add(role)
    await db_session.flush()

    assert role.description is None
    assert role.parent_role_id is None
    assert role.is_system_role is False
    assert role.is_active is True
    assert role.created_by is None
    assert role.updated_by is None
    assert role.deleted_at is None


async def test_duplicate_active_name_is_rejected(db_session):
    db_session.add(Role(name="ADMIN"))
    await db_session.flush()

    db_session.add(Role(name="ADMIN"))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_soft_deleted_name_is_free_for_reuse(db_session):
    original = Role(name="BILLING_CLERK")
    db_session.add(original)
    await db_session.flush()
    original.deleted_at = original.created_at
    await db_session.flush()

    db_session.add(Role(name="BILLING_CLERK"))
    await db_session.flush()  # must not raise: the partial index only covers active rows


async def test_role_hierarchy_via_parent_role_id(db_session):
    parent = Role(name="DOCTOR")
    db_session.add(parent)
    await db_session.flush()

    child = Role(name="SENIOR_DOCTOR", parent_role_id=parent.id)
    db_session.add(child)
    await db_session.flush()

    assert child.parent_role_id == parent.id


async def test_deleting_parent_role_nulls_out_parent_role_id(db_session):
    parent = Role(name="LAB_TECHNICIAN")
    db_session.add(parent)
    await db_session.flush()

    child = Role(name="SENIOR_LAB_TECHNICIAN", parent_role_id=parent.id)
    db_session.add(child)
    await db_session.flush()

    await db_session.delete(parent)
    await db_session.flush()
    # attribute_names limits the refresh to this one column: a full refresh
    # would also eagerly reload role_permissions/user_roles (lazy=
    # "selectin"), which fail here since those tables aren't migrated yet
    # in this design-only phase.
    await db_session.refresh(child, attribute_names=["parent_role_id"])

    assert child.parent_role_id is None


async def test_deleting_creator_user_nulls_out_created_by(db_session):
    creator = User(email="role-creator@example.com", password_hash="hash", full_name="Creator")
    db_session.add(creator)
    await db_session.flush()

    role = Role(name="PHARMACIST", created_by=creator.id)
    db_session.add(role)
    await db_session.flush()

    await db_session.delete(creator)
    await db_session.flush()
    # attribute_names limits the refresh to this one column: a full refresh
    # would also eagerly reload role_permissions/user_roles (lazy=
    # "selectin"), which fail here since those tables aren't migrated yet
    # in this design-only phase.
    await db_session.refresh(role, attribute_names=["created_by"])

    assert role.created_by is None

from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from uuid6 import uuid7

from app.modules.auth.models import User, UserStatus


async def test_user_gets_a_uuid7_primary_key(db_session):
    user = User(email="uuid7@example.com", password_hash="hash", full_name="Test User")
    db_session.add(user)
    await db_session.flush()

    assert isinstance(user.id, UUID)
    assert user.id.version == 7


async def test_user_timestamps_are_timezone_aware(db_session):
    user = User(email="tz@example.com", password_hash="hash", full_name="Test User")
    db_session.add(user)
    await db_session.flush()

    assert user.created_at.tzinfo is not None
    assert user.updated_at.tzinfo is not None


async def test_user_defaults(db_session):
    user = User(email="defaults@example.com", password_hash="hash", full_name="Test User")
    db_session.add(user)
    await db_session.flush()

    assert user.status is UserStatus.PENDING_VERIFICATION
    assert user.is_email_verified is False
    assert user.must_change_password is True
    assert user.failed_login_attempts == 0
    assert user.mfa_enabled is False
    assert user.created_by is None
    assert user.updated_by is None


async def test_duplicate_active_email_is_rejected(db_session):
    db_session.add(User(email="dup@example.com", password_hash="hash", full_name="First"))
    await db_session.flush()

    db_session.add(User(email="dup@example.com", password_hash="hash", full_name="Second"))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_soft_deleted_email_is_free_for_reuse(db_session):
    original = User(email="reuse@example.com", password_hash="hash", full_name="Original")
    db_session.add(original)
    await db_session.flush()
    original.deleted_at = original.created_at
    await db_session.flush()

    db_session.add(User(email="reuse@example.com", password_hash="hash", full_name="New"))
    await db_session.flush()  # must not raise: the partial index only covers active rows


async def test_invalid_status_value_is_rejected_at_the_database_level(db_session):
    """Regression test for a bug found in manual migration audit: SQLAlchemy's
    `Enum(..., native_enum=False)` does NOT emit a CHECK constraint unless
    `create_constraint=True` is also passed — without it, `status` was a
    plain VARCHAR accepting any string. Bypasses the ORM (which would
    reject an invalid Python-side UserStatus value before ever reaching the
    database) with a raw INSERT to prove the constraint is enforced by
    Postgres itself, not just by application-level type checking."""
    with pytest.raises(IntegrityError):
        await db_session.execute(
            text(
                """
                INSERT INTO "user"
                    (id, email, password_hash, full_name, status,
                     is_email_verified, must_change_password, failed_login_attempts, mfa_enabled)
                VALUES
                    (:id, :email, 'hash', 'Test', :status, false, true, 0, false)
                """
            ),
            {"id": uuid7(), "email": "invalid-status@example.com", "status": "not-a-real-status"},
        )
        await db_session.flush()


async def test_deleting_the_creator_nulls_out_created_by(db_session):
    """Regression test for a bug found in manual migration audit: the
    created_by/updated_by FKs had no ON DELETE behavior (defaulting to
    Postgres's NO ACTION), contradicting the architecture's own audit
    recommendation that these nullable audit-actor columns use SET NULL so
    a hard-deleted user doesn't block or cascade-delete records they
    created."""
    creator = User(email="creator@example.com", password_hash="hash", full_name="Creator")
    db_session.add(creator)
    await db_session.flush()

    child = User(
        email="child@example.com", password_hash="hash", full_name="Child", created_by=creator.id
    )
    db_session.add(child)
    await db_session.flush()

    await db_session.delete(creator)
    await db_session.flush()
    # attribute_names limits the refresh to this one column: a full refresh
    # would also eagerly reload user_roles/refresh_tokens/etc. (lazy=
    # "selectin"), which fail here since those tables aren't migrated yet
    # in this design-only phase.
    await db_session.refresh(child, attribute_names=["created_by"])

    assert child.created_by is None

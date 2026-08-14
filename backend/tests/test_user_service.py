import pytest
from sqlalchemy import select
from uuid6 import uuid7

from app.core.exceptions import ValidationError
from app.modules.auth.constants import PERMISSION_USERS_MANAGE_STATUS
from app.modules.auth.exceptions import (
    AccountLockedError,
    EmailAlreadyRegisteredError,
    InvalidUserStatusTransitionError,
    LastAdminCannotBeDeactivatedError,
    PhoneNumberAlreadyRegisteredError,
    RoleInactiveError,
    RoleNotFoundError,
    SelfActionNotAllowedError,
    TokenInvalidError,
    UserNotFoundError,
)
from app.modules.auth.models import AuditEventType, AuditLog, Role, UserStatus
from app.modules.auth.repository import RoleRepository
from tests.conftest import TEST_ROLE_PREFIX, make_test_email

_PASSWORD = "Str0ng!Passw0rd#2026"


async def _register(auth_service, suffix: str):
    return await auth_service.register(
        email=make_test_email(suffix), password=_PASSWORD, full_name="Target User"
    )


async def _make_role(real_session, suffix: str, *, is_active: bool = True) -> Role:
    # Role.name is VARCHAR(50) — TEST_ROLE_PREFIX + a bare uuid7 already
    # uses 46 of those, so `suffix` is deliberately not included in the
    # generated name (it exists only to make call sites self-documenting).
    del suffix
    return await RoleRepository(real_session).add(
        Role(name=f"{TEST_ROLE_PREFIX}{uuid7()}", is_active=is_active)
    )


# ---------------------------------------------------------------------
# Create / Get / List / Update / Delete
# ---------------------------------------------------------------------


async def test_create_user_returns_working_temporary_password(user_service, auth_service):
    user, temporary_password = await user_service.create_user(
        actor=await _register(auth_service, "create-actor"),
        email=make_test_email("create-target"),
        full_name="New User",
        phone_number=None,
    )

    assert user.must_change_password is True
    assert user.status == UserStatus.ACTIVE
    login = await auth_service.login(
        email=user.email,
        password=temporary_password,
        remember_me=False,
        ip_address=None,
        user_agent=None,
    )
    assert login.access_token


async def test_create_user_rejects_duplicate_email(user_service, auth_service):
    actor = await _register(auth_service, "create-dup-actor")
    email = make_test_email("create-dup-target")
    await user_service.create_user(actor=actor, email=email, full_name="A", phone_number=None)

    with pytest.raises(EmailAlreadyRegisteredError):
        await user_service.create_user(actor=actor, email=email, full_name="B", phone_number=None)


async def test_create_user_rejects_duplicate_phone_number(user_service, auth_service):
    actor = await _register(auth_service, "create-dup-phone-actor")
    await user_service.create_user(
        actor=actor,
        email=make_test_email("create-dup-phone-a"),
        full_name="A",
        phone_number="+1 555 0200",
    )

    with pytest.raises(PhoneNumberAlreadyRegisteredError):
        await user_service.create_user(
            actor=actor,
            email=make_test_email("create-dup-phone-b"),
            full_name="B",
            phone_number="+1 555 0200",
        )


async def test_get_user_raises_not_found_for_unknown_id(user_service):
    with pytest.raises(UserNotFoundError):
        await user_service.get_user(uuid7())


async def test_list_users_filters_by_search(user_service, auth_service):
    await _register(auth_service, "list-target-unique-zz")

    users, total = await user_service.list_users(
        search="list-target-unique-zz",
        status=None,
        role_id=None,
        sort_by="created_at",
        sort_desc=True,
        page=1,
        page_size=20,
    )

    assert total == 1
    assert make_test_email("list-target-unique-zz") == users[0].email


async def test_update_user_changes_fields_and_records_updated_by(user_service, auth_service):
    actor = await _register(auth_service, "update-actor")
    target = await _register(auth_service, "update-target")

    updated = await user_service.update_user(
        actor=actor,
        user_id=target.id,
        updates={"full_name": "Renamed", "phone_number": "+1 555 0300"},
    )

    assert updated.full_name == "Renamed"
    assert updated.phone_number == "+1 555 0300"
    assert updated.updated_by == actor.id


async def test_update_user_no_updates_is_a_noop(user_service, auth_service):
    actor = await _register(auth_service, "update-noop-actor")
    target = await _register(auth_service, "update-noop-target")

    result = await user_service.update_user(actor=actor, user_id=target.id, updates={})

    assert result.id == target.id


async def test_update_user_rejects_duplicate_email(user_service, auth_service):
    actor = await _register(auth_service, "update-dup-actor")
    existing = await _register(auth_service, "update-dup-existing")
    target = await _register(auth_service, "update-dup-target")

    with pytest.raises(EmailAlreadyRegisteredError):
        await user_service.update_user(
            actor=actor, user_id=target.id, updates={"email": existing.email}
        )


async def test_update_user_rejects_clearing_full_name(user_service, auth_service):
    actor = await _register(auth_service, "update-clear-actor")
    target = await _register(auth_service, "update-clear-target")

    with pytest.raises(ValidationError):
        await user_service.update_user(actor=actor, user_id=target.id, updates={"full_name": None})


async def test_update_user_allows_clearing_phone_number(user_service, auth_service):
    actor = await _register(auth_service, "update-clear-phone-actor")
    target = await _register(auth_service, "update-clear-phone-target")
    await user_service.update_user(
        actor=actor, user_id=target.id, updates={"phone_number": "+1 555 0400"}
    )

    updated = await user_service.update_user(
        actor=actor, user_id=target.id, updates={"phone_number": None}
    )

    assert updated.phone_number is None


async def test_update_own_profile_updates_full_name(user_service, auth_service):
    user = await _register(auth_service, "own-profile")

    updated = await user_service.update_own_profile(
        user=user, updates={"full_name": "Self Renamed"}
    )

    assert updated.full_name == "Self Renamed"


async def test_update_own_profile_rejects_email_key(user_service, auth_service):
    user = await _register(auth_service, "own-profile-email")

    with pytest.raises(ValidationError):
        await user_service.update_own_profile(
            user=user, updates={"email": "someone-else@example.com"}
        )


async def test_delete_user_soft_deletes_and_revokes_sessions(user_service, auth_service):
    actor = await _register(auth_service, "delete-actor")
    target = await _register(auth_service, "delete-target")
    login = await auth_service.login(
        email=target.email, password=_PASSWORD, remember_me=False, ip_address=None, user_agent=None
    )

    await user_service.delete_user(actor=actor, user_id=target.id)

    with pytest.raises(UserNotFoundError):
        await user_service.get_user(target.id)
    with pytest.raises(TokenInvalidError):
        await auth_service.refresh(
            raw_refresh_token=login.raw_refresh_token, ip_address=None, user_agent=None
        )


async def test_delete_user_rejects_self_deletion(user_service, auth_service):
    actor = await _register(auth_service, "delete-self")

    with pytest.raises(SelfActionNotAllowedError):
        await user_service.delete_user(actor=actor, user_id=actor.id)


# ---------------------------------------------------------------------
# Status: Activate / Deactivate / Lock / Unlock
# ---------------------------------------------------------------------


async def test_deactivate_then_activate_round_trip(user_service, auth_service):
    actor = await _register(auth_service, "status-actor")
    target = await _register(auth_service, "status-target")

    deactivated = await user_service.deactivate_user(actor=actor, user_id=target.id)
    assert deactivated.status == UserStatus.INACTIVE

    activated = await user_service.activate_user(actor=actor, user_id=target.id)
    assert activated.status == UserStatus.ACTIVE


async def test_activate_rejects_already_active_user(user_service, auth_service):
    actor = await _register(auth_service, "activate-noop-actor")
    target = await _register(auth_service, "activate-noop-target")

    with pytest.raises(InvalidUserStatusTransitionError):
        await user_service.activate_user(actor=actor, user_id=target.id)


async def test_deactivate_rejects_self(user_service, auth_service):
    actor = await _register(auth_service, "deactivate-self")

    with pytest.raises(SelfActionNotAllowedError):
        await user_service.deactivate_user(actor=actor, user_id=actor.id)


async def test_deactivate_revokes_active_sessions(user_service, auth_service):
    actor = await _register(auth_service, "deactivate-revoke-actor")
    target = await _register(auth_service, "deactivate-revoke-target")
    login = await auth_service.login(
        email=target.email, password=_PASSWORD, remember_me=False, ip_address=None, user_agent=None
    )

    await user_service.deactivate_user(actor=actor, user_id=target.id)

    with pytest.raises(TokenInvalidError):
        await auth_service.refresh(
            raw_refresh_token=login.raw_refresh_token, ip_address=None, user_agent=None
        )


async def test_deactivate_blocked_when_it_would_leave_no_one_able_to_manage_status(
    user_service, auth_service, monkeypatch
):
    """The genuinely-last-admin scenario can't be constructed naturally
    against this shared, never-reset test database (it already holds
    real active admin accounts, and test data is only ever additive —
    see test_user_repository.py's delta-based
    `count_active_holders_of_permission` tests for how that's worked
    around elsewhere). Monkeypatching the repository's count for this
    one call isolates the unit from that uncontrollable global
    precondition — the same technique test_auth_service.py's
    `test_replay_outside_grace_window_revokes_the_family` already uses
    for an equally hard-to-construct-naturally scenario."""
    actor = await _register(auth_service, "last-admin-actor")
    target = await _register(auth_service, "last-admin-target")

    async def _zero_remaining(*args, **kwargs):
        return 0

    monkeypatch.setattr(
        user_service._user_repo, "count_active_holders_of_permission", _zero_remaining
    )

    with pytest.raises(LastAdminCannotBeDeactivatedError):
        await user_service.deactivate_user(actor=actor, user_id=target.id)

    # Never partially applied — the account is exactly as before the
    # blocked attempt.
    unchanged = await user_service.get_user(target.id)
    assert unchanged.status == UserStatus.ACTIVE


async def test_deactivate_allowed_when_another_active_holder_remains(
    user_service, auth_service, grant_permission
):
    """Deterministic, not dependent on the shared database's real admin
    count — grants `users:manage_status` to a dedicated "keeper" user
    first, so at least one other holder is guaranteed to remain no
    matter what else is in the database."""
    actor = await _register(auth_service, "keeper-actor")
    keeper = await _register(auth_service, "keeper-holder")
    await grant_permission(keeper, PERMISSION_USERS_MANAGE_STATUS)
    target = await _register(auth_service, "keeper-target")

    deactivated = await user_service.deactivate_user(actor=actor, user_id=target.id)

    assert deactivated.status == UserStatus.INACTIVE


async def test_deactivate_and_activate_are_audit_logged(user_service, auth_service, real_session):
    actor = await _register(auth_service, "audit-actor")
    target = await _register(auth_service, "audit-target")

    await user_service.deactivate_user(actor=actor, user_id=target.id)
    await user_service.activate_user(actor=actor, user_id=target.id)

    deactivated_logs = (
        (
            await real_session.execute(
                select(AuditLog).where(
                    AuditLog.event_type == AuditEventType.USER_DEACTIVATED,
                    AuditLog.target_user_id == target.id,
                )
            )
        )
        .scalars()
        .all()
    )
    activated_logs = (
        (
            await real_session.execute(
                select(AuditLog).where(
                    AuditLog.event_type == AuditEventType.USER_ACTIVATED,
                    AuditLog.target_user_id == target.id,
                )
            )
        )
        .scalars()
        .all()
    )

    assert len(deactivated_logs) == 1
    assert deactivated_logs[0].actor_user_id == actor.id
    assert len(activated_logs) == 1
    assert activated_logs[0].actor_user_id == actor.id


async def test_lock_rejects_self(user_service, auth_service):
    actor = await _register(auth_service, "lock-self")

    with pytest.raises(SelfActionNotAllowedError):
        await user_service.lock_user(actor=actor, user_id=actor.id)


async def test_lock_then_unlock_round_trip(user_service, auth_service):
    actor = await _register(auth_service, "lock-actor")
    target = await _register(auth_service, "lock-target")

    locked = await user_service.lock_user(actor=actor, user_id=target.id)
    assert locked.status == UserStatus.LOCKED

    with pytest.raises(InvalidUserStatusTransitionError):
        await user_service.lock_user(actor=actor, user_id=target.id)

    unlocked = await user_service.unlock_user(actor=actor, user_id=target.id)
    assert unlocked.status == UserStatus.ACTIVE
    assert unlocked.locked_until is None
    assert unlocked.failed_login_attempts == 0


async def test_unlock_rejects_user_that_is_not_locked(user_service, auth_service):
    actor = await _register(auth_service, "unlock-noop-actor")
    target = await _register(auth_service, "unlock-noop-target")

    with pytest.raises(InvalidUserStatusTransitionError):
        await user_service.unlock_user(actor=actor, user_id=target.id)


async def test_locked_user_cannot_login(user_service, auth_service):
    actor = await _register(auth_service, "lock-login-actor")
    target = await _register(auth_service, "lock-login-target")
    await user_service.lock_user(actor=actor, user_id=target.id)

    with pytest.raises(AccountLockedError):
        await auth_service.login(
            email=target.email,
            password=_PASSWORD,
            remember_me=False,
            ip_address=None,
            user_agent=None,
        )


# ---------------------------------------------------------------------
# Password: Admin Reset / Force Change
# ---------------------------------------------------------------------


async def test_admin_reset_password_issues_working_temporary_password(user_service, auth_service):
    actor = await _register(auth_service, "reset-pw-actor")
    target = await _register(auth_service, "reset-pw-target")
    login = await auth_service.login(
        email=target.email, password=_PASSWORD, remember_me=False, ip_address=None, user_agent=None
    )

    updated, temporary_password = await user_service.admin_reset_password(
        actor=actor, user_id=target.id
    )

    assert updated.must_change_password is True
    with pytest.raises(TokenInvalidError):
        await auth_service.refresh(
            raw_refresh_token=login.raw_refresh_token, ip_address=None, user_agent=None
        )
    relogin = await auth_service.login(
        email=target.email,
        password=temporary_password,
        remember_me=False,
        ip_address=None,
        user_agent=None,
    )
    assert relogin.access_token


async def test_force_password_change_sets_flag_without_touching_password(
    user_service, auth_service
):
    actor = await _register(auth_service, "force-pw-actor")
    target = await _register(auth_service, "force-pw-target")
    original_hash = target.password_hash

    updated = await user_service.force_password_change(actor=actor, user_id=target.id)

    assert updated.must_change_password is True
    assert updated.password_hash == original_hash
    # Idempotent: calling again on an already-flagged user must not raise.
    await user_service.force_password_change(actor=actor, user_id=target.id)


# ---------------------------------------------------------------------
# Role Assignment: Assign / Remove / Replace
# ---------------------------------------------------------------------


async def test_assign_roles_grants_and_is_idempotent(user_service, auth_service, real_session):
    actor = await _register(auth_service, "assign-actor")
    target = await _register(auth_service, "assign-target")
    role = await _make_role(real_session, "assign")

    updated = await user_service.assign_roles(actor=actor, user_id=target.id, role_ids=[role.id])
    assert role.name in [ur.role.name for ur in updated.user_roles if ur.deleted_at is None]

    # Re-assigning the same role must not raise and must not duplicate.
    again = await user_service.assign_roles(actor=actor, user_id=target.id, role_ids=[role.id])
    active_role_ids = [ur.role_id for ur in again.user_roles if ur.deleted_at is None]
    assert active_role_ids.count(role.id) == 1


async def test_assign_roles_rejects_unknown_role(user_service, auth_service):
    actor = await _register(auth_service, "assign-unknown-actor")
    target = await _register(auth_service, "assign-unknown-target")

    with pytest.raises(RoleNotFoundError):
        await user_service.assign_roles(actor=actor, user_id=target.id, role_ids=[uuid7()])


async def test_assign_roles_rejects_inactive_role(user_service, auth_service, real_session):
    actor = await _register(auth_service, "assign-inactive-actor")
    target = await _register(auth_service, "assign-inactive-target")
    role = await _make_role(real_session, "inactive", is_active=False)

    with pytest.raises(RoleInactiveError):
        await user_service.assign_roles(actor=actor, user_id=target.id, role_ids=[role.id])


async def test_remove_roles_revokes_and_is_idempotent(user_service, auth_service, real_session):
    actor = await _register(auth_service, "remove-actor")
    target = await _register(auth_service, "remove-target")
    role = await _make_role(real_session, "remove")
    await user_service.assign_roles(actor=actor, user_id=target.id, role_ids=[role.id])

    updated = await user_service.remove_roles(actor=actor, user_id=target.id, role_ids=[role.id])
    assert all(ur.deleted_at is not None for ur in updated.user_roles if ur.role_id == role.id)

    # Removing again (nothing active left to remove) must not raise.
    await user_service.remove_roles(actor=actor, user_id=target.id, role_ids=[role.id])


async def test_remove_roles_on_unassigned_role_is_a_noop(user_service, auth_service, real_session):
    actor = await _register(auth_service, "remove-noop-actor")
    target = await _register(auth_service, "remove-noop-target")
    role = await _make_role(real_session, "remove-noop")

    result = await user_service.remove_roles(actor=actor, user_id=target.id, role_ids=[role.id])

    assert result.id == target.id


async def test_replace_roles_sets_exact_role_set(user_service, auth_service, real_session):
    actor = await _register(auth_service, "replace-actor")
    target = await _register(auth_service, "replace-target")
    role_a = await _make_role(real_session, "replace-a")
    role_b = await _make_role(real_session, "replace-b")
    await user_service.assign_roles(actor=actor, user_id=target.id, role_ids=[role_a.id])

    updated = await user_service.replace_roles(actor=actor, user_id=target.id, role_ids=[role_b.id])

    active_role_ids = {ur.role_id for ur in updated.user_roles if ur.deleted_at is None}
    assert active_role_ids == {role_b.id}


async def test_replace_roles_with_empty_list_clears_all_roles(
    user_service, auth_service, real_session
):
    actor = await _register(auth_service, "replace-empty-actor")
    target = await _register(auth_service, "replace-empty-target")
    role = await _make_role(real_session, "replace-empty")
    await user_service.assign_roles(actor=actor, user_id=target.id, role_ids=[role.id])

    updated = await user_service.replace_roles(actor=actor, user_id=target.id, role_ids=[])

    assert all(ur.deleted_at is not None for ur in updated.user_roles)

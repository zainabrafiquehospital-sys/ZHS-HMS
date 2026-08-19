from datetime import timedelta

import pytest

from app.modules.auth.exceptions import (
    AccountLockedError,
    EmailAlreadyRegisteredError,
    InvalidCredentialsError,
    PasswordPolicyViolationError,
    PasswordReusedError,
    TokenInvalidError,
)
from app.modules.auth.repository import UserRepository
from tests.conftest import make_test_email

_PASSWORD = "Str0ng!Passw0rd#2026"


async def _register(auth_service, suffix: str, password: str = _PASSWORD):
    return await auth_service.register(
        email=make_test_email(suffix), password=password, full_name="Test User"
    )


# ---------------------------------------------------------------------
# Register
# ---------------------------------------------------------------------


async def test_register_creates_a_loggable_in_user(auth_service):
    user = await _register(auth_service, "register-basic")

    assert user.email == make_test_email("register-basic")
    result = await auth_service.login(
        email=user.email, password=_PASSWORD, remember_me=False, ip_address=None, user_agent=None
    )
    assert result.access_token


async def test_register_rejects_duplicate_email(auth_service):
    await _register(auth_service, "register-dup")

    with pytest.raises(EmailAlreadyRegisteredError):
        await _register(auth_service, "register-dup")


async def test_register_rejects_weak_password(auth_service):
    with pytest.raises(PasswordPolicyViolationError):
        await _register(auth_service, "register-weak", password="short")


# ---------------------------------------------------------------------
# Login / lockout
# ---------------------------------------------------------------------


async def test_login_wrong_password_raises_invalid_credentials(auth_service):
    user = await _register(auth_service, "login-wrong-pw")

    with pytest.raises(InvalidCredentialsError):
        await auth_service.login(
            email=user.email,
            password="wrong-password",
            remember_me=False,
            ip_address=None,
            user_agent=None,
        )


async def test_login_unknown_email_raises_invalid_credentials(auth_service):
    with pytest.raises(InvalidCredentialsError):
        await auth_service.login(
            email=make_test_email("does-not-exist"),
            password="whatever12345",
            remember_me=False,
            ip_address=None,
            user_agent=None,
        )


async def test_account_locks_after_configured_threshold(auth_service):
    user = await _register(auth_service, "lockout")

    for _ in range(3):  # auth_settings fixture sets account_lockout_threshold=3
        with pytest.raises(InvalidCredentialsError):
            await auth_service.login(
                email=user.email,
                password="wrong-password",
                remember_me=False,
                ip_address=None,
                user_agent=None,
            )

    with pytest.raises(AccountLockedError):
        await auth_service.login(
            email=user.email,
            password=_PASSWORD,
            remember_me=False,
            ip_address=None,
            user_agent=None,
        )


async def test_successful_login_resets_failed_attempts(auth_service, real_session):
    user = await _register(auth_service, "reset-attempts")

    with pytest.raises(InvalidCredentialsError):
        await auth_service.login(
            email=user.email,
            password="wrong-password",
            remember_me=False,
            ip_address=None,
            user_agent=None,
        )
    await auth_service.login(
        email=user.email, password=_PASSWORD, remember_me=False, ip_address=None, user_agent=None
    )

    await real_session.refresh(user, attribute_names=["failed_login_attempts"])
    assert user.failed_login_attempts == 0


# ---------------------------------------------------------------------
# Refresh rotation / replay handling
# ---------------------------------------------------------------------


async def test_refresh_rotates_to_a_new_token(auth_service):
    user = await _register(auth_service, "refresh-basic")
    login = await auth_service.login(
        email=user.email, password=_PASSWORD, remember_me=False, ip_address=None, user_agent=None
    )

    refreshed = await auth_service.refresh(
        raw_refresh_token=login.raw_refresh_token, ip_address=None, user_agent=None
    )

    assert refreshed.raw_refresh_token != login.raw_refresh_token
    assert refreshed.access_token != login.access_token


async def test_refresh_rejects_unknown_token(auth_service):
    with pytest.raises(TokenInvalidError):
        await auth_service.refresh(
            raw_refresh_token="not-a-real-token", ip_address=None, user_agent=None
        )


async def test_refresh_accepts_matching_expected_user_id(auth_service):
    """`expected_user_id` matching the token's real owner must behave
    exactly like omitting it — the guard is only ever supposed to reject
    a genuine mismatch, never a normal, single-identity refresh."""
    user = await _register(auth_service, "refresh-expected-match")
    login = await auth_service.login(
        email=user.email, password=_PASSWORD, remember_me=False, ip_address=None, user_agent=None
    )

    refreshed = await auth_service.refresh(
        raw_refresh_token=login.raw_refresh_token,
        ip_address=None,
        user_agent=None,
        expected_user_id=user.id,
    )

    assert refreshed.user.id == user.id


async def test_refresh_rejects_mismatched_expected_user_id(auth_service, real_session):
    """The 2026-08-19 audit's cross-tab identity-bleed scenario, at the
    service layer: Staff A's tab believes it is refreshing as A
    (`expected_user_id=A.id`), but the cookie it actually presents
    belongs to B (a second login on the same shared browser). This must
    fail exactly like any other invalid token — never silently hand back
    a valid session for B."""
    user_a = await _register(auth_service, "refresh-mismatch-a")
    user_b = await _register(auth_service, "refresh-mismatch-b")
    login_b = await auth_service.login(
        email=user_b.email,
        password=_PASSWORD,
        remember_me=False,
        ip_address=None,
        user_agent=None,
    )

    with pytest.raises(TokenInvalidError):
        await auth_service.refresh(
            raw_refresh_token=login_b.raw_refresh_token,
            ip_address=None,
            user_agent=None,
            expected_user_id=user_a.id,
        )

    # The mismatch must not have disturbed B's own, genuinely valid
    # refresh token — B's real session is collateral-free.
    real_refresh = await auth_service.refresh(
        raw_refresh_token=login_b.raw_refresh_token,
        ip_address=None,
        user_agent=None,
        expected_user_id=user_b.id,
    )
    assert real_refresh.user.id == user_b.id


async def test_replay_within_grace_window_is_benign(auth_service):
    """Two callers presenting the same already-rotated token within the
    grace window must both end up with a valid session — this is the
    concurrent-request race the grace window exists to tolerate."""
    user = await _register(auth_service, "replay-benign")
    login = await auth_service.login(
        email=user.email, password=_PASSWORD, remember_me=False, ip_address=None, user_agent=None
    )

    await auth_service.refresh(
        raw_refresh_token=login.raw_refresh_token, ip_address=None, user_agent=None
    )
    # Reusing the ORIGINAL (now-rotated) token again, immediately after —
    # well within the default grace window.
    second = await auth_service.refresh(
        raw_refresh_token=login.raw_refresh_token, ip_address=None, user_agent=None
    )

    assert second.access_token


async def test_replay_outside_grace_window_revokes_the_family(auth_service, monkeypatch):
    user = await _register(auth_service, "replay-attack")
    login = await auth_service.login(
        email=user.email, password=_PASSWORD, remember_me=False, ip_address=None, user_agent=None
    )
    refreshed = await auth_service.refresh(
        raw_refresh_token=login.raw_refresh_token, ip_address=None, user_agent=None
    )

    import app.core.token_rotation as token_rotation

    monkeypatch.setattr(token_rotation, "default_grace_window", lambda: timedelta(seconds=-1))

    with pytest.raises(TokenInvalidError):
        await auth_service.refresh(
            raw_refresh_token=login.raw_refresh_token, ip_address=None, user_agent=None
        )

    # The entire family — including the token that had just been issued
    # legitimately — must now be dead.
    with pytest.raises(TokenInvalidError):
        await auth_service.refresh(
            raw_refresh_token=refreshed.raw_refresh_token, ip_address=None, user_agent=None
        )


async def test_replaying_a_logged_out_token_is_treated_as_reuse(auth_service):
    """Unlike a natural rotation race, replaying a token that was revoked
    by an explicit action (logout) must never be tolerated, regardless of
    timing — see AuthService.refresh's `reused_legitimately` check."""
    user = await _register(auth_service, "replay-after-logout")
    login = await auth_service.login(
        email=user.email, password=_PASSWORD, remember_me=False, ip_address=None, user_agent=None
    )
    await auth_service.logout(raw_refresh_token=login.raw_refresh_token)

    with pytest.raises(TokenInvalidError):
        await auth_service.refresh(
            raw_refresh_token=login.raw_refresh_token, ip_address=None, user_agent=None
        )


# ---------------------------------------------------------------------
# Logout / logout-all
# ---------------------------------------------------------------------


async def test_logout_revokes_the_token(auth_service):
    user = await _register(auth_service, "logout-basic")
    login = await auth_service.login(
        email=user.email, password=_PASSWORD, remember_me=False, ip_address=None, user_agent=None
    )

    await auth_service.logout(raw_refresh_token=login.raw_refresh_token)

    with pytest.raises(TokenInvalidError):
        await auth_service.refresh(
            raw_refresh_token=login.raw_refresh_token, ip_address=None, user_agent=None
        )


async def test_logout_is_idempotent(auth_service):
    user = await _register(auth_service, "logout-idempotent")
    login = await auth_service.login(
        email=user.email, password=_PASSWORD, remember_me=False, ip_address=None, user_agent=None
    )

    await auth_service.logout(raw_refresh_token=login.raw_refresh_token)
    await auth_service.logout(raw_refresh_token=login.raw_refresh_token)  # must not raise


async def test_logout_with_unknown_token_does_not_raise(auth_service):
    await auth_service.logout(raw_refresh_token="never-existed")  # must not raise


async def test_logout_all_revokes_every_session(auth_service):
    user = await _register(auth_service, "logout-all")
    first = await auth_service.login(
        email=user.email, password=_PASSWORD, remember_me=False, ip_address=None, user_agent=None
    )
    second = await auth_service.login(
        email=user.email, password=_PASSWORD, remember_me=False, ip_address=None, user_agent=None
    )

    await auth_service.logout_all(user=user)

    with pytest.raises(TokenInvalidError):
        await auth_service.refresh(
            raw_refresh_token=first.raw_refresh_token, ip_address=None, user_agent=None
        )
    with pytest.raises(TokenInvalidError):
        await auth_service.refresh(
            raw_refresh_token=second.raw_refresh_token, ip_address=None, user_agent=None
        )


async def test_logout_all_blacklists_the_current_access_token(auth_service, token_service):
    user = await _register(auth_service, "logout-all-blacklist")
    login = await auth_service.login(
        email=user.email, password=_PASSWORD, remember_me=False, ip_address=None, user_agent=None
    )
    claims = await token_service.decode_access_token(login.access_token)

    await auth_service.logout_all(user=user, current_access_token_jti=claims["jti"])

    assert await token_service.is_blacklisted(claims["jti"]) is True


# ---------------------------------------------------------------------
# Change password
# ---------------------------------------------------------------------


async def test_change_password_succeeds_and_updates_hash(auth_service):
    user = await _register(auth_service, "change-pw")
    old_hash = user.password_hash

    await auth_service.change_password(
        user=user, current_password=_PASSWORD, new_password="EvenStr0nger!Pass#2026"
    )

    assert user.password_hash != old_hash


async def test_change_password_wrong_current_password_raises(auth_service):
    user = await _register(auth_service, "change-pw-wrong")

    with pytest.raises(InvalidCredentialsError):
        await auth_service.change_password(
            user=user, current_password="wrong", new_password="EvenStr0nger!Pass#2026"
        )


async def test_change_password_rejects_reused_password(auth_service):
    user = await _register(auth_service, "change-pw-reuse")
    await auth_service.change_password(
        user=user, current_password=_PASSWORD, new_password="EvenStr0nger!Pass#2026"
    )

    with pytest.raises(PasswordReusedError):
        await auth_service.change_password(
            user=user, current_password="EvenStr0nger!Pass#2026", new_password=_PASSWORD
        )


async def test_change_password_revokes_all_existing_sessions(auth_service):
    user = await _register(auth_service, "change-pw-revoke")
    login = await auth_service.login(
        email=user.email, password=_PASSWORD, remember_me=False, ip_address=None, user_agent=None
    )

    await auth_service.change_password(
        user=user, current_password=_PASSWORD, new_password="EvenStr0nger!Pass#2026"
    )

    with pytest.raises(TokenInvalidError):
        await auth_service.refresh(
            raw_refresh_token=login.raw_refresh_token, ip_address=None, user_agent=None
        )


# ---------------------------------------------------------------------
# Role / permission loading
# ---------------------------------------------------------------------


async def test_effective_role_names_empty_for_new_user(auth_service, real_session):
    user = await _register(auth_service, "roles-empty")
    # Every real caller (login/refresh/get_current_user) invokes these
    # methods on a User obtained via a fresh repository fetch, which is
    # what makes the `lazy="selectin"` relationship chain already loaded
    # — see _active_roles's docstring. Re-fetching here matches that.
    fetched = await UserRepository(real_session).get_by_id(user.id)

    assert auth_service.effective_role_names(fetched) == []


async def test_effective_permission_codes_empty_for_new_user(auth_service, real_session):
    user = await _register(auth_service, "permissions-empty")
    fetched = await UserRepository(real_session).get_by_id(user.id)

    assert auth_service.effective_permission_codes(fetched) == set()

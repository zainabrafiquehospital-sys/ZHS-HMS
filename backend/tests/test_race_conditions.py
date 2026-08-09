"""Production QA hardening (post Phase 5): regression tests for a real
concurrency bug found by deliberately trying to break every
check-then-insert duplicate-prevention path in this codebase. Two
genuinely independent sessions/engines are used per test — not the
single shared `real_session` fixture every other test file uses — to
faithfully simulate two separate concurrent HTTP requests, each with
its own connection, exactly as would happen in production. A single
shared `AsyncSession` cannot reproduce this: SQLAlchemy sessions are not
safe for concurrent use from multiple coroutines, and more importantly
a single session sees its own uncommitted work, which would hide the
race entirely.

Before the fix: the second of two concurrent requests creating/renaming
to the same email/phone/role-name/permission-code got an unhandled
`IntegrityError` (raw 500) instead of the same clean 409 it would get
outside the race window. After the fix: exactly one request succeeds,
and the other gets the correct domain exception, indistinguishable from
the non-racing duplicate case."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool
from uuid6 import uuid7

from app.core.config import get_settings
from app.modules.auth.exceptions import (
    EmailAlreadyRegisteredError,
    PermissionCodeAlreadyExistsError,
    PhoneNumberAlreadyRegisteredError,
    RoleNameAlreadyExistsError,
)
from app.modules.auth.models import Role
from app.modules.auth.otp_service import OtpService
from app.modules.auth.password_service import PasswordService
from app.modules.auth.permission_service import PermissionService
from app.modules.auth.repository import (
    AuditRepository,
    LoginSessionRepository,
    OtpCodeRepository,
    PasswordHistoryRepository,
    PermissionRepository,
    RefreshTokenRepository,
    RolePermissionRepository,
    RoleRepository,
    UserRepository,
    UserRoleRepository,
)
from app.modules.auth.role_service import RoleService
from app.modules.auth.service import AuthService
from app.modules.auth.token_service import TokenService
from app.modules.auth.user_service import UserService
from app.shared.email.service import EmailService
from tests.conftest import TEST_PERMISSION_GROUP_PREFIX, TEST_ROLE_PREFIX, make_test_email

_PASSWORD = "Str0ng!Passw0rd#2026"


@asynccontextmanager
async def _independent_session() -> AsyncIterator[AsyncSession]:
    """A brand-new engine + session, never shared with any other
    fixture — the only way to get a genuinely separate database
    connection, matching what two different HTTP requests would each
    get from `get_db` in production."""
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    session = AsyncSession(engine, expire_on_commit=False)
    try:
        yield session
    finally:
        await session.close()
        await engine.dispose()


def _role_service_for(session: AsyncSession) -> RoleService:
    return RoleService(
        session=session,
        role_repository=RoleRepository(session),
        user_role_repository=UserRoleRepository(session),
        permission_repository=PermissionRepository(session),
        role_permission_repository=RolePermissionRepository(session),
        audit_repository=AuditRepository(session),
    )


def _permission_service_for(session: AsyncSession) -> PermissionService:
    return PermissionService(
        session=session,
        permission_repository=PermissionRepository(session),
        role_permission_repository=RolePermissionRepository(session),
        audit_repository=AuditRepository(session),
    )


def _user_service_for(session: AsyncSession) -> UserService:
    return UserService(
        session=session,
        user_repository=UserRepository(session),
        role_repository=RoleRepository(session),
        user_role_repository=UserRoleRepository(session),
        password_history_repository=PasswordHistoryRepository(session),
        refresh_token_repository=RefreshTokenRepository(session),
        login_session_repository=LoginSessionRepository(session),
        audit_repository=AuditRepository(session),
        password_service=PasswordService(),
    )


def _auth_service_for(session: AsyncSession, jwt_key_registry, fake_redis) -> AuthService:
    """Uses the real app settings (`get_settings()`), not the
    lockout-threshold-3 `auth_settings` test fixture — these race tests
    don't exercise lockout behavior, only the create/insert path, so the
    real settings are simpler and just as correct here."""
    settings = get_settings()
    token_service = TokenService(key_registry=jwt_key_registry, settings=settings, redis=fake_redis)
    return AuthService(
        session=session,
        settings=settings,
        user_repository=UserRepository(session),
        refresh_token_repository=RefreshTokenRepository(session),
        login_session_repository=LoginSessionRepository(session),
        password_history_repository=PasswordHistoryRepository(session),
        audit_repository=AuditRepository(session),
        password_service=PasswordService(),
        token_service=token_service,
        otp_code_repository=OtpCodeRepository(session),
        otp_service=OtpService(),
        email_service=EmailService(settings),
    )


def _assert_exactly_one_winner(results: list, expected_error: type[Exception]) -> None:
    successes = [r for r in results if not isinstance(r, Exception)]
    failures = [r for r in results if isinstance(r, Exception)]
    assert len(successes) == 1, f"expected exactly one winner, got {results!r}"
    assert len(failures) == 1, f"expected exactly one loser, got {results!r}"
    assert isinstance(failures[0], expected_error), (
        f"the losing request must surface as {expected_error.__name__}, "
        f"not a raw database error: got {failures[0]!r}"
    )


async def test_concurrent_create_role_same_name_is_handled_cleanly(real_session, auth_service):
    actor = await auth_service.register(
        email=make_test_email("race-role-actor"), password=_PASSWORD, full_name="Race Actor"
    )
    name = f"{TEST_ROLE_PREFIX}{uuid7()}"

    async with _independent_session() as session_a, _independent_session() as session_b:
        results = await asyncio.gather(
            _role_service_for(session_a).create_role(
                actor=actor, name=name, description=None, parent_role_id=None
            ),
            _role_service_for(session_b).create_role(
                actor=actor, name=name, description=None, parent_role_id=None
            ),
            return_exceptions=True,
        )

    _assert_exactly_one_winner(results, RoleNameAlreadyExistsError)


async def test_concurrent_rename_role_to_same_name_is_handled_cleanly(real_session, auth_service):
    actor = await auth_service.register(
        email=make_test_email("race-rename-actor"), password=_PASSWORD, full_name="Race Actor"
    )
    target_name = f"{TEST_ROLE_PREFIX}{uuid7()}"
    role_repo = RoleRepository(real_session)
    role_one = await role_repo.add(Role(name=f"{TEST_ROLE_PREFIX}{uuid7()}"))
    role_two = await role_repo.add(Role(name=f"{TEST_ROLE_PREFIX}{uuid7()}"))
    await real_session.commit()

    async with _independent_session() as session_a, _independent_session() as session_b:
        results = await asyncio.gather(
            _role_service_for(session_a).update_role(
                actor=actor, role_id=role_one.id, updates={"name": target_name}
            ),
            _role_service_for(session_b).update_role(
                actor=actor, role_id=role_two.id, updates={"name": target_name}
            ),
            return_exceptions=True,
        )

    _assert_exactly_one_winner(results, RoleNameAlreadyExistsError)


async def test_concurrent_create_permission_same_code_is_handled_cleanly(
    real_session, auth_service
):
    actor = await auth_service.register(
        email=make_test_email("race-perm-actor"), password=_PASSWORD, full_name="Race Actor"
    )
    suffix = uuid7().hex
    code = f"{TEST_PERMISSION_GROUP_PREFIX}{suffix}:act{suffix}"

    async with _independent_session() as session_a, _independent_session() as session_b:
        results = await asyncio.gather(
            _permission_service_for(session_a).create_permission(
                actor=actor, code=code, display_name="Race", description=None
            ),
            _permission_service_for(session_b).create_permission(
                actor=actor, code=code, display_name="Race", description=None
            ),
            return_exceptions=True,
        )

    _assert_exactly_one_winner(results, PermissionCodeAlreadyExistsError)


async def test_concurrent_create_user_same_email_is_handled_cleanly(real_session, auth_service):
    actor = await auth_service.register(
        email=make_test_email("race-user-email-actor"), password=_PASSWORD, full_name="Race Actor"
    )
    email = make_test_email(f"race-user-email-{uuid7().hex}")

    async with _independent_session() as session_a, _independent_session() as session_b:
        results = await asyncio.gather(
            _user_service_for(session_a).create_user(
                actor=actor, email=email, full_name="A", phone_number=None
            ),
            _user_service_for(session_b).create_user(
                actor=actor, email=email, full_name="B", phone_number=None
            ),
            return_exceptions=True,
        )

    _assert_exactly_one_winner(results, EmailAlreadyRegisteredError)


async def test_concurrent_create_user_same_phone_is_handled_cleanly(real_session, auth_service):
    actor = await auth_service.register(
        email=make_test_email("race-user-phone-actor"), password=_PASSWORD, full_name="Race Actor"
    )
    phone = f"+1555{uuid7().int % 10_000_000:07d}"

    async with _independent_session() as session_a, _independent_session() as session_b:
        results = await asyncio.gather(
            _user_service_for(session_a).create_user(
                actor=actor,
                email=make_test_email(f"race-user-phone-a-{uuid7().hex}"),
                full_name="A",
                phone_number=phone,
            ),
            _user_service_for(session_b).create_user(
                actor=actor,
                email=make_test_email(f"race-user-phone-b-{uuid7().hex}"),
                full_name="B",
                phone_number=phone,
            ),
            return_exceptions=True,
        )

    _assert_exactly_one_winner(results, PhoneNumberAlreadyRegisteredError)


async def test_concurrent_register_same_email_is_handled_cleanly(
    real_session, jwt_key_registry, fake_redis
):
    email = make_test_email(f"race-register-{uuid7().hex}")

    async with _independent_session() as session_a, _independent_session() as session_b:
        results = await asyncio.gather(
            _auth_service_for(session_a, jwt_key_registry, fake_redis).register(
                email=email, password=_PASSWORD, full_name="A"
            ),
            _auth_service_for(session_b, jwt_key_registry, fake_redis).register(
                email=email, password=_PASSWORD, full_name="B"
            ),
            return_exceptions=True,
        )

    _assert_exactly_one_winner(results, EmailAlreadyRegisteredError)


async def test_concurrent_register_same_phone_is_handled_cleanly(
    real_session, jwt_key_registry, fake_redis
):
    """Regression test for the second bug found alongside the race
    condition: `AuthService.register` previously never checked
    `phone_number` for duplicates at all, racing or not."""
    phone = f"+1555{uuid7().int % 10_000_000:07d}"

    async with _independent_session() as session_a, _independent_session() as session_b:
        results = await asyncio.gather(
            _auth_service_for(session_a, jwt_key_registry, fake_redis).register(
                email=make_test_email(f"race-register-phone-a-{uuid7().hex}"),
                password=_PASSWORD,
                full_name="A",
                phone_number=phone,
            ),
            _auth_service_for(session_b, jwt_key_registry, fake_redis).register(
                email=make_test_email(f"race-register-phone-b-{uuid7().hex}"),
                password=_PASSWORD,
                full_name="B",
                phone_number=phone,
            ),
            return_exceptions=True,
        )

    _assert_exactly_one_winner(results, PhoneNumberAlreadyRegisteredError)


async def test_register_rejects_duplicate_phone_without_any_race(auth_service):
    """Non-racing regression test for the same gap: even a single,
    ordinary sequential call must reject a duplicate phone number
    cleanly, not just under concurrency."""
    phone = f"+1555{uuid7().int % 10_000_000:07d}"
    await auth_service.register(
        email=make_test_email(f"register-phone-dup-a-{uuid7().hex}"),
        password=_PASSWORD,
        full_name="A",
        phone_number=phone,
    )

    with pytest.raises(PhoneNumberAlreadyRegisteredError):
        await auth_service.register(
            email=make_test_email(f"register-phone-dup-b-{uuid7().hex}"),
            password=_PASSWORD,
            full_name="B",
            phone_number=phone,
        )

import shutil
import tempfile
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fakeredis import aioredis as fakeaioredis
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool
from uuid6 import uuid7

from app.core.config import Settings, get_settings
from app.core.dependencies import get_db
from app.core.jwt_keys import JWTKeyRegistry, get_jwt_key_registry
from app.modules.auth.models import Permission, Role, RolePermission, User, UserRole
from app.modules.auth.password_service import PasswordService
from app.modules.auth.permission_service import PermissionService
from app.modules.auth.repository import (
    AuditRepository,
    LoginSessionRepository,
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
from app.modules.auth.validators import derive_permission_group
from app.modules.billing.repository import (
    InvoiceLineItemRepository,
    InvoiceRepository,
    PendingBillingItemRepository,
)
from app.modules.billing.service import BillingService
from app.modules.consultation.repository import ConsultationRepository
from app.modules.consultation.service import ConsultationService
from app.modules.dashboard.service import DashboardService
from app.modules.patients.repository import PatientRepository
from app.modules.patients.service import PatientService
from app.modules.queue.repository import QueueEntryRepository
from app.modules.queue.service import QueueService
from app.modules.reception.repository import ReceptionRepository
from app.modules.reception.service import ReceptionService
from app.modules.visits.repository import VisitRepository
from app.modules.visits.service import VisitService
from app.modules.vitals.repository import VitalsRecordRepository
from app.modules.vitals.service import VitalsService
from app.redis.client import get_redis_client
from app.shared.audit.repository import AuditLogRepository

# Every RBAC test fixture (grant_permission below) names its throwaway
# Role with this prefix, so teardown can delete it deterministically. The
# Permission it grants is deliberately NOT prefixed and NOT deleted per
# test — see grant_permission's docstring for why reusing the same small,
# fixed set of real permission-code rows across the whole suite is safe
# and correct, unlike the per-test Role/User rows.
TEST_ROLE_PREFIX = "test-role-"

# Distinct from the above: the Permission Management test suite
# (tests/test_permission_*.py) creates genuinely new Permission rows
# through the API/service itself, each with a unique, throwaway `code`
# (e.g. via a local `_unique_code()` helper) — this is real per-test
# data, not the small reusable reference set `grant_permission` grants,
# and must be cleaned up the same way `test-role-*` roles are. Every
# such test-generated code's group is prefixed with this string so
# `real_session`'s teardown can delete them deterministically.
TEST_PERMISSION_GROUP_PREFIX = "testperm"

# Every user created by the auth test suite uses this email prefix, so
# fixture teardown can reliably clean up regardless of which test created
# what — this is necessary (not just convenient) because AuthService
# commits internally (see service.py's module docstring), so the
# rollback-based isolation `db_session` above relies on doesn't apply to
# anything that goes through it.
TEST_EMAIL_PREFIX = "auth-test-"

# Every patient created through PatientService by the Patient Management
# test suite uses this full_name prefix, for the identical reason
# TEST_EMAIL_PREFIX exists — PatientService also commits internally (see
# app/modules/patients/service.py's module docstring). full_name, not
# mr_number, is what test cleanup filters on: mr_number is always
# server-generated (never caller-supplied — see PatientService's module
# docstring), so tests have no way to tag it with a recognizable prefix,
# but full_name is fully caller-controlled.
TEST_PATIENT_NAME_PREFIX = "Patient Test "


@pytest.fixture
async def db_session():
    """A session bound to a connection whose transaction is always rolled
    back at the end of the test, regardless of outcome — no test using this
    fixture ever leaves a row behind in the real database.

    Uses a fresh, unpooled engine per test rather than the app's shared
    module-level engine: pytest-asyncio gives each test its own event loop,
    and asyncpg connections are bound to the loop they were created on —
    reusing a pooled connection across tests reliably crashes with "Event
    loop is closed". `NullPool` means no connection survives past this
    single test to be reused on the next loop."""
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            async with AsyncSession(bind=connection) as session:
                yield session
            # A failed flush (e.g. an IntegrityError under test) leaves the
            # connection's transaction already deactivated by the time we
            # get here — rolling back an inactive transaction is harmless
            # but logs a spurious SAWarning, so only roll back if there's
            # still something active to undo.
            if transaction.is_active:
                await transaction.rollback()
    finally:
        await engine.dispose()


def make_test_email(local_part: str) -> str:
    return f"{TEST_EMAIL_PREFIX}{local_part}@example.com"


@pytest.fixture
def jwt_key_registry():
    """A real RS256 key pair in a throwaway directory — genuine
    cryptography, never the app's actual configured keys (which may not
    even be provisioned in this environment; see app/core/jwt_keys.py)."""
    tmp = Path(tempfile.mkdtemp())
    try:
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        (tmp / "test-kid.pem").write_bytes(pem)
        yield JWTKeyRegistry(keys_dir=tmp, active_kid="test-kid")
    finally:
        shutil.rmtree(tmp)


@pytest.fixture
async def fake_redis():
    """A faithful in-memory Redis protocol emulator — real Redis isn't
    available in every environment this suite runs in, and this is
    infrastructure the module depends on, not a repository being mocked
    (repositories and the database stay real throughout this suite)."""
    client = fakeaioredis.FakeRedis(decode_responses=True)
    yield client
    await client.aclose()


@pytest.fixture
def auth_settings() -> Settings:
    return Settings(
        database_url="unused",
        database_sync_url="unused",
        account_lockout_threshold=3,
        account_lockout_duration_minutes=15,
        password_history_depth=5,
    )


@pytest.fixture
def token_service(jwt_key_registry, auth_settings, fake_redis) -> TokenService:
    return TokenService(key_registry=jwt_key_registry, settings=auth_settings, redis=fake_redis)


@pytest.fixture
def password_service() -> PasswordService:
    return PasswordService()


@pytest.fixture
async def real_session():
    """A genuine, non-rollback-isolated session for tests that exercise
    AuthService/UserService/RoleService/PermissionService, all of which
    commit internally. Cleanup is by explicit deletion of every
    `auth-test-*@example.com` user (CASCADE removes their
    refresh_token/login_session/password_history/user_role rows too —
    see the ON DELETE policy documented in app/modules/auth/models.py),
    every `test-role-*` role (CASCADE removes its role_permission rows),
    every permission whose `group` starts with
    `TEST_PERMISSION_GROUP_PREFIX` (CASCADE removes its role_permission
    rows too), plus any orphaned audit_log rows the actor/target SET
    NULL policy leaves behind for anonymous events (e.g. a login attempt
    against no such account). `expire_on_commit=False` matches
    app/db/session.py's real `async_session_factory` — without it, every
    attribute on an object one of these services just committed becomes
    "expired" and triggers an implicit reload on next access, which
    fails outside an active async context (`MissingGreenlet`) the moment
    a test touches e.g. `user.email` after a service call returns."""
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session
            # Visit rows (and their audit_log entries) must be deleted
            # before the user/patient rows they FK to — visit.patient_id
            # and visit.doctor_user_id have no ON DELETE clause (see
            # app/modules/visits/models.py) — a patient or user row with
            # a surviving visit reference cannot be deleted first. Every
            # test visit is caught by *either* condition: tests that give
            # a visit a dedicated patient always use TEST_PATIENT_NAME_PREFIX
            # (see app/modules/patients/service.py's docstring on why
            # mr_number can't be used to tag test data instead), and every
            # visit's doctor is always a test-suite-created user under
            # TEST_EMAIL_PREFIX (including the common shortcut of reusing
            # the acting user as their own doctor in these tests).
            visit_owned_by_test_data = (
                "SELECT id FROM visit WHERE "
                "patient_id IN (SELECT id FROM patient WHERE full_name LIKE :patient_pattern) "
                "OR doctor_user_id IN "
                '(SELECT id FROM "user" WHERE email LIKE :email_pattern)'
            )
            cleanup_params = {
                "patient_pattern": f"{TEST_PATIENT_NAME_PREFIX}%",
                "email_pattern": f"{TEST_EMAIL_PREFIX}%@example.com",
            }
            # queue_entry rows (and their audit_log entries) must be
            # deleted before the visit rows they FK to (no ON DELETE
            # clause — see app/modules/queue/models.py), for the same
            # reason visit must be deleted before patient/user above.
            await session.execute(
                text(
                    "DELETE FROM audit_log WHERE entity_id IN "
                    f"(SELECT id FROM queue_entry WHERE visit_id IN ({visit_owned_by_test_data}))"
                ),
                cleanup_params,
            )
            await session.execute(
                text("DELETE FROM queue_entry WHERE visit_id IN " f"({visit_owned_by_test_data})"),
                cleanup_params,
            )
            # Billing rows must be deleted before visit for the same
            # reason (see app/modules/billing/models.py) — line items
            # first (they FK to both invoice and pending_billing_item).
            await session.execute(
                text(
                    "DELETE FROM audit_log WHERE entity_id IN "
                    f"(SELECT id FROM invoice WHERE visit_id IN ({visit_owned_by_test_data}))"
                ),
                cleanup_params,
            )
            await session.execute(
                text(
                    "DELETE FROM audit_log WHERE entity_id IN "
                    "(SELECT id FROM pending_billing_item WHERE visit_id IN "
                    f"({visit_owned_by_test_data}))"
                ),
                cleanup_params,
            )
            await session.execute(
                text(
                    "DELETE FROM invoice_line_item WHERE invoice_id IN "
                    f"(SELECT id FROM invoice WHERE visit_id IN ({visit_owned_by_test_data}))"
                ),
                cleanup_params,
            )
            await session.execute(
                text(f"DELETE FROM invoice WHERE visit_id IN ({visit_owned_by_test_data})"),
                cleanup_params,
            )
            await session.execute(
                text(
                    "DELETE FROM pending_billing_item WHERE visit_id IN "
                    f"({visit_owned_by_test_data})"
                ),
                cleanup_params,
            )
            # vitals_record rows must be deleted before both visit and
            # consultation — same no-ON-DELETE-clause reasoning (see
            # app/modules/vitals/models.py). Deleted first since it FKs
            # to consultation, which is itself about to be deleted next.
            await session.execute(
                text(
                    "DELETE FROM audit_log WHERE entity_id IN "
                    f"(SELECT id FROM vitals_record WHERE visit_id IN ({visit_owned_by_test_data}))"
                ),
                cleanup_params,
            )
            await session.execute(
                text(f"DELETE FROM vitals_record WHERE visit_id IN ({visit_owned_by_test_data})"),
                cleanup_params,
            )
            # consultation rows must likewise be deleted before visit —
            # same no-ON-DELETE-clause reasoning (see
            # app/modules/consultation/models.py).
            await session.execute(
                text(
                    "DELETE FROM audit_log WHERE entity_id IN "
                    f"(SELECT id FROM consultation WHERE visit_id IN ({visit_owned_by_test_data}))"
                ),
                cleanup_params,
            )
            await session.execute(
                text(f"DELETE FROM consultation WHERE visit_id IN ({visit_owned_by_test_data})"),
                cleanup_params,
            )
            await session.execute(
                text(f"DELETE FROM audit_log WHERE entity_id IN ({visit_owned_by_test_data})"),
                cleanup_params,
            )
            await session.execute(
                text(f"DELETE FROM visit WHERE id IN ({visit_owned_by_test_data})"),
                cleanup_params,
            )
            await session.execute(
                text(
                    "DELETE FROM audit_log WHERE entity_id IN "
                    "(SELECT id FROM patient WHERE full_name LIKE :pattern)"
                ),
                {"pattern": f"{TEST_PATIENT_NAME_PREFIX}%"},
            )
            await session.execute(
                text("DELETE FROM patient WHERE full_name LIKE :pattern"),
                {"pattern": f"{TEST_PATIENT_NAME_PREFIX}%"},
            )
            await session.execute(
                text('DELETE FROM "user" WHERE email LIKE :pattern'),
                {"pattern": f"{TEST_EMAIL_PREFIX}%@example.com"},
            )
            await session.execute(
                text("DELETE FROM role WHERE name LIKE :pattern"),
                {"pattern": f"{TEST_ROLE_PREFIX}%"},
            )
            await session.execute(
                text('DELETE FROM permission WHERE "group" LIKE :pattern'),
                {"pattern": f"{TEST_PERMISSION_GROUP_PREFIX}%"},
            )
            await session.execute(
                text(
                    "DELETE FROM auth_audit_log "
                    "WHERE actor_user_id IS NULL AND target_user_id IS NULL"
                )
            )
            await session.commit()
    finally:
        await engine.dispose()


@pytest.fixture
def user_service(real_session) -> UserService:
    return UserService(
        session=real_session,
        user_repository=UserRepository(real_session),
        role_repository=RoleRepository(real_session),
        user_role_repository=UserRoleRepository(real_session),
        password_history_repository=PasswordHistoryRepository(real_session),
        refresh_token_repository=RefreshTokenRepository(real_session),
        login_session_repository=LoginSessionRepository(real_session),
        audit_repository=AuditRepository(real_session),
        password_service=PasswordService(),
    )


@pytest.fixture
def role_service(real_session) -> RoleService:
    return RoleService(
        session=real_session,
        role_repository=RoleRepository(real_session),
        user_role_repository=UserRoleRepository(real_session),
        permission_repository=PermissionRepository(real_session),
        role_permission_repository=RolePermissionRepository(real_session),
        audit_repository=AuditRepository(real_session),
    )


@pytest.fixture
def permission_service(real_session) -> PermissionService:
    return PermissionService(
        session=real_session,
        permission_repository=PermissionRepository(real_session),
        role_permission_repository=RolePermissionRepository(real_session),
        audit_repository=AuditRepository(real_session),
    )


@pytest.fixture
def patient_service(real_session) -> PatientService:
    return PatientService(
        session=real_session,
        patient_repository=PatientRepository(real_session),
        audit_repository=AuditLogRepository(real_session),
    )


@pytest.fixture
def visit_service(real_session) -> VisitService:
    return VisitService(
        session=real_session,
        visit_repository=VisitRepository(real_session),
        audit_repository=AuditLogRepository(real_session),
    )


@pytest.fixture
def queue_service(real_session) -> QueueService:
    return QueueService(
        session=real_session,
        queue_entry_repository=QueueEntryRepository(real_session),
        audit_repository=AuditLogRepository(real_session),
    )


@pytest.fixture
def consultation_service(real_session, visit_service, queue_service) -> ConsultationService:
    return ConsultationService(
        session=real_session,
        consultation_repository=ConsultationRepository(real_session),
        visit_service=visit_service,
        queue_service=queue_service,
        audit_repository=AuditLogRepository(real_session),
    )


@pytest.fixture
def vitals_service(
    real_session, visit_service, queue_service, consultation_service
) -> VitalsService:
    return VitalsService(
        session=real_session,
        vitals_record_repository=VitalsRecordRepository(real_session),
        visit_service=visit_service,
        queue_service=queue_service,
        consultation_service=consultation_service,
        audit_repository=AuditLogRepository(real_session),
    )


@pytest.fixture
def billing_service(real_session, visit_service) -> BillingService:
    return BillingService(
        session=real_session,
        pending_billing_item_repository=PendingBillingItemRepository(real_session),
        invoice_repository=InvoiceRepository(real_session),
        invoice_line_item_repository=InvoiceLineItemRepository(real_session),
        visit_service=visit_service,
        audit_repository=AuditLogRepository(real_session),
    )


@pytest.fixture
def dashboard_service(visit_service, queue_service, billing_service) -> DashboardService:
    return DashboardService(
        visit_service=visit_service, queue_service=queue_service, billing_service=billing_service
    )


@pytest.fixture
def reception_service(
    real_session, patient_service, visit_service, queue_service
) -> ReceptionService:
    return ReceptionService(
        session=real_session,
        patient_service=patient_service,
        visit_service=visit_service,
        queue_service=queue_service,
        audit_repository=AuditLogRepository(real_session),
        reception_repository=ReceptionRepository(real_session),
    )


@pytest.fixture
def grant_permission(real_session):
    """Returns an async callable `grant(user, permission_code)` that
    gives `user` a permission by creating a throwaway Role (named with
    `TEST_ROLE_PREFIX` so `real_session`'s teardown deletes it), a
    RolePermission linking that role to `permission_code` (find-or-
    create — this suite only ever exercises a small, fixed set of real
    `PERMISSION_USERS_*` codes from app/modules/auth/constants.py, so
    reusing the same Permission row across every test that grants that
    code is correct, not test pollution: it is the same real permission
    a production deployment would eventually seed once, not fabricated
    per-test data), and a UserRole linking `user` to that role (cleaned
    up automatically when the user is deleted, via `ON DELETE CASCADE`).

    `RolePermission` is created via `RolePermissionRepository` (Phase 5
    Step 4) — its generic inherited `add()` is all this helper needs;
    Step 4 deliberately did not give it `assign`/`remove`-style methods,
    since granting a permission to a role generically is Phase 5 Step
    5's responsibility, not this test helper's."""

    async def _grant(user: User, permission_code: str) -> None:
        permission_repo = PermissionRepository(real_session)
        permission = await permission_repo.get_by_code(permission_code)
        if permission is None:
            permission = await permission_repo.add(
                Permission(
                    code=permission_code,
                    group=derive_permission_group(permission_code),
                    display_name=permission_code,
                )
            )
        role = await RoleRepository(real_session).add(
            Role(name=f"{TEST_ROLE_PREFIX}{uuid7()}", is_active=True)
        )
        await RolePermissionRepository(real_session).add(
            RolePermission(role_id=role.id, permission_id=permission.id)
        )
        await UserRoleRepository(real_session).add(UserRole(user_id=user.id, role_id=role.id))
        await real_session.commit()

    return _grant


@pytest.fixture
def auth_service(real_session, auth_settings, token_service, password_service) -> AuthService:
    return AuthService(
        session=real_session,
        settings=auth_settings,
        user_repository=UserRepository(real_session),
        refresh_token_repository=RefreshTokenRepository(real_session),
        login_session_repository=LoginSessionRepository(real_session),
        password_history_repository=PasswordHistoryRepository(real_session),
        audit_repository=AuditRepository(real_session),
        password_service=password_service,
        token_service=token_service,
    )


@pytest.fixture
async def api_client(jwt_key_registry, fake_redis):
    """An httpx client driving the real ASGI app end to end (real
    middleware, real routing, real dependency-injection graph, real
    Postgres, real business logic). Three dependencies are overridden via
    FastAPI's standard `dependency_overrides` mechanism:

    - `get_jwt_key_registry`/`get_redis_client`, for the same reason the
      `jwt_key_registry`/`fake_redis` fixtures exist.
    - `get_db`, with a `NullPool`-based engine scoped to this fixture
      instead of app/db/session.py's real module-level singleton engine.
      That singleton is built for a long-lived server process with one
      event loop; pytest-asyncio gives each test its own event loop, and
      reusing the singleton's pooled connections across tests reliably
      crashes with "Event loop is closed" the same way it did for
      `db_session` above — this changes only connection pooling, not the
      database, schema, or any query/business logic under test.
    """
    from app.main import app

    test_engine = create_async_engine(get_settings().database_url, poolclass=NullPool)

    async def _override_get_db():
        async with AsyncSession(test_engine, expire_on_commit=False) as session:
            yield session

    app.dependency_overrides[get_jwt_key_registry] = lambda: jwt_key_registry
    app.dependency_overrides[get_redis_client] = lambda: fake_redis
    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        await test_engine.dispose()
        engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
        try:
            async with AsyncSession(engine) as session:
                await session.execute(
                    text('DELETE FROM "user" WHERE email LIKE :pattern'),
                    {"pattern": f"{TEST_EMAIL_PREFIX}%@example.com"},
                )
                await session.execute(
                    text(
                        "DELETE FROM auth_audit_log "
                        "WHERE actor_user_id IS NULL AND target_user_id IS NULL"
                    )
                )
                await session.commit()
        finally:
            await engine.dispose()

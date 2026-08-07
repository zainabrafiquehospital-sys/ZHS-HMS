"""Production QA hardening (post Phase 5): a deliberate attempt to break
the system as a Senior QA/Security engineer, not merely re-confirm what
the per-module test suites already prove. Covers: expired/malformed/
foreign-key JWTs end-to-end, disabled/locked/deleted-user login
rejection, inactive-role/deleted-role/deleted-permission exclusion from
effective permission resolution, mass-assignment resistance, injection-
style search input, horizontal/vertical privilege escalation, and
idempotent/duplicate/concurrent HTTP requests.

Every test here exercises the real ASGI app end-to-end via `api_client`
unless a scenario genuinely requires service-layer access (e.g. reading
`AuthService.effective_permission_codes` directly, since no endpoint
exposes that set on its own)."""

import asyncio
from datetime import UTC, datetime, timedelta

import jwt as pyjwt
from uuid6 import uuid7

from app.core.config import get_settings
from app.core.jwt_keys import ALGORITHM
from app.modules.auth.constants import (
    PERMISSION_PERMISSIONS_CREATE,
    PERMISSION_ROLES_CREATE,
    PERMISSION_ROLES_MANAGE_PERMISSIONS,
    PERMISSION_USERS_MANAGE_STATUS,
    PERMISSION_USERS_READ,
    PERMISSION_USERS_UPDATE,
    TOKEN_TYPE_ACCESS,
)
from app.modules.auth.models import Permission, Role, User, UserRole, UserStatus
from app.modules.auth.password_service import PasswordService
from app.modules.auth.repository import (
    PermissionRepository,
    RoleRepository,
    UserRepository,
    UserRoleRepository,
)
from tests.conftest import TEST_PERMISSION_GROUP_PREFIX, TEST_ROLE_PREFIX, make_test_email

_PASSWORD = "Str0ng!Passw0rd#2026"


async def _create_and_login(api_client, real_session, suffix: str) -> tuple[User, str]:
    password_hash = await PasswordService().hash(_PASSWORD)
    email = make_test_email(suffix)
    user = await UserRepository(real_session).add(
        User(
            email=email,
            password_hash=password_hash,
            full_name="Hardening Test Actor",
            status=UserStatus.ACTIVE,
        )
    )
    await real_session.commit()
    login_resp = await api_client.post(
        "/api/v1/auth/login", json={"email": email, "password": _PASSWORD}
    )
    access_token = login_resp.json()["data"]["access_token"]
    return user, access_token


def _auth_header(access_token: str) -> dict:
    return {"Authorization": f"Bearer {access_token}"}


def _craft_token(jwt_key_registry, settings, *, claims_override: dict) -> str:
    signing_key = jwt_key_registry.signing_key()
    now = datetime.now(UTC)
    claims = {
        "sub": str(uuid7()),
        "roles": [],
        "jti": str(uuid7()),
        "iat": now,
        "exp": now + timedelta(minutes=15),
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "token_type": TOKEN_TYPE_ACCESS,
    }
    claims.update(claims_override)
    return pyjwt.encode(
        claims, signing_key.private_key, algorithm=ALGORITHM, headers={"kid": signing_key.kid}
    )


# ---------------------------------------------------------------------
# JWT edge cases
# ---------------------------------------------------------------------


async def test_expired_jwt_is_rejected_end_to_end(api_client, real_session, jwt_key_registry):
    user, _ = await _create_and_login(api_client, real_session, "hardening-expired-jwt")
    expired_token = _craft_token(
        jwt_key_registry,
        get_settings(),
        claims_override={
            "sub": str(user.id),
            "exp": datetime.now(UTC) - timedelta(minutes=10),
            "iat": datetime.now(UTC) - timedelta(minutes=25),
        },
    )

    resp = await api_client.get("/api/v1/auth/me", headers=_auth_header(expired_token))

    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "TOKEN_INVALID"


async def test_malformed_jwt_is_rejected_end_to_end(api_client):
    resp = await api_client.get(
        "/api/v1/auth/me", headers={"Authorization": "Bearer not-a-real-jwt-at-all"}
    )

    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "TOKEN_INVALID"


async def test_jwt_with_wrong_token_type_is_rejected(api_client, real_session, jwt_key_registry):
    """A refresh-typed token must never authenticate an access-protected
    endpoint, even if otherwise validly signed."""
    user, _ = await _create_and_login(api_client, real_session, "hardening-wrong-type-jwt")
    wrong_type_token = _craft_token(
        jwt_key_registry,
        get_settings(),
        claims_override={"sub": str(user.id), "token_type": "refresh"},
    )

    resp = await api_client.get("/api/v1/auth/me", headers=_auth_header(wrong_type_token))

    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "TOKEN_INVALID"


async def test_jwt_for_nonexistent_user_is_rejected(api_client, jwt_key_registry):
    """A structurally valid, correctly-signed token naming a `sub` that
    doesn't correspond to any real user (e.g. the account was hard-
    deleted, or the token is simply forged with a random UUID) must be
    rejected, not silently treated as some anonymous/default identity."""
    token = _craft_token(jwt_key_registry, get_settings(), claims_override={"sub": str(uuid7())})

    resp = await api_client.get("/api/v1/auth/me", headers=_auth_header(token))

    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "TOKEN_INVALID"


async def test_no_authorization_header_is_rejected(api_client):
    resp = await api_client.get("/api/v1/auth/me")

    assert resp.status_code == 401
    assert resp.headers.get("www-authenticate") == "Bearer"


# ---------------------------------------------------------------------
# Disabled / locked / deleted user login rejection
# ---------------------------------------------------------------------


async def test_soft_deleted_user_cannot_login(api_client, real_session):
    password_hash = await PasswordService().hash(_PASSWORD)
    email = make_test_email("hardening-deleted-user")
    user = await UserRepository(real_session).add(
        User(
            email=email,
            password_hash=password_hash,
            full_name="Soon Deleted",
            status=UserStatus.ACTIVE,
        )
    )
    await real_session.commit()
    await UserRepository(real_session).soft_delete(user, deleted_at=datetime.now(UTC))
    await real_session.commit()

    resp = await api_client.post("/api/v1/auth/login", json={"email": email, "password": _PASSWORD})

    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "INVALID_CREDENTIALS"


async def test_deactivated_user_cannot_login(api_client, real_session, grant_permission):
    actor, actor_token = await _create_and_login(api_client, real_session, "hardening-deact-actor")
    await grant_permission(actor, PERMISSION_USERS_MANAGE_STATUS)
    target, _ = await _create_and_login(api_client, real_session, "hardening-deact-target")

    deactivate_resp = await api_client.post(
        f"/api/v1/users/{target.id}/deactivate", headers=_auth_header(actor_token)
    )
    assert deactivate_resp.status_code == 200

    resp = await api_client.post(
        "/api/v1/auth/login", json={"email": target.email, "password": _PASSWORD}
    )

    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "ACCOUNT_SUSPENDED"


async def test_locked_user_cannot_login(api_client, real_session, grant_permission):
    actor, actor_token = await _create_and_login(api_client, real_session, "hardening-lock-actor")
    await grant_permission(actor, PERMISSION_USERS_MANAGE_STATUS)
    target, _ = await _create_and_login(api_client, real_session, "hardening-lock-target")

    lock_resp = await api_client.post(
        f"/api/v1/users/{target.id}/lock", headers=_auth_header(actor_token)
    )
    assert lock_resp.status_code == 200

    resp = await api_client.post(
        "/api/v1/auth/login", json={"email": target.email, "password": _PASSWORD}
    )

    assert resp.status_code == 423
    assert resp.json()["error"]["code"] == "ACCOUNT_LOCKED"


# ---------------------------------------------------------------------
# Inactive/deleted role and permission exclusion from effective access
# ---------------------------------------------------------------------


async def test_inactive_role_permissions_are_excluded_from_effective_access(
    api_client, real_session, role_service, user_service, auth_service, grant_permission
):
    admin = await auth_service.register(
        email=make_test_email("hardening-inactive-role-admin"),
        password=_PASSWORD,
        full_name="Admin",
    )
    target = await auth_service.register(
        email=make_test_email("hardening-inactive-role-target"),
        password=_PASSWORD,
        full_name="Target",
    )
    role = await role_service.create_role(
        actor=admin, name=f"{TEST_ROLE_PREFIX}{uuid7()}", description=None, parent_role_id=None
    )
    permission = await PermissionRepository(real_session).get_by_code(PERMISSION_USERS_READ)
    if permission is None:
        permission = await PermissionRepository(real_session).add(
            Permission(code=PERMISSION_USERS_READ, group="users", display_name="Read Users")
        )
        await real_session.commit()
    await role_service.assign_permissions(
        actor=admin, role_id=role.id, permission_ids=[permission.id]
    )
    await user_service.assign_roles(actor=admin, user_id=target.id, role_ids=[role.id])

    fetched = await UserRepository(real_session).get_by_id(target.id)
    assert PERMISSION_USERS_READ in auth_service.effective_permission_codes(fetched)

    await role_service.update_role(actor=admin, role_id=role.id, updates={"is_active": False})

    fetched_again = await UserRepository(real_session).get_by_id(target.id)
    assert PERMISSION_USERS_READ not in auth_service.effective_permission_codes(fetched_again)


async def test_soft_deleted_permission_is_excluded_even_if_grant_row_remains(
    real_session, role_service, user_service, auth_service
):
    """Direct regression test for the exact filter
    `AuthService.effective_permission_codes` applies: a permission that
    is itself soft-deleted must never count, even if its
    `role_permission` grant row was never explicitly revoked (mirrors
    the same "inert, not blocked" philosophy Phase 5 Step 5 applied to
    a soft-deleted *role* still holding grants)."""
    admin = await auth_service.register(
        email=make_test_email("hardening-deleted-perm-admin"), password=_PASSWORD, full_name="A"
    )
    target = await auth_service.register(
        email=make_test_email("hardening-deleted-perm-target"), password=_PASSWORD, full_name="T"
    )
    role = await role_service.create_role(
        actor=admin, name=f"{TEST_ROLE_PREFIX}{uuid7()}", description=None, parent_role_id=None
    )
    suffix = uuid7().hex
    permission = await PermissionRepository(real_session).add(
        Permission(
            code=f"{TEST_PERMISSION_GROUP_PREFIX}{suffix}:act{suffix}",
            group=f"{TEST_PERMISSION_GROUP_PREFIX}{suffix}",
            display_name="Throwaway",
        )
    )
    await real_session.commit()
    await role_service.assign_permissions(
        actor=admin, role_id=role.id, permission_ids=[permission.id]
    )
    await user_service.assign_roles(actor=admin, user_id=target.id, role_ids=[role.id])

    fetched = await UserRepository(real_session).get_by_id(target.id)
    assert permission.code in auth_service.effective_permission_codes(fetched)

    await PermissionRepository(real_session).soft_delete(permission, deleted_at=datetime.now(UTC))
    await real_session.commit()

    fetched_again = await UserRepository(real_session).get_by_id(target.id)
    assert permission.code not in auth_service.effective_permission_codes(fetched_again)


async def test_expired_role_assignment_is_excluded_from_effective_access(
    real_session, role_service, auth_service
):
    """`UserRole.expires_at` support already exists at the schema/
    resolution layer (Phase 3/4) even though no Step 2-5 endpoint
    exposes setting it — this proves the resolution side still honors
    it correctly for any row that does carry an expiry (e.g. seeded
    directly, or by a future endpoint)."""
    admin = await auth_service.register(
        email=make_test_email("hardening-expired-assignment-admin"),
        password=_PASSWORD,
        full_name="A",
    )
    target = await auth_service.register(
        email=make_test_email("hardening-expired-assignment-target"),
        password=_PASSWORD,
        full_name="T",
    )
    role = await role_service.create_role(
        actor=admin, name=f"{TEST_ROLE_PREFIX}{uuid7()}", description=None, parent_role_id=None
    )
    permission = await PermissionRepository(real_session).get_by_code(PERMISSION_USERS_READ)
    if permission is None:
        permission = await PermissionRepository(real_session).add(
            Permission(code=PERMISSION_USERS_READ, group="users", display_name="Read Users")
        )
        await real_session.commit()
    await role_service.assign_permissions(
        actor=admin, role_id=role.id, permission_ids=[permission.id]
    )
    await UserRoleRepository(real_session).add(
        UserRole(
            user_id=target.id,
            role_id=role.id,
            expires_at=datetime.now(UTC) - timedelta(minutes=1),
        )
    )
    await real_session.commit()

    fetched = await UserRepository(real_session).get_by_id(target.id)
    assert PERMISSION_USERS_READ not in auth_service.effective_permission_codes(fetched)


# ---------------------------------------------------------------------
# Mass assignment resistance
# ---------------------------------------------------------------------


async def test_create_role_ignores_is_system_role_in_request_body(
    api_client, real_session, grant_permission
):
    actor, token = await _create_and_login(api_client, real_session, "hardening-mass-role")
    await grant_permission(actor, PERMISSION_ROLES_CREATE)

    resp = await api_client.post(
        "/api/v1/roles",
        json={
            "name": f"{TEST_ROLE_PREFIX}{uuid7()}",
            "is_system_role": True,
            "id": str(uuid7()),
            "created_by": str(uuid7()),
        },
        headers=_auth_header(token),
    )

    assert resp.status_code == 201
    assert resp.json()["data"]["is_system_role"] is False


async def test_update_user_ignores_status_in_request_body(
    api_client, real_session, grant_permission
):
    actor, token = await _create_and_login(api_client, real_session, "hardening-mass-user-actor")
    await grant_permission(actor, PERMISSION_USERS_UPDATE)
    target, _ = await _create_and_login(api_client, real_session, "hardening-mass-user-target")

    resp = await api_client.patch(
        f"/api/v1/users/{target.id}",
        json={"full_name": "Renamed Safely", "status": "locked", "must_change_password": True},
        headers=_auth_header(token),
    )

    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["full_name"] == "Renamed Safely"
    assert body["status"] == "active"  # unchanged: status is not a field this endpoint accepts


async def test_create_permission_ignores_group_in_request_body(
    api_client, real_session, grant_permission
):
    actor, token = await _create_and_login(api_client, real_session, "hardening-mass-perm")
    await grant_permission(actor, PERMISSION_PERMISSIONS_CREATE)
    suffix = uuid7().hex
    code = f"{TEST_PERMISSION_GROUP_PREFIX}{suffix}:act{suffix}"

    resp = await api_client.post(
        "/api/v1/permissions",
        json={"code": code, "display_name": "Test", "group": "totally-different-group"},
        headers=_auth_header(token),
    )

    assert resp.status_code == 201
    assert resp.json()["data"]["group"] == f"{TEST_PERMISSION_GROUP_PREFIX}{suffix}"


# ---------------------------------------------------------------------
# Injection / adversarial input safety
# ---------------------------------------------------------------------


async def test_search_with_sql_injection_like_string_is_safe(
    api_client, real_session, grant_permission
):
    actor, token = await _create_and_login(api_client, real_session, "hardening-injection-actor")
    await grant_permission(actor, PERMISSION_USERS_READ)

    resp = await api_client.get(
        "/api/v1/users",
        params={"search": '\'; DROP TABLE "user"; --'},
        headers=_auth_header(token),
    )

    assert resp.status_code == 200
    assert resp.json()["data"] == []

    # Prove the table (and the actor's own row) really does still exist.
    still_there = await UserRepository(real_session).get_by_id(actor.id)
    assert still_there is not None


async def test_search_with_percent_and_underscore_wildcards_does_not_crash(
    api_client, real_session, grant_permission
):
    actor, token = await _create_and_login(api_client, real_session, "hardening-wildcard-actor")
    await grant_permission(actor, PERMISSION_USERS_READ)

    for pattern in ["%", "_", "%%%", "___"]:
        resp = await api_client.get(
            "/api/v1/users", params={"search": pattern}, headers=_auth_header(token)
        )
        assert resp.status_code == 200


async def test_invalid_sort_field_is_rejected_not_silently_ignored(
    api_client, real_session, grant_permission
):
    actor, token = await _create_and_login(api_client, real_session, "hardening-badsort-actor")
    await grant_permission(actor, PERMISSION_USERS_READ)

    resp = await api_client.get(
        "/api/v1/users",
        params={"sort_by": "password_hash"},
        headers=_auth_header(token),
    )

    assert resp.status_code == 422


# ---------------------------------------------------------------------
# Privilege escalation
# ---------------------------------------------------------------------


async def test_read_only_user_cannot_create_users(api_client, real_session, grant_permission):
    actor, token = await _create_and_login(api_client, real_session, "hardening-vertical-actor")
    await grant_permission(actor, PERMISSION_USERS_READ)

    resp = await api_client.post(
        "/api/v1/users",
        json={
            "email": make_test_email(f"hardening-vertical-victim-{uuid7().hex}"),
            "full_name": "X",
        },
        headers=_auth_header(token),
    )

    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "PERMISSION_DENIED"


async def test_role_permission_manager_cannot_create_new_permissions(
    api_client, real_session, grant_permission
):
    """Permission codes are siloed, not transitively implied:
    `roles:manage_permissions` lets an actor attach *existing*
    permissions to roles, but must never also imply
    `permissions:create` — a different, separately-granted capability."""
    actor, token = await _create_and_login(api_client, real_session, "hardening-siloed-actor")
    await grant_permission(actor, PERMISSION_ROLES_MANAGE_PERMISSIONS)

    resp = await api_client.post(
        "/api/v1/permissions",
        json={"code": f"{TEST_PERMISSION_GROUP_PREFIX}{uuid7().hex}:act", "display_name": "X"},
        headers=_auth_header(token),
    )

    assert resp.status_code == 403


async def test_user_with_no_permissions_cannot_self_grant_a_role(
    api_client, real_session, grant_permission
):
    """No endpoint lets a user assign a role to themselves without
    `users:manage_roles` — confirms there is no self-service escalation
    path even for a user acting on their own user_id."""
    actor, token = await _create_and_login(api_client, real_session, "hardening-self-grant-actor")
    role = await RoleRepository(real_session).add(Role(name=f"{TEST_ROLE_PREFIX}{uuid7()}"))
    await real_session.commit()

    resp = await api_client.post(
        f"/api/v1/users/{actor.id}/roles/assign",
        json={"role_ids": [str(role.id)]},
        headers=_auth_header(token),
    )

    assert resp.status_code == 403


async def test_user_cannot_read_other_users_admin_record_without_permission(
    api_client, real_session
):
    """No `users:read` permission at all: the target's admin record
    (GET /users/{id}) must be denied, not merely filtered."""
    _actor, token = await _create_and_login(api_client, real_session, "hardening-horiz-actor")
    victim, _ = await _create_and_login(api_client, real_session, "hardening-horiz-victim")

    resp = await api_client.get(f"/api/v1/users/{victim.id}", headers=_auth_header(token))

    assert resp.status_code == 403


# ---------------------------------------------------------------------
# Idempotency / duplicate / concurrent HTTP requests
# ---------------------------------------------------------------------


async def test_duplicate_http_permission_assign_requests_are_idempotent(
    api_client, real_session, grant_permission
):
    actor, token = await _create_and_login(api_client, real_session, "hardening-dup-http-actor")
    await grant_permission(actor, PERMISSION_ROLES_MANAGE_PERMISSIONS)
    role = await RoleRepository(real_session).add(Role(name=f"{TEST_ROLE_PREFIX}{uuid7()}"))
    permission = await PermissionRepository(real_session).get_by_code(PERMISSION_USERS_READ)
    if permission is None:
        permission = await PermissionRepository(real_session).add(
            Permission(code=PERMISSION_USERS_READ, group="users", display_name="Read Users")
        )
    await real_session.commit()

    payload = {"permission_ids": [str(permission.id)]}
    first = await api_client.post(
        f"/api/v1/roles/{role.id}/permissions/assign", json=payload, headers=_auth_header(token)
    )
    second = await api_client.post(
        f"/api/v1/roles/{role.id}/permissions/assign", json=payload, headers=_auth_header(token)
    )

    assert first.status_code == 200
    assert second.status_code == 200
    codes = [p["code"] for p in second.json()["data"]["permissions"]]
    assert codes.count(PERMISSION_USERS_READ) == 1


async def test_concurrent_http_create_role_same_name_is_handled_cleanly(
    api_client, real_session, grant_permission
):
    """End-to-end confirmation of the race-condition fix (see
    tests/test_race_conditions.py for the service-level regression
    tests) through the real ASGI app: `api_client`'s `get_db` override
    creates a fresh session per request (matching production), so two
    genuinely concurrent HTTP requests exercise the exact same race."""
    actor, token = await _create_and_login(api_client, real_session, "hardening-http-race-actor")
    await grant_permission(actor, PERMISSION_ROLES_CREATE)
    name = f"{TEST_ROLE_PREFIX}{uuid7()}"
    payload = {"name": name}

    responses = await asyncio.gather(
        api_client.post("/api/v1/roles", json=payload, headers=_auth_header(token)),
        api_client.post("/api/v1/roles", json=payload, headers=_auth_header(token)),
    )

    statuses = sorted(r.status_code for r in responses)
    assert statuses == [201, 409]
    conflict_resp = next(r for r in responses if r.status_code == 409)
    assert conflict_resp.json()["error"]["code"] == "ROLE_NAME_ALREADY_EXISTS"

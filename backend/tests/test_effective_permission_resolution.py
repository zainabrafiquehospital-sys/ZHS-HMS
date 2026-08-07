"""Cross-cutting integration test for Phase 5 Step 5's core requirement:
effective permission resolution must continue to work correctly through
the existing authorization layer once permissions are granted to roles
through the real API, not just via direct DB manipulation (the only way
`AuthService.effective_permission_codes` had ever been exercised before
this step existed). Spans four services (AuthService, UserService,
RoleService, PermissionService) and the real ASGI app — deliberately
its own file rather than folded into any single module's test file,
since it proves the seam between all of them, not any one module in
isolation.

`AuthService.effective_permission_codes` itself is not modified by this
step and is not re-tested here in isolation (see tests/test_auth_service.py
for that) — these tests exist to prove the *new* thing this step adds
(API-driven grants) flows correctly into that *already-tested*,
untouched resolution logic."""

from uuid6 import uuid7

from app.modules.auth.constants import PERMISSION_ROLES_MANAGE_PERMISSIONS, PERMISSION_USERS_READ
from app.modules.auth.models import Permission
from app.modules.auth.repository import PermissionRepository, UserRepository
from tests.conftest import TEST_ROLE_PREFIX, make_test_email

_PASSWORD = "Str0ng!Passw0rd#2026"


async def _get_or_create_permission(real_session, code: str, group: str) -> Permission:
    """Mirrors `grant_permission`'s find-or-create precedent exactly
    (tests/conftest.py) — `users:read` is real, reusable reference data
    across this whole suite, not per-test throwaway data, so it may
    already exist depending on test execution order."""
    repo = PermissionRepository(real_session)
    permission = await repo.get_by_code(code)
    if permission is None:
        permission = await repo.add(Permission(code=code, group=group, display_name=code))
        await real_session.commit()
    return permission


async def test_granting_and_revoking_a_permission_through_the_api_takes_effect_immediately(
    api_client, real_session, auth_service, user_service, role_service, grant_permission
):
    """Full round trip: create a permission-less role -> assign it to a
    user -> prove the user is denied a permission-gated endpoint ->
    grant that permission to the role through the real Step 5 endpoint
    -> prove the SAME already-issued access token now passes (proving
    permissions are resolved fresh per request from the database, never
    baked into the JWT itself — only role *names* are, per
    TokenService.create_access_token) -> revoke it -> prove access is
    denied again."""
    admin = await auth_service.register(
        email=make_test_email("effective-perm-admin"), password=_PASSWORD, full_name="Admin"
    )
    await grant_permission(admin, PERMISSION_ROLES_MANAGE_PERMISSIONS)
    admin_login = await api_client.post(
        "/api/v1/auth/login", json={"email": admin.email, "password": _PASSWORD}
    )
    admin_headers = {"Authorization": f"Bearer {admin_login.json()['data']['access_token']}"}

    target = await auth_service.register(
        email=make_test_email("effective-perm-target"), password=_PASSWORD, full_name="Target"
    )
    role = await role_service.create_role(
        actor=admin, name=f"{TEST_ROLE_PREFIX}{uuid7()}", description=None, parent_role_id=None
    )
    await user_service.assign_roles(actor=admin, user_id=target.id, role_ids=[role.id])

    target_login = await api_client.post(
        "/api/v1/auth/login", json={"email": target.email, "password": _PASSWORD}
    )
    target_headers = {"Authorization": f"Bearer {target_login.json()['data']['access_token']}"}

    # Before any grant: the role has no permissions, so the user cannot
    # list users (GET /api/v1/users requires users:read).
    denied = await api_client.get("/api/v1/users", headers=target_headers)
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "PERMISSION_DENIED"

    users_read = await _get_or_create_permission(real_session, PERMISSION_USERS_READ, "users")

    grant_resp = await api_client.post(
        f"/api/v1/roles/{role.id}/permissions/assign",
        json={"permission_ids": [str(users_read.id)]},
        headers=admin_headers,
    )
    assert grant_resp.status_code == 200

    # Same access token, no re-login required.
    allowed = await api_client.get("/api/v1/users", headers=target_headers)
    assert allowed.status_code == 200

    revoke_resp = await api_client.post(
        f"/api/v1/roles/{role.id}/permissions/remove",
        json={"permission_ids": [str(users_read.id)]},
        headers=admin_headers,
    )
    assert revoke_resp.status_code == 200

    denied_again = await api_client.get("/api/v1/users", headers=target_headers)
    assert denied_again.status_code == 403


async def test_effective_permission_codes_reflects_api_driven_grants_directly(
    auth_service, user_service, role_service, real_session
):
    """Same proof, at the service layer rather than through HTTP: after
    granting a permission to a role via `RoleService.assign_permissions`
    and assigning that role to a user via `UserService.assign_roles`,
    `AuthService.effective_permission_codes` — completely untouched by
    this step — correctly includes the granted permission's code, and
    correctly stops including it once revoked."""
    admin = await auth_service.register(
        email=make_test_email("effective-perm-codes-admin"), password=_PASSWORD, full_name="Admin"
    )
    target = await auth_service.register(
        email=make_test_email("effective-perm-codes-target"),
        password=_PASSWORD,
        full_name="Target",
    )
    role = await role_service.create_role(
        actor=admin, name=f"{TEST_ROLE_PREFIX}{uuid7()}", description=None, parent_role_id=None
    )
    permission = await _get_or_create_permission(real_session, PERMISSION_USERS_READ, "users")
    await role_service.assign_permissions(
        actor=admin, role_id=role.id, permission_ids=[permission.id]
    )
    await user_service.assign_roles(actor=admin, user_id=target.id, role_ids=[role.id])

    fetched_target = await UserRepository(real_session).get_by_id(target.id)
    codes_after_grant = auth_service.effective_permission_codes(fetched_target)
    assert PERMISSION_USERS_READ in codes_after_grant

    await role_service.remove_permissions(
        actor=admin, role_id=role.id, permission_ids=[permission.id]
    )

    fetched_target_again = await UserRepository(real_session).get_by_id(target.id)
    codes_after_revoke = auth_service.effective_permission_codes(fetched_target_again)
    assert PERMISSION_USERS_READ not in codes_after_revoke

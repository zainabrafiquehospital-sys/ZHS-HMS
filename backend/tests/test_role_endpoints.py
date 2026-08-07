"""Full end-to-end HTTP tests for the Role Management module: real ASGI
app, real routing, real dependency-injection graph, real Postgres — same
style as tests/test_user_endpoints.py, using the `grant_permission`
fixture for genuine RBAC state rather than bypassing authorization."""

from uuid6 import uuid7

from app.modules.auth.constants import (
    PERMISSION_ROLES_CREATE,
    PERMISSION_ROLES_DELETE,
    PERMISSION_ROLES_MANAGE_PERMISSIONS,
    PERMISSION_ROLES_READ,
    PERMISSION_ROLES_UPDATE,
    PERMISSION_USERS_MANAGE_ROLES,
)
from app.modules.auth.models import Permission, Role, User, UserStatus
from app.modules.auth.password_service import PasswordService
from app.modules.auth.repository import PermissionRepository, RoleRepository, UserRepository
from tests.conftest import TEST_PERMISSION_GROUP_PREFIX, TEST_ROLE_PREFIX, make_test_email

_PASSWORD = "Str0ng!Passw0rd#2026"


async def _create_and_login(api_client, real_session, suffix: str) -> tuple[User, str]:
    password_hash = await PasswordService().hash(_PASSWORD)
    email = make_test_email(suffix)
    user = await UserRepository(real_session).add(
        User(
            email=email,
            password_hash=password_hash,
            full_name="Role Endpoint Actor",
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


async def _make_role(real_session, *, is_system_role: bool = False) -> Role:
    role = await RoleRepository(real_session).add(
        Role(name=f"{TEST_ROLE_PREFIX}{uuid7()}", is_system_role=is_system_role)
    )
    await real_session.commit()
    return role


async def _make_permission(real_session) -> Permission:
    suffix = uuid7().hex
    code = f"{TEST_PERMISSION_GROUP_PREFIX}{suffix}:act{suffix}"
    permission = await PermissionRepository(real_session).add(
        Permission(code=code, group=code.split(":", 1)[0], display_name="Endpoint Test Permission")
    )
    await real_session.commit()
    return permission


# ---------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------


async def test_create_role_requires_authentication(api_client):
    resp = await api_client.post("/api/v1/roles", json={"name": f"{TEST_ROLE_PREFIX}{uuid7()}"})

    assert resp.status_code == 401


async def test_create_role_without_permission_is_forbidden(api_client, real_session):
    _actor, access_token = await _create_and_login(api_client, real_session, "no-perm-role")

    resp = await api_client.post(
        "/api/v1/roles",
        json={"name": f"{TEST_ROLE_PREFIX}{uuid7()}"},
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "PERMISSION_DENIED"


# ---------------------------------------------------------------------
# Create / Get / List / Update / Delete
# ---------------------------------------------------------------------


async def test_create_role_success(api_client, real_session, grant_permission):
    actor, access_token = await _create_and_login(api_client, real_session, "create-role-actor")
    await grant_permission(actor, PERMISSION_ROLES_CREATE)
    name = f"{TEST_ROLE_PREFIX}{uuid7()}"

    resp = await api_client.post(
        "/api/v1/roles",
        json={"name": name, "description": "Created via HTTP"},
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 201
    body = resp.json()["data"]
    assert body["name"] == name
    assert body["is_system_role"] is False
    assert body["permissions"] == []


async def test_create_role_duplicate_name_returns_409(api_client, real_session, grant_permission):
    actor, access_token = await _create_and_login(api_client, real_session, "create-role-dup")
    await grant_permission(actor, PERMISSION_ROLES_CREATE)
    name = f"{TEST_ROLE_PREFIX}{uuid7()}"
    await api_client.post("/api/v1/roles", json={"name": name}, headers=_auth_header(access_token))

    resp = await api_client.post(
        "/api/v1/roles", json={"name": name}, headers=_auth_header(access_token)
    )

    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "ROLE_NAME_ALREADY_EXISTS"


async def test_list_roles_returns_pagination_meta(api_client, real_session, grant_permission):
    actor, access_token = await _create_and_login(api_client, real_session, "list-roles-actor")
    await grant_permission(actor, PERMISSION_ROLES_READ)
    await grant_permission(actor, PERMISSION_ROLES_CREATE)
    name = f"{TEST_ROLE_PREFIX}{uuid7()}"
    await api_client.post("/api/v1/roles", json={"name": name}, headers=_auth_header(access_token))

    resp = await api_client.get(
        "/api/v1/roles",
        params={"page": 1, "page_size": 5, "search": name},
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["meta"]["page"] == 1
    assert body["meta"]["total"] == 1
    assert body["data"][0]["name"] == name


async def test_get_role_returns_404_for_unknown_id(api_client, real_session, grant_permission):
    actor, access_token = await _create_and_login(api_client, real_session, "get-role-404")
    await grant_permission(actor, PERMISSION_ROLES_READ)

    resp = await api_client.get(f"/api/v1/roles/{uuid7()}", headers=_auth_header(access_token))

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "ROLE_NOT_FOUND"


async def test_update_role_changes_description(api_client, real_session, grant_permission):
    actor, access_token = await _create_and_login(api_client, real_session, "update-role-actor")
    await grant_permission(actor, PERMISSION_ROLES_UPDATE)
    role = await _make_role(real_session)

    resp = await api_client.patch(
        f"/api/v1/roles/{role.id}",
        json={"description": "Updated via API"},
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 200
    assert resp.json()["data"]["description"] == "Updated via API"


async def test_update_role_invalid_parent_returns_422(api_client, real_session, grant_permission):
    actor, access_token = await _create_and_login(
        api_client, real_session, "update-role-bad-parent"
    )
    await grant_permission(actor, PERMISSION_ROLES_UPDATE)
    role = await _make_role(real_session)

    resp = await api_client.patch(
        f"/api/v1/roles/{role.id}",
        json={"parent_role_id": str(role.id)},
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "INVALID_PARENT_ROLE"


async def test_delete_role_success(api_client, real_session, grant_permission):
    actor, access_token = await _create_and_login(api_client, real_session, "delete-role-actor")
    await grant_permission(actor, PERMISSION_ROLES_DELETE)
    await grant_permission(actor, PERMISSION_ROLES_READ)
    role = await _make_role(real_session)

    resp = await api_client.delete(f"/api/v1/roles/{role.id}", headers=_auth_header(access_token))
    assert resp.status_code == 200

    get_resp = await api_client.get(f"/api/v1/roles/{role.id}", headers=_auth_header(access_token))
    assert get_resp.status_code == 404


async def test_delete_system_role_returns_422(api_client, real_session, grant_permission):
    actor, access_token = await _create_and_login(api_client, real_session, "delete-system-role")
    await grant_permission(actor, PERMISSION_ROLES_DELETE)
    role = await _make_role(real_session, is_system_role=True)

    resp = await api_client.delete(f"/api/v1/roles/{role.id}", headers=_auth_header(access_token))

    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "SYSTEM_ROLE_PROTECTED"


async def test_delete_role_in_use_returns_409(api_client, real_session, grant_permission):
    actor, access_token = await _create_and_login(api_client, real_session, "delete-role-in-use")
    await grant_permission(actor, PERMISSION_ROLES_DELETE)
    await grant_permission(actor, PERMISSION_USERS_MANAGE_ROLES)
    target, _ = await _create_and_login(api_client, real_session, "delete-role-in-use-target")
    role = await _make_role(real_session)
    await api_client.post(
        f"/api/v1/users/{target.id}/roles/assign",
        json={"role_ids": [str(role.id)]},
        headers=_auth_header(access_token),
    )

    resp = await api_client.delete(f"/api/v1/roles/{role.id}", headers=_auth_header(access_token))

    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "ROLE_IN_USE"


# ---------------------------------------------------------------------
# Role <-> Permission Assignment (Phase 5 Step 5)
# ---------------------------------------------------------------------


async def test_assign_permissions_requires_authentication(api_client, real_session):
    role = await _make_role(real_session)

    resp = await api_client.post(
        f"/api/v1/roles/{role.id}/permissions/assign", json={"permission_ids": [str(uuid7())]}
    )

    assert resp.status_code == 401


async def test_assign_permissions_without_permission_is_forbidden(api_client, real_session):
    _actor, access_token = await _create_and_login(api_client, real_session, "no-perm-assign-perm")
    role = await _make_role(real_session)

    resp = await api_client.post(
        f"/api/v1/roles/{role.id}/permissions/assign",
        json={"permission_ids": [str(uuid7())]},
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "PERMISSION_DENIED"


async def test_assign_permissions_success(api_client, real_session, grant_permission):
    actor, access_token = await _create_and_login(api_client, real_session, "assign-perm-actor")
    await grant_permission(actor, PERMISSION_ROLES_MANAGE_PERMISSIONS)
    role = await _make_role(real_session)
    permission = await _make_permission(real_session)

    resp = await api_client.post(
        f"/api/v1/roles/{role.id}/permissions/assign",
        json={"permission_ids": [str(permission.id)]},
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 200
    codes = [p["code"] for p in resp.json()["data"]["permissions"]]
    assert codes == [permission.code]


async def test_assign_permissions_unknown_permission_returns_404(
    api_client, real_session, grant_permission
):
    actor, access_token = await _create_and_login(api_client, real_session, "assign-perm-404")
    await grant_permission(actor, PERMISSION_ROLES_MANAGE_PERMISSIONS)
    role = await _make_role(real_session)

    resp = await api_client.post(
        f"/api/v1/roles/{role.id}/permissions/assign",
        json={"permission_ids": [str(uuid7())]},
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "PERMISSION_NOT_FOUND"


async def test_remove_permissions_success(api_client, real_session, grant_permission):
    actor, access_token = await _create_and_login(api_client, real_session, "remove-perm-actor")
    await grant_permission(actor, PERMISSION_ROLES_MANAGE_PERMISSIONS)
    role = await _make_role(real_session)
    permission = await _make_permission(real_session)
    await api_client.post(
        f"/api/v1/roles/{role.id}/permissions/assign",
        json={"permission_ids": [str(permission.id)]},
        headers=_auth_header(access_token),
    )

    resp = await api_client.post(
        f"/api/v1/roles/{role.id}/permissions/remove",
        json={"permission_ids": [str(permission.id)]},
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 200
    assert resp.json()["data"]["permissions"] == []


async def test_replace_permissions_success(api_client, real_session, grant_permission):
    actor, access_token = await _create_and_login(api_client, real_session, "replace-perm-actor")
    await grant_permission(actor, PERMISSION_ROLES_MANAGE_PERMISSIONS)
    role = await _make_role(real_session)
    permission_a = await _make_permission(real_session)
    permission_b = await _make_permission(real_session)
    await api_client.post(
        f"/api/v1/roles/{role.id}/permissions/assign",
        json={"permission_ids": [str(permission_a.id)]},
        headers=_auth_header(access_token),
    )

    resp = await api_client.put(
        f"/api/v1/roles/{role.id}/permissions",
        json={"permission_ids": [str(permission_b.id)]},
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 200
    codes = [p["code"] for p in resp.json()["data"]["permissions"]]
    assert codes == [permission_b.code]

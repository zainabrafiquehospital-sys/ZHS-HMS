"""Full end-to-end HTTP tests for the Permission Management module: real
ASGI app, real routing, real dependency-injection graph, real Postgres —
same style as tests/test_role_endpoints.py, using the `grant_permission`
fixture for genuine RBAC state rather than bypassing authorization."""

from uuid6 import uuid7

from app.modules.auth.constants import (
    PERMISSION_PERMISSIONS_CREATE,
    PERMISSION_PERMISSIONS_DELETE,
    PERMISSION_PERMISSIONS_READ,
    PERMISSION_PERMISSIONS_UPDATE,
)
from app.modules.auth.models import Permission, Role, RolePermission, User, UserStatus
from app.modules.auth.password_service import PasswordService
from app.modules.auth.repository import (
    PermissionRepository,
    RolePermissionRepository,
    RoleRepository,
    UserRepository,
)
from tests.conftest import TEST_PERMISSION_GROUP_PREFIX, TEST_ROLE_PREFIX, make_test_email

_PASSWORD = "Str0ng!Passw0rd#2026"


def _unique_code() -> str:
    suffix = uuid7().hex
    return f"{TEST_PERMISSION_GROUP_PREFIX}{suffix}:act{suffix}"


async def _create_and_login(api_client, real_session, suffix: str) -> tuple[User, str]:
    password_hash = await PasswordService().hash(_PASSWORD)
    email = make_test_email(suffix)
    user = await UserRepository(real_session).add(
        User(
            email=email,
            password_hash=password_hash,
            full_name="Permission Endpoint Actor",
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


async def _make_permission(real_session, *, code: str | None = None) -> Permission:
    code = code or _unique_code()
    permission = await PermissionRepository(real_session).add(
        Permission(
            code=code,
            group=code.split(":", 1)[0],
            display_name="Endpoint Test Permission",
        )
    )
    await real_session.commit()
    return permission


# ---------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------


async def test_create_permission_requires_authentication(api_client):
    resp = await api_client.post(
        "/api/v1/permissions",
        json={"code": _unique_code(), "display_name": "No Auth"},
    )

    assert resp.status_code == 401


async def test_create_permission_without_permission_is_forbidden(api_client, real_session):
    _actor, access_token = await _create_and_login(api_client, real_session, "no-perm-perm")

    resp = await api_client.post(
        "/api/v1/permissions",
        json={"code": _unique_code(), "display_name": "Forbidden"},
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "PERMISSION_DENIED"


# ---------------------------------------------------------------------
# Create / Get / List / Update / Delete
# ---------------------------------------------------------------------


async def test_create_permission_success(api_client, real_session, grant_permission):
    actor, access_token = await _create_and_login(api_client, real_session, "create-perm-actor")
    await grant_permission(actor, PERMISSION_PERMISSIONS_CREATE)
    code = _unique_code()

    resp = await api_client.post(
        "/api/v1/permissions",
        json={"code": code, "display_name": "Create Patient", "description": "Allows creating."},
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 201
    body = resp.json()["data"]
    assert body["code"] == code
    assert body["group"] == code.split(":", 1)[0]
    assert body["display_name"] == "Create Patient"


async def test_create_permission_duplicate_code_returns_409(
    api_client, real_session, grant_permission
):
    actor, access_token = await _create_and_login(api_client, real_session, "create-perm-dup")
    await grant_permission(actor, PERMISSION_PERMISSIONS_CREATE)
    code = _unique_code()
    payload = {"code": code, "display_name": "First"}
    await api_client.post("/api/v1/permissions", json=payload, headers=_auth_header(access_token))

    resp = await api_client.post(
        "/api/v1/permissions", json=payload, headers=_auth_header(access_token)
    )

    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "PERMISSION_CODE_ALREADY_EXISTS"


async def test_create_permission_malformed_code_returns_422(
    api_client, real_session, grant_permission
):
    actor, access_token = await _create_and_login(api_client, real_session, "create-perm-bad")
    await grant_permission(actor, PERMISSION_PERMISSIONS_CREATE)

    resp = await api_client.post(
        "/api/v1/permissions",
        json={"code": "NotValid", "display_name": "Bad"},
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 422


async def test_list_permissions_returns_pagination_meta(api_client, real_session, grant_permission):
    actor, access_token = await _create_and_login(api_client, real_session, "list-perm-actor")
    await grant_permission(actor, PERMISSION_PERMISSIONS_READ)
    await grant_permission(actor, PERMISSION_PERMISSIONS_CREATE)
    code = _unique_code()
    await api_client.post(
        "/api/v1/permissions",
        json={"code": code, "display_name": "Listable"},
        headers=_auth_header(access_token),
    )

    resp = await api_client.get(
        "/api/v1/permissions",
        params={"page": 1, "page_size": 5, "search": code},
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["meta"]["page"] == 1
    assert body["meta"]["total"] == 1
    assert body["data"][0]["code"] == code


async def test_get_permission_returns_404_for_unknown_id(
    api_client, real_session, grant_permission
):
    actor, access_token = await _create_and_login(api_client, real_session, "get-perm-404")
    await grant_permission(actor, PERMISSION_PERMISSIONS_READ)

    resp = await api_client.get(
        f"/api/v1/permissions/{uuid7()}", headers=_auth_header(access_token)
    )

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "PERMISSION_NOT_FOUND"


async def test_update_permission_changes_display_name(api_client, real_session, grant_permission):
    actor, access_token = await _create_and_login(api_client, real_session, "update-perm-actor")
    await grant_permission(actor, PERMISSION_PERMISSIONS_UPDATE)
    permission = await _make_permission(real_session)

    resp = await api_client.patch(
        f"/api/v1/permissions/{permission.id}",
        json={"display_name": "Updated Display Name"},
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 200
    assert resp.json()["data"]["display_name"] == "Updated Display Name"


async def test_update_permission_ignores_code_in_body(api_client, real_session, grant_permission):
    actor, access_token = await _create_and_login(api_client, real_session, "update-perm-code")
    await grant_permission(actor, PERMISSION_PERMISSIONS_UPDATE)
    permission = await _make_permission(real_session)
    original_code = permission.code

    resp = await api_client.patch(
        f"/api/v1/permissions/{permission.id}",
        json={"code": "attempted:rename", "display_name": "Still Updated"},
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 200
    assert resp.json()["data"]["code"] == original_code
    assert resp.json()["data"]["display_name"] == "Still Updated"


async def test_delete_permission_success(api_client, real_session, grant_permission):
    actor, access_token = await _create_and_login(api_client, real_session, "delete-perm-actor")
    await grant_permission(actor, PERMISSION_PERMISSIONS_DELETE)
    await grant_permission(actor, PERMISSION_PERMISSIONS_READ)
    permission = await _make_permission(real_session)

    resp = await api_client.delete(
        f"/api/v1/permissions/{permission.id}", headers=_auth_header(access_token)
    )
    assert resp.status_code == 200

    get_resp = await api_client.get(
        f"/api/v1/permissions/{permission.id}", headers=_auth_header(access_token)
    )
    assert get_resp.status_code == 404


async def test_delete_permission_in_use_returns_409(api_client, real_session, grant_permission):
    actor, access_token = await _create_and_login(api_client, real_session, "delete-perm-in-use")
    await grant_permission(actor, PERMISSION_PERMISSIONS_DELETE)
    permission = await _make_permission(real_session)
    role = await RoleRepository(real_session).add(
        Role(name=f"{TEST_ROLE_PREFIX}{uuid7()}", is_active=True)
    )
    await RolePermissionRepository(real_session).add(
        RolePermission(role_id=role.id, permission_id=permission.id)
    )
    await real_session.commit()

    resp = await api_client.delete(
        f"/api/v1/permissions/{permission.id}", headers=_auth_header(access_token)
    )

    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "PERMISSION_IN_USE"


# ---------------------------------------------------------------------
# Role <-> Permission Assignment (Phase 5 Step 5) — read-only inverse
# ---------------------------------------------------------------------


async def test_get_roles_for_permission_requires_authentication(api_client, real_session):
    permission = await _make_permission(real_session)

    resp = await api_client.get(f"/api/v1/permissions/{permission.id}/roles")

    assert resp.status_code == 401


async def test_get_roles_for_permission_returns_granted_roles(
    api_client, real_session, grant_permission
):
    actor, access_token = await _create_and_login(api_client, real_session, "roles-for-perm")
    await grant_permission(actor, PERMISSION_PERMISSIONS_READ)
    permission = await _make_permission(real_session)
    role = await RoleRepository(real_session).add(
        Role(name=f"{TEST_ROLE_PREFIX}{uuid7()}", is_active=True)
    )
    await RolePermissionRepository(real_session).add(
        RolePermission(role_id=role.id, permission_id=permission.id)
    )
    await real_session.commit()

    resp = await api_client.get(
        f"/api/v1/permissions/{permission.id}/roles", headers=_auth_header(access_token)
    )

    assert resp.status_code == 200
    role_ids = [r["id"] for r in resp.json()["data"]]
    assert role_ids == [str(role.id)]


async def test_get_roles_for_permission_returns_404_for_unknown_id(
    api_client, real_session, grant_permission
):
    actor, access_token = await _create_and_login(api_client, real_session, "roles-for-perm-404")
    await grant_permission(actor, PERMISSION_PERMISSIONS_READ)

    resp = await api_client.get(
        f"/api/v1/permissions/{uuid7()}/roles", headers=_auth_header(access_token)
    )

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "PERMISSION_NOT_FOUND"

"""Full end-to-end HTTP tests for the User Management module: real ASGI
app, real routing, real dependency-injection graph, real Postgres — the
same style as tests/test_auth_endpoints.py. `grant_permission` (see
conftest.py) is used to set up realistic RBAC state rather than bypassing
authorization in these tests, since "Only authorized roles may manage
users" is itself part of what this module must prove."""

from uuid6 import uuid7

from app.modules.auth.constants import (
    PERMISSION_USERS_CREATE,
    PERMISSION_USERS_DELETE,
    PERMISSION_USERS_MANAGE_PASSWORD,
    PERMISSION_USERS_MANAGE_ROLES,
    PERMISSION_USERS_MANAGE_STATUS,
    PERMISSION_USERS_READ,
    PERMISSION_USERS_UPDATE,
)
from app.modules.auth.models import Role, User, UserStatus
from app.modules.auth.password_service import PasswordService
from app.modules.auth.repository import RoleRepository, UserRepository
from tests.conftest import TEST_ROLE_PREFIX, make_test_email

_PASSWORD = "Str0ng!Passw0rd#2026"


async def _create_and_login(api_client, real_session, suffix: str) -> tuple[User, str]:
    password_hash = await PasswordService().hash(_PASSWORD)
    email = make_test_email(suffix)
    user = await UserRepository(real_session).add(
        User(
            email=email,
            password_hash=password_hash,
            full_name="Endpoint Actor",
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


async def _make_role(real_session, *, is_active: bool = True) -> Role:
    role = await RoleRepository(real_session).add(
        Role(name=f"{TEST_ROLE_PREFIX}{uuid7()}", is_active=is_active)
    )
    # `api_client` reads through a separate connection/session from
    # `real_session` (see api_client's docstring) — an uncommitted
    # flush() is invisible across that boundary, unlike within a single
    # session, so this must commit for the role to be visible to the
    # HTTP request the test makes next.
    await real_session.commit()
    return role


# ---------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------


async def test_create_user_requires_authentication(api_client):
    resp = await api_client.post(
        "/api/v1/users",
        json={"email": make_test_email("no-auth"), "full_name": "Nobody"},
    )

    assert resp.status_code == 401


async def test_create_user_without_permission_is_forbidden(api_client, real_session):
    _actor, access_token = await _create_and_login(api_client, real_session, "no-perm-create")

    resp = await api_client.post(
        "/api/v1/users",
        json={"email": make_test_email("no-perm-target"), "full_name": "Target"},
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "PERMISSION_DENIED"


# ---------------------------------------------------------------------
# Create / Get / List / Update / Delete
# ---------------------------------------------------------------------


async def test_create_user_success_returns_temporary_password(
    api_client, real_session, grant_permission
):
    actor, access_token = await _create_and_login(api_client, real_session, "create-actor")
    await grant_permission(actor, PERMISSION_USERS_CREATE)
    email = make_test_email("create-target")

    resp = await api_client.post(
        "/api/v1/users",
        json={"email": email, "full_name": "Created User", "phone_number": "+1 555 0700"},
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 201
    body = resp.json()["data"]
    assert body["user"]["email"] == email
    assert body["user"]["must_change_password"] is True
    assert len(body["temporary_password"]) >= 12

    login_resp = await api_client.post(
        "/api/v1/auth/login", json={"email": email, "password": body["temporary_password"]}
    )
    assert login_resp.status_code == 200


async def test_create_user_duplicate_email_returns_409(api_client, real_session, grant_permission):
    actor, access_token = await _create_and_login(api_client, real_session, "create-dup-actor")
    await grant_permission(actor, PERMISSION_USERS_CREATE)
    email = make_test_email("create-dup-target")
    payload = {"email": email, "full_name": "First"}
    await api_client.post("/api/v1/users", json=payload, headers=_auth_header(access_token))

    resp = await api_client.post("/api/v1/users", json=payload, headers=_auth_header(access_token))

    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "EMAIL_ALREADY_REGISTERED"


async def test_list_users_returns_pagination_meta(api_client, real_session, grant_permission):
    actor, access_token = await _create_and_login(api_client, real_session, "list-actor")
    await grant_permission(actor, PERMISSION_USERS_READ)

    resp = await api_client.get(
        "/api/v1/users",
        params={"page": 1, "page_size": 5, "search": "list-actor"},
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["meta"]["page"] == 1
    assert body["meta"]["page_size"] == 5
    assert body["meta"]["total"] >= 1
    assert any(u["id"] == str(actor.id) for u in body["data"])


async def test_get_user_returns_404_for_unknown_id(api_client, real_session, grant_permission):
    actor, access_token = await _create_and_login(api_client, real_session, "get-404-actor")
    await grant_permission(actor, PERMISSION_USERS_READ)

    resp = await api_client.get(f"/api/v1/users/{uuid7()}", headers=_auth_header(access_token))

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "USER_NOT_FOUND"


async def test_update_user_changes_full_name(api_client, real_session, grant_permission):
    actor, access_token = await _create_and_login(api_client, real_session, "update-actor")
    await grant_permission(actor, PERMISSION_USERS_UPDATE)
    target, _ = await _create_and_login(api_client, real_session, "update-target")

    resp = await api_client.patch(
        f"/api/v1/users/{target.id}",
        json={"full_name": "Updated Via API"},
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 200
    assert resp.json()["data"]["full_name"] == "Updated Via API"


async def test_update_own_profile_requires_only_authentication(api_client, real_session):
    _user, access_token = await _create_and_login(api_client, real_session, "own-profile")

    resp = await api_client.patch(
        "/api/v1/users/me",
        json={"full_name": "Self Updated"},
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 200
    assert resp.json()["data"]["full_name"] == "Self Updated"


async def test_delete_user_success(api_client, real_session, grant_permission):
    actor, access_token = await _create_and_login(api_client, real_session, "delete-actor")
    await grant_permission(actor, PERMISSION_USERS_DELETE)
    await grant_permission(actor, PERMISSION_USERS_READ)
    target, _ = await _create_and_login(api_client, real_session, "delete-target")

    resp = await api_client.delete(f"/api/v1/users/{target.id}", headers=_auth_header(access_token))
    assert resp.status_code == 200

    get_resp = await api_client.get(
        f"/api/v1/users/{target.id}", headers=_auth_header(access_token)
    )
    assert get_resp.status_code == 404


async def test_delete_self_is_rejected(api_client, real_session, grant_permission):
    actor, access_token = await _create_and_login(api_client, real_session, "delete-self")
    await grant_permission(actor, PERMISSION_USERS_DELETE)

    resp = await api_client.delete(f"/api/v1/users/{actor.id}", headers=_auth_header(access_token))

    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "SELF_ACTION_NOT_ALLOWED"


# ---------------------------------------------------------------------
# Status: Activate / Deactivate / Lock / Unlock
# ---------------------------------------------------------------------


async def test_lock_then_unlock_via_http(api_client, real_session, grant_permission):
    actor, access_token = await _create_and_login(api_client, real_session, "lock-http-actor")
    await grant_permission(actor, PERMISSION_USERS_MANAGE_STATUS)
    target, _ = await _create_and_login(api_client, real_session, "lock-http-target")

    lock_resp = await api_client.post(
        f"/api/v1/users/{target.id}/lock", headers=_auth_header(access_token)
    )
    assert lock_resp.status_code == 200
    assert lock_resp.json()["data"]["status"] == "locked"

    unlock_resp = await api_client.post(
        f"/api/v1/users/{target.id}/unlock", headers=_auth_header(access_token)
    )
    assert unlock_resp.status_code == 200
    assert unlock_resp.json()["data"]["status"] == "active"


async def test_deactivate_twice_returns_422(api_client, real_session, grant_permission):
    actor, access_token = await _create_and_login(api_client, real_session, "deactivate-actor")
    await grant_permission(actor, PERMISSION_USERS_MANAGE_STATUS)
    target, _ = await _create_and_login(api_client, real_session, "deactivate-target")

    first = await api_client.post(
        f"/api/v1/users/{target.id}/deactivate", headers=_auth_header(access_token)
    )
    assert first.status_code == 200

    second = await api_client.post(
        f"/api/v1/users/{target.id}/deactivate", headers=_auth_header(access_token)
    )
    assert second.status_code == 422
    assert second.json()["error"]["code"] == "INVALID_STATUS_TRANSITION"


# ---------------------------------------------------------------------
# Password: Admin Reset / Force Change
# ---------------------------------------------------------------------


async def test_admin_reset_password_via_http(api_client, real_session, grant_permission):
    actor, access_token = await _create_and_login(api_client, real_session, "reset-pw-actor")
    await grant_permission(actor, PERMISSION_USERS_MANAGE_PASSWORD)
    target, _ = await _create_and_login(api_client, real_session, "reset-pw-target")

    resp = await api_client.post(
        f"/api/v1/users/{target.id}/reset-password", headers=_auth_header(access_token)
    )

    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["user"]["must_change_password"] is True
    login_resp = await api_client.post(
        "/api/v1/auth/login",
        json={"email": target.email, "password": body["temporary_password"]},
    )
    assert login_resp.status_code == 200


async def test_force_password_change_via_http(api_client, real_session, grant_permission):
    actor, access_token = await _create_and_login(api_client, real_session, "force-pw-actor")
    await grant_permission(actor, PERMISSION_USERS_MANAGE_PASSWORD)
    target, _ = await _create_and_login(api_client, real_session, "force-pw-target")

    resp = await api_client.post(
        f"/api/v1/users/{target.id}/force-password-change", headers=_auth_header(access_token)
    )

    assert resp.status_code == 200
    assert resp.json()["data"]["must_change_password"] is True


# ---------------------------------------------------------------------
# Role Assignment: Assign / Remove / Replace
# ---------------------------------------------------------------------


async def test_assign_and_remove_roles_via_http(api_client, real_session, grant_permission):
    actor, access_token = await _create_and_login(api_client, real_session, "roles-actor")
    await grant_permission(actor, PERMISSION_USERS_MANAGE_ROLES)
    target, _ = await _create_and_login(api_client, real_session, "roles-target")
    role = await _make_role(real_session)

    assign_resp = await api_client.post(
        f"/api/v1/users/{target.id}/roles/assign",
        json={"role_ids": [str(role.id)]},
        headers=_auth_header(access_token),
    )
    assert assign_resp.status_code == 200
    assert role.name in [r["name"] for r in assign_resp.json()["data"]["roles"]]

    remove_resp = await api_client.post(
        f"/api/v1/users/{target.id}/roles/remove",
        json={"role_ids": [str(role.id)]},
        headers=_auth_header(access_token),
    )
    assert remove_resp.status_code == 200
    assert remove_resp.json()["data"]["roles"] == []


async def test_replace_roles_via_http(api_client, real_session, grant_permission):
    actor, access_token = await _create_and_login(api_client, real_session, "replace-roles-actor")
    await grant_permission(actor, PERMISSION_USERS_MANAGE_ROLES)
    target, _ = await _create_and_login(api_client, real_session, "replace-roles-target")
    role_a = await _make_role(real_session)
    role_b = await _make_role(real_session)
    await api_client.post(
        f"/api/v1/users/{target.id}/roles/assign",
        json={"role_ids": [str(role_a.id)]},
        headers=_auth_header(access_token),
    )

    resp = await api_client.put(
        f"/api/v1/users/{target.id}/roles",
        json={"role_ids": [str(role_b.id)]},
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 200
    role_names = [r["name"] for r in resp.json()["data"]["roles"]]
    assert role_names == [role_b.name]


async def test_assign_unknown_role_returns_404(api_client, real_session, grant_permission):
    actor, access_token = await _create_and_login(api_client, real_session, "assign-404-actor")
    await grant_permission(actor, PERMISSION_USERS_MANAGE_ROLES)
    target, _ = await _create_and_login(api_client, real_session, "assign-404-target")

    resp = await api_client.post(
        f"/api/v1/users/{target.id}/roles/assign",
        json={"role_ids": [str(uuid7())]},
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "ROLE_NOT_FOUND"

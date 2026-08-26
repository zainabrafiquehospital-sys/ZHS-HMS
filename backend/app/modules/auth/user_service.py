"""User Management business logic (Phase 5 Step 2) — administrative CRUD,
profile self-service, status transitions, admin-driven password actions,
and role assignment over the `User`/`Role`/`UserRole` models Phase 3
already defined. Kept as its own service, separate from `AuthService`
(service.py): that service answers "can this person get in and stay in"
(login/refresh/logout/change-password); this one answers "how is the
identity/role record itself managed". Both are legitimately part of the
Authentication & Authorization module and share its repositories — this
is a SRP split within one module, not a new module boundary.

Does not subclass the shared `BaseService`
(app/shared/service/base_service.py) for the same reason `AuthService`
doesn't: `BaseService` is generic over a *single* repository, and this
coordinates five repositories plus `PasswordService` — see service.py's
own module docstring for the identical reasoning.

Every method that mutates data ends with an explicit `await
self._session.commit()`, exactly matching `AuthService`'s transaction-
boundary convention (see service.py's module docstring) — the shared
`get_db` dependency does not auto-commit.

Every mutating method returns the user it just acted on rather than
`None`, so a caller (the router) always has a fresh view to serialize.
Methods that only change plain columns (status, password fields, etc.)
mutate the already-loaded `User` object directly, so simply returning it
— or re-fetching it, which is a no-op against the same session's
identity map — is correct either way. `assign_roles`/`remove_roles`/
`replace_roles` are the one case that needs real care: they add/soft-
delete `UserRole` rows through a *separate* repository, which never
touches the `user.user_roles` collection object already sitting in
memory, and a plain re-fetch by primary key would hand back that same
stale, identity-mapped object without noticing the underlying rows
changed. See `_reload_with_fresh_roles`'s docstring for how those three
methods handle it (`session.expire()` before re-fetching)."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ValidationError
from app.modules.auth.constants import PERMISSION_USERS_MANAGE_STATUS
from app.modules.auth.exceptions import (
    EmailAlreadyRegisteredError,
    InvalidUserStatusTransitionError,
    LastAdminCannotBeDeactivatedError,
    PhoneNumberAlreadyRegisteredError,
    RoleInactiveError,
    RoleNotFoundError,
    SelfActionNotAllowedError,
    SignupNotPendingApprovalError,
    UserNotFoundError,
)
from app.modules.auth.models import (
    AuditEventStatus,
    AuditEventType,
    LoginSessionLogoutReason,
    PasswordHistory,
    RefreshTokenRevokedReason,
    Role,
    SignupRole,
    User,
    UserRole,
    UserStatus,
)
from app.modules.auth.password_service import PasswordService
from app.modules.auth.repository import (
    USER_SORTABLE_COLUMNS,
    AuditRepository,
    LoginSessionRepository,
    PasswordHistoryRepository,
    RefreshTokenRepository,
    RoleRepository,
    UserRepository,
    UserRoleRepository,
)
from app.modules.auth.validators import normalize_email
from app.shared.db_errors import unique_violation_constraint_name

# The unique-while-active indexes backing User.email/phone_number — see
# app/modules/auth/models.py and app/shared/db_errors.py for the full
# race-condition rationale.
_USER_EMAIL_CONSTRAINT = "ix_user_email_active"
_USER_PHONE_CONSTRAINT = "ix_user_phone_number_active"

# The exact Role.name each self-service signup role resolves to — see
# approve_signup's docstring. Keys are models.SignupRole members (what a
# pending User.signup_role actually holds), not the schema-side enum —
# this dict is the one place that translates "what a signup requested"
# into "which Role gets granted". Receptionist/Vitals are the Role names
# `scripts/seed_launch_bootstrap.py` creates directly; Doctor's Role
# already existed (admin-provisioned accounts, never self-service) under
# the ad hoc name `demo-doctor-demo` — see
# 8c263fc375ec_add_doctor_self_service_signup_role.py for the rename to
# `Doctor` this entry depends on. "Inventory Manager" (2026-08-26) is
# created fresh by its own migration — no rename involved, see
# models.SignupRole.INVENTORY_MANAGER's own docstring.
_SIGNUP_ROLE_TO_ROLE_NAME: dict[SignupRole, str] = {
    SignupRole.RECEPTIONIST: "Receptionist",
    SignupRole.VITALS: "Vitals",
    SignupRole.DOCTOR: "Doctor",
    SignupRole.INVENTORY_MANAGER: "Inventory Manager",
}


class UserService:
    def __init__(
        self,
        session: AsyncSession,
        user_repository: UserRepository,
        role_repository: RoleRepository,
        user_role_repository: UserRoleRepository,
        password_history_repository: PasswordHistoryRepository,
        refresh_token_repository: RefreshTokenRepository,
        login_session_repository: LoginSessionRepository,
        audit_repository: AuditRepository,
        password_service: PasswordService,
    ) -> None:
        self._session = session
        self._user_repo = user_repository
        self._role_repo = role_repository
        self._user_role_repo = user_role_repository
        self._password_history_repo = password_history_repository
        self._refresh_token_repo = refresh_token_repository
        self._login_session_repo = login_session_repository
        self._audit_repo = audit_repository
        self._password_service = password_service

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _add_user_handling_races(self, user: User) -> None:
        """Wraps `UserRepository.add` for every call site that can
        violate the email/phone unique-while-active indexes
        (`create_user`, `update_user`, `update_own_profile`). The
        `get_by_email`/`get_by_phone_number` pre-checks those callers
        already ran are not by themselves race-safe — two concurrent
        requests can both pass them before either commits — so this is
        what actually closes that window, by catching the database's
        own rejection rather than trusting the pre-check alone; see
        app/shared/db_errors.py for the full rationale."""
        try:
            await self._user_repo.add(user)
        except IntegrityError as exc:
            await self._session.rollback()
            constraint = unique_violation_constraint_name(exc)
            if constraint == _USER_EMAIL_CONSTRAINT:
                raise EmailAlreadyRegisteredError from exc
            if constraint == _USER_PHONE_CONSTRAINT:
                raise PhoneNumberAlreadyRegisteredError from exc
            raise

    async def _revoke_all_sessions(self, user_id: UUID, now: datetime) -> None:
        """Shared by every action that must immediately kill a user's
        existing access rather than merely block future logins
        (deactivate, lock, delete, admin password reset) — reuses the
        `RefreshTokenRevokedReason.ADMIN_REVOKED` /
        `LoginSessionLogoutReason.FORCED` enum members Phase 3 already
        defined for exactly this purpose (see
        app/modules/auth/models.py)."""
        await self._refresh_token_repo.revoke_all_for_user(
            user_id, RefreshTokenRevokedReason.ADMIN_REVOKED, now
        )
        await self._login_session_repo.revoke_all_for_user(
            user_id, LoginSessionLogoutReason.FORCED, now
        )

    def _active_role_ids(self, user: User) -> set[UUID]:
        """Every role_id currently on record for `user` (not soft-
        deleted). Deliberately does not also filter by `expires_at`/
        `role.is_active` the way `AuthService._active_roles` does — that
        method computes *effective* permissions at a point in time; this
        is an administrative "what assignments currently exist" view
        used only to diff against a desired role set. Precondition:
        `user.user_roles` must already be loaded — see this module's
        docstring."""
        return {user_role.role_id for user_role in user.user_roles if user_role.deleted_at is None}

    async def _require_active_role(self, role_id: UUID) -> Role:
        role = await self._role_repo.get_by_id(role_id)
        if role is None:
            raise RoleNotFoundError(role_id)
        if not role.is_active:
            raise RoleInactiveError(role_id)
        return role

    async def _reload_with_fresh_roles(self, user: User) -> User:
        """Used by assign_roles/remove_roles/replace_roles/approve_signup
        instead of a plain `UserRepository.get_by_id` re-fetch. Within
        the *same* session, re-fetching by primary key returns the
        identical Python object already in the session's identity map —
        and because that object's `user_roles` was already populated by
        the `get_user()` call at the start of the method, SQLAlchemy
        considers the relationship "already loaded" and will not
        re-issue the `selectin` query, even though `UserRole` rows were
        just added/soft-deleted underneath it.
        `session.refresh(user, attribute_names=[...])` forces exactly
        the named attributes to reload. A bare `session.expire(user)` is
        deliberately avoided — it expires *every* attribute including
        `id`, and the very next line needing `user.id` would trigger an
        implicit synchronous reload outside an active await, raising
        `MissingGreenlet`.

        `updated_at` is named here for a second, less obvious reason
        (root-caused after a live incident where `approve_signup`, the
        one caller of this method that also mutates the user's own
        columns — `status`/`updated_by` — before calling it, crashed
        with `MissingGreenlet` on `user.updated_at` access downstream in
        `UserAdminOut.from_user`): `updated_at` uses
        `onupdate=func.now()`, a server-evaluated default. The UPDATE
        flush emits `updated_at=now()` in the SQL but this project's
        mapper configuration does not fetch the computed value back via
        `RETURNING`, so SQLAlchemy marks `updated_at` expired in memory
        after that flush. A *scoped* refresh naming only `user_roles`
        does not touch or un-expire it, so it stays expired. The next
        bare attribute access to it (a plain Python `__get__`, not
        routed through any of SQLAlchemy's async entrypoints) cannot
        bridge into the greenlet context needed to lazily reload an
        expired column under `AsyncSession`, and raises the same
        `MissingGreenlet` error.

        `activate_user`/`deactivate_user`/`lock_user`/`unlock_user`/
        `update_user` mutate `status`/other columns the same way but
        never hit this: they end with a fresh
        `self._user_repo.get_by_id(user.id)` re-fetch (a real SELECT,
        not a scoped refresh), which happens to reload every scalar
        column as a side effect and so never leaves `updated_at`
        expired. `assign_roles`/`remove_roles`/`replace_roles` never hit
        it either, for the opposite reason: they never mutate `user`'s
        own columns before calling this method, so `updated_at` is never
        expired in the first place. `approve_signup` is the only caller
        that does both — mutates `user`'s own columns *and* relies on
        this scoped refresh — which is why naming `updated_at`
        explicitly alongside `user_roles` here, rather than leaving it
        to whichever caller happens to need it, is the fix: it makes
        this helper safe for any future caller with the same
        mutate-then-refresh shape, not just the one that surfaced it."""
        await self._session.refresh(user, attribute_names=["user_roles", "updated_at"])
        return user

    async def _apply_email_and_phone_updates(
        self, user: User, updates: dict[str, Any], *, allow_email: bool
    ) -> None:
        """Shared validation/mutation for the fields `UpdateUserRequest`
        and `UpdateOwnProfileRequest` have in common. `email` is only
        ever present in `updates` when `allow_email` is True (i.e. never
        for self-service — see `UpdateOwnProfileRequest`'s docstring for
        why), so the `allow_email=False` branch never actually needs to
        guard against it; the flag exists so a future caller mistake
        (accidentally passing an `email` key from self-service) fails
        loudly instead of silently applying it."""
        if "email" in updates:
            if not allow_email:
                raise ValidationError("Email cannot be changed through this endpoint.")
            if updates["email"] is None:
                raise ValidationError("Email cannot be cleared.")
            normalized = normalize_email(updates["email"])
            existing = await self._user_repo.get_by_email(normalized)
            if existing is not None and existing.id != user.id:
                raise EmailAlreadyRegisteredError
            user.email = normalized

        if "full_name" in updates:
            if updates["full_name"] is None:
                raise ValidationError("Full name cannot be cleared.")
            user.full_name = updates["full_name"]

        if "phone_number" in updates:
            phone_number = updates["phone_number"]
            if phone_number is not None:
                existing = await self._user_repo.get_by_phone_number(phone_number)
                if existing is not None and existing.id != user.id:
                    raise PhoneNumberAlreadyRegisteredError
            user.phone_number = phone_number

    # ------------------------------------------------------------------
    # Users: Create / Get / List / Update / Delete
    # ------------------------------------------------------------------

    async def create_user(
        self, *, actor: User, email: str, full_name: str, phone_number: str | None
    ) -> tuple[User, str]:
        """Creates an admin-provisioned account with a system-generated
        temporary password (never an admin-chosen one — see
        PasswordService.generate_temporary_password) and
        `must_change_password=True`. `status=ACTIVE` is set explicitly,
        mirroring `AuthService.register`'s identical reasoning: no
        email-verification flow exists yet, so gating on
        `PENDING_VERIFICATION` would leave the account permanently
        unable to log in. Returns the temporary password once; there is
        no delivery mechanism (email/SMS) in this phase, so the caller
        (the admin) is responsible for relaying it out-of-band."""
        normalized_email = normalize_email(email)
        if await self._user_repo.get_by_email(normalized_email) is not None:
            raise EmailAlreadyRegisteredError
        if (
            phone_number is not None
            and await self._user_repo.get_by_phone_number(phone_number) is not None
        ):
            raise PhoneNumberAlreadyRegisteredError

        temporary_password = self._password_service.generate_temporary_password()
        password_hash = await self._password_service.hash(temporary_password)

        user = User(
            email=normalized_email,
            password_hash=password_hash,
            full_name=full_name,
            phone_number=phone_number,
            status=UserStatus.ACTIVE,
            must_change_password=True,
            created_by=actor.id,
            updated_by=actor.id,
        )
        await self._add_user_handling_races(user)
        await self._password_history_repo.add(
            PasswordHistory(user_id=user.id, password_hash=password_hash)
        )
        await self._audit_repo.record(
            event_type=AuditEventType.USER_CREATED,
            status=AuditEventStatus.SUCCESS,
            actor_user_id=actor.id,
            target_user_id=user.id,
        )
        await self._session.commit()
        created = await self._user_repo.get_by_id(user.id)
        return created, temporary_password

    async def get_user(self, user_id: UUID) -> User:
        user = await self._user_repo.get_by_id(user_id)
        if user is None:
            raise UserNotFoundError
        return user

    async def list_by_ids(self, user_ids: list[UUID]) -> list[User]:
        """Batch lookup — see UserRepository.list_by_ids's own docstring.
        Never raises UserNotFoundError for a missing id (unlike
        get_user): a caller resolving a name for display should simply
        have fewer rows to match against, not fail outright."""
        return await self._user_repo.list_by_ids(user_ids)

    async def list_users(
        self,
        *,
        search: str | None,
        status: UserStatus | None,
        role_id: UUID | None,
        sort_by: str,
        sort_desc: bool,
        page: int,
        page_size: int,
    ) -> tuple[list[User], int]:
        """`sort_by` must be one of `USER_SORTABLE_COLUMNS`'s keys — the
        router only ever passes through `UserSortField`'s enum values,
        which are defined to match that whitelist exactly, so this never
        needs to fall back for a value that actually reached this
        method through the real API."""
        sort_column = USER_SORTABLE_COLUMNS[sort_by]
        return await self._user_repo.search(
            search=search,
            status=status,
            role_id=role_id,
            sort_column=sort_column,
            sort_desc=sort_desc,
            limit=page_size,
            offset=(page - 1) * page_size,
        )

    async def update_user(self, *, actor: User, user_id: UUID, updates: dict[str, Any]) -> User:
        """Admin-driven partial update of `email`/`full_name`/
        `phone_number` only — `status` is deliberately never editable
        here. Changing it always goes through
        activate_user/deactivate_user/lock_user/unlock_user instead, so
        every status change is guaranteed to pass through their business
        -rule validation and session-revocation side effects; a generic
        field-level PATCH must never be able to bypass that."""
        user = await self.get_user(user_id)
        if not updates:
            return user

        await self._apply_email_and_phone_updates(user, updates, allow_email=True)
        user.updated_by = actor.id
        await self._add_user_handling_races(user)
        await self._audit_repo.record(
            event_type=AuditEventType.USER_UPDATED,
            status=AuditEventStatus.SUCCESS,
            actor_user_id=actor.id,
            target_user_id=user.id,
            metadata={"fields": sorted(updates.keys())},
        )
        await self._session.commit()
        return await self._user_repo.get_by_id(user.id)

    async def update_own_profile(self, *, user: User, updates: dict[str, Any]) -> User:
        if not updates:
            return user

        await self._apply_email_and_phone_updates(user, updates, allow_email=False)
        user.updated_by = user.id
        await self._add_user_handling_races(user)
        await self._audit_repo.record(
            event_type=AuditEventType.USER_UPDATED,
            status=AuditEventStatus.SUCCESS,
            actor_user_id=user.id,
            target_user_id=user.id,
            metadata={"fields": sorted(updates.keys()), "self_service": True},
        )
        await self._session.commit()
        return await self._user_repo.get_by_id(user.id)

    async def delete_user(self, *, actor: User, user_id: UUID) -> None:
        if actor.id == user_id:
            raise SelfActionNotAllowedError
        user = await self.get_user(user_id)

        now = datetime.now(UTC)
        await self._user_repo.soft_delete(user, deleted_at=now, deleted_by=actor.id)
        await self._revoke_all_sessions(user.id, now)
        await self._audit_repo.record(
            event_type=AuditEventType.USER_DELETED,
            status=AuditEventStatus.SUCCESS,
            actor_user_id=actor.id,
            target_user_id=user.id,
        )
        await self._session.commit()

    # ------------------------------------------------------------------
    # Status: Activate / Deactivate / Lock / Unlock
    # ------------------------------------------------------------------

    async def activate_user(self, *, actor: User, user_id: UUID) -> User:
        user = await self.get_user(user_id)
        if user.status == UserStatus.ACTIVE:
            raise InvalidUserStatusTransitionError("User is already active.")

        user.status = UserStatus.ACTIVE
        user.locked_until = None
        user.failed_login_attempts = 0
        user.updated_by = actor.id
        await self._user_repo.add(user)
        await self._audit_repo.record(
            event_type=AuditEventType.USER_ACTIVATED,
            status=AuditEventStatus.SUCCESS,
            actor_user_id=actor.id,
            target_user_id=user.id,
        )
        await self._session.commit()
        return await self._user_repo.get_by_id(user.id)

    async def deactivate_user(self, *, actor: User, user_id: UUID) -> User:
        if actor.id == user_id:
            raise SelfActionNotAllowedError
        user = await self.get_user(user_id)
        if user.status == UserStatus.INACTIVE:
            raise InvalidUserStatusTransitionError("User is already inactive.")

        now = datetime.now(UTC)
        # Never deactivate the last user who could still undo an account
        # lockout — including reactivating whoever gets deactivated here.
        # Counts *other* active holders of the exact permission that
        # gates activate/deactivate/lock/unlock (permission-based, not a
        # hardcoded role-name check — see UserRepository.
        # count_active_holders_of_permission's docstring). Runs
        # unconditionally, not only when `user` itself holds this
        # permission: the question is always "how many would remain",
        # never "does this specific user matter".
        remaining_holders = await self._user_repo.count_active_holders_of_permission(
            PERMISSION_USERS_MANAGE_STATUS, now=now, exclude_user_id=user.id
        )
        if remaining_holders == 0:
            raise LastAdminCannotBeDeactivatedError

        user.status = UserStatus.INACTIVE
        user.updated_by = actor.id
        await self._user_repo.add(user)
        await self._revoke_all_sessions(user.id, now)
        await self._audit_repo.record(
            event_type=AuditEventType.USER_DEACTIVATED,
            status=AuditEventStatus.SUCCESS,
            actor_user_id=actor.id,
            target_user_id=user.id,
        )
        await self._session.commit()
        return await self._user_repo.get_by_id(user.id)

    async def lock_user(self, *, actor: User, user_id: UUID) -> User:
        """Admin-imposed lock — sets `status=LOCKED`, distinct from the
        temporary, auto-expiring `locked_until` the failed-login-attempt
        counter sets in `AuthService.login`. `AuthService.login` already
        checks both, so either form blocks login identically."""
        if actor.id == user_id:
            raise SelfActionNotAllowedError
        user = await self.get_user(user_id)
        if user.status == UserStatus.LOCKED:
            raise InvalidUserStatusTransitionError("User is already locked.")

        now = datetime.now(UTC)
        user.status = UserStatus.LOCKED
        user.updated_by = actor.id
        await self._user_repo.add(user)
        await self._revoke_all_sessions(user.id, now)
        await self._audit_repo.record(
            event_type=AuditEventType.ACCOUNT_LOCKED,
            status=AuditEventStatus.SUCCESS,
            actor_user_id=actor.id,
            target_user_id=user.id,
            metadata={"reason": "admin_action"},
        )
        await self._session.commit()
        return await self._user_repo.get_by_id(user.id)

    async def unlock_user(self, *, actor: User, user_id: UUID) -> User:
        user = await self.get_user(user_id)
        now = datetime.now(UTC)
        is_locked = user.status == UserStatus.LOCKED or (
            user.locked_until is not None and user.locked_until > now
        )
        if not is_locked:
            raise InvalidUserStatusTransitionError("User is not locked.")

        user.status = UserStatus.ACTIVE
        user.locked_until = None
        user.failed_login_attempts = 0
        user.updated_by = actor.id
        await self._user_repo.add(user)
        await self._audit_repo.record(
            event_type=AuditEventType.ACCOUNT_UNLOCKED,
            status=AuditEventStatus.SUCCESS,
            actor_user_id=actor.id,
            target_user_id=user.id,
        )
        await self._session.commit()
        return await self._user_repo.get_by_id(user.id)

    # ------------------------------------------------------------------
    # Self-Service Signup Approval
    # ------------------------------------------------------------------

    async def approve_signup(self, *, actor: User, user_id: UUID) -> User:
        """Assigns whichever role `user.signup_role` recorded at signup
        time (via `_SIGNUP_ROLE_TO_ROLE_NAME`) and moves the account to
        ACTIVE. Role assignment reuses the exact same association-row/
        audit pattern as `assign_roles` rather than a bespoke insert, and
        the status transition mirrors `activate_user` — this method is
        really "assign_roles + activate_user" for whichever one role a
        signup resolves to.

        `signup_role` being `None` (only possible for a handful of
        accounts that signed up before this column existed — every
        current signup path always sets it) falls back to
        `RECEPTIONIST`: that was the only role self-service signup could
        ever produce before this field existed, so treating an absent
        value as "was a receptionist signup" is the historically correct
        reading, not a guess.

        Deliberately does NOT send the approval confirmation email
        itself (see this class's earlier revision's own docstring,
        which said the opposite — corrected after a live production
        incident): `EmailService.send`'s real-delivery path is genuine
        network I/O (originally a blocking, `asyncio.to_thread`-wrapped
        SMTP call; now a native async HTTP POST to the Resend API — see
        shared/email/service.py), and empirically, regardless of exactly
        where in this method it ran relative to the session's own work,
        its mere presence anywhere in this call's lifecycle left the
        async DB session unable to service a later ORM attribute access
        in *this same request* — reproduced live as
        `sqlalchemy.exc.MissingGreenlet` at the router's own
        `UserAdminOut.from_user(user)` call, every time, only with a real
        send attempted (never with the console-fallback path this was
        originally, and insufficiently, verified against). The switch
        away from SMTP doesn't change this — it's still a real network
        call. The actual DB work
        (commit, role grant, status change) always completed
        successfully regardless — only the HTTP response after it broke.
        The robust fix is architectural, not a reordering: decouple the
        slow email send from this request/session lifecycle entirely,
        via `BackgroundTasks` in the router, scheduled to run only after
        the response (and this session) are already done. See
        user_router.py's `approve_signup` endpoint."""
        user = await self.get_user(user_id)
        if user.status != UserStatus.PENDING_ADMIN_APPROVAL:
            raise SignupNotPendingApprovalError

        signup_role = user.signup_role or SignupRole.RECEPTIONIST
        role_name = _SIGNUP_ROLE_TO_ROLE_NAME[signup_role]
        role = await self._role_repo.get_by_name(role_name)
        if role is None or not role.is_active:
            raise RoleNotFoundError(role_name)

        if role.id not in self._active_role_ids(user):
            await self._user_role_repo.add(
                UserRole(user_id=user.id, role_id=role.id, assigned_by=actor.id)
            )
            await self._audit_repo.record(
                event_type=AuditEventType.ROLE_ASSIGNED,
                status=AuditEventStatus.SUCCESS,
                actor_user_id=actor.id,
                target_user_id=user.id,
                metadata={"role_id": str(role.id), "role_name": role.name},
            )

        user.status = UserStatus.ACTIVE
        user.updated_by = actor.id
        await self._user_repo.add(user)
        await self._audit_repo.record(
            event_type=AuditEventType.SIGNUP_APPROVED,
            status=AuditEventStatus.SUCCESS,
            actor_user_id=actor.id,
            target_user_id=user.id,
        )
        await self._session.commit()
        return await self._reload_with_fresh_roles(user)

    async def reject_signup(self, *, actor: User, user_id: UUID) -> User:
        """Moves the account to REJECTED — permanently login-blocked,
        distinct from INACTIVE (see UserStatus's own docstring for why).
        No confirmation email: checked against every existing status-
        transition method in this module (activate/deactivate/lock/
        unlock), none of them sends one either — email-on-status-change
        is an approve-specific addition (the applicant is actively
        waiting to hear back), not an established convention this method
        should invent a first exception to."""
        user = await self.get_user(user_id)
        if user.status != UserStatus.PENDING_ADMIN_APPROVAL:
            raise SignupNotPendingApprovalError

        user.status = UserStatus.REJECTED
        user.updated_by = actor.id
        await self._user_repo.add(user)
        await self._audit_repo.record(
            event_type=AuditEventType.SIGNUP_REJECTED,
            status=AuditEventStatus.SUCCESS,
            actor_user_id=actor.id,
            target_user_id=user.id,
        )
        await self._session.commit()
        return await self._user_repo.get_by_id(user.id)

    # ------------------------------------------------------------------
    # Password: Admin Reset / Force Change
    # ------------------------------------------------------------------

    async def admin_reset_password(self, *, actor: User, user_id: UUID) -> tuple[User, str]:
        """Mirrors `create_user`'s temporary-password approach: the
        admin cannot choose the new password (removing the risk of a
        weak or shared admin-chosen one), it is returned once, and every
        existing session/refresh token is revoked immediately — the old
        credential must stop working the instant it's replaced, exactly
        like `AuthService.change_password`'s self-service equivalent."""
        user = await self.get_user(user_id)
        temporary_password = self._password_service.generate_temporary_password()
        password_hash = await self._password_service.hash(temporary_password)
        now = datetime.now(UTC)

        user.password_hash = password_hash
        user.password_changed_at = now
        user.must_change_password = True
        user.updated_by = actor.id
        await self._user_repo.add(user)
        await self._password_history_repo.add(
            PasswordHistory(user_id=user.id, password_hash=password_hash)
        )
        await self._refresh_token_repo.revoke_all_for_user(
            user.id, RefreshTokenRevokedReason.PASSWORD_CHANGED, now
        )
        await self._login_session_repo.revoke_all_for_user(
            user.id, LoginSessionLogoutReason.FORCED, now
        )
        await self._audit_repo.record(
            event_type=AuditEventType.PASSWORD_RESET_BY_ADMIN,
            status=AuditEventStatus.SUCCESS,
            actor_user_id=actor.id,
            target_user_id=user.id,
        )
        await self._session.commit()
        refreshed = await self._user_repo.get_by_id(user.id)
        return refreshed, temporary_password

    async def force_password_change(self, *, actor: User, user_id: UUID) -> User:
        """Sets `must_change_password=True` without touching the current
        password or any session — unlike `admin_reset_password`, the
        admin doesn't know (and this doesn't invalidate) the current
        credential, only requires it be changed at next login.
        Idempotent: calling this on a user already flagged is a no-op
        success, not an error, since the flag itself (not the act of
        setting it) is what matters here."""
        user = await self.get_user(user_id)
        user.must_change_password = True
        user.updated_by = actor.id
        await self._user_repo.add(user)
        await self._audit_repo.record(
            event_type=AuditEventType.PASSWORD_CHANGE_FORCED,
            status=AuditEventStatus.SUCCESS,
            actor_user_id=actor.id,
            target_user_id=user.id,
        )
        await self._session.commit()
        return await self._user_repo.get_by_id(user.id)

    # ------------------------------------------------------------------
    # Role Assignment: Assign / Remove / Replace
    # ------------------------------------------------------------------

    async def assign_roles(self, *, actor: User, user_id: UUID, role_ids: list[UUID]) -> User:
        """Adds roles not already actively assigned; a role_id already
        assigned is silently skipped (idempotent), matching this
        codebase's established idempotency precedent (see
        `AuthService.logout`'s docstring)."""
        user = await self.get_user(user_id)
        to_add = set(role_ids) - self._active_role_ids(user)

        roles_by_id: dict[UUID, Role] = {}
        for role_id in to_add:
            roles_by_id[role_id] = await self._require_active_role(role_id)

        for role_id, role in roles_by_id.items():
            await self._user_role_repo.add(
                UserRole(user_id=user.id, role_id=role_id, assigned_by=actor.id)
            )
            await self._audit_repo.record(
                event_type=AuditEventType.ROLE_ASSIGNED,
                status=AuditEventStatus.SUCCESS,
                actor_user_id=actor.id,
                target_user_id=user.id,
                metadata={"role_id": str(role_id), "role_name": role.name},
            )
        if roles_by_id:
            await self._session.commit()
        return await self._reload_with_fresh_roles(user)

    async def remove_roles(self, *, actor: User, user_id: UUID, role_ids: list[UUID]) -> User:
        """Removes (soft-deletes) the given role assignments; a role_id
        with no currently-active assignment is silently skipped
        (idempotent) rather than raising — there is nothing to remove,
        which is not an error condition."""
        user = await self.get_user(user_id)
        now = datetime.now(UTC)
        changed = False

        for role_id in set(role_ids):
            user_role = await self._user_role_repo.get_active(user.id, role_id)
            if user_role is None:
                continue
            role_name = user_role.role.name
            await self._user_role_repo.soft_delete(user_role, deleted_at=now, deleted_by=actor.id)
            await self._audit_repo.record(
                event_type=AuditEventType.ROLE_REVOKED,
                status=AuditEventStatus.SUCCESS,
                actor_user_id=actor.id,
                target_user_id=user.id,
                metadata={"role_id": str(role_id), "role_name": role_name},
            )
            changed = True

        if changed:
            await self._session.commit()
        return await self._reload_with_fresh_roles(user)

    async def replace_roles(self, *, actor: User, user_id: UUID, role_ids: list[UUID]) -> User:
        """Sets the user's role assignments to exactly `role_ids`:
        removes every currently-active assignment not in the given set
        and adds every one in it that isn't already active. Every new
        role is validated (exists and is active) before any mutation is
        applied, so a partially-invalid request fails atomically instead
        of leaving a half-applied change."""
        user = await self.get_user(user_id)
        current = self._active_role_ids(user)
        desired = set(role_ids)
        to_add = desired - current
        to_remove = current - desired

        roles_by_id: dict[UUID, Role] = {}
        for role_id in to_add:
            roles_by_id[role_id] = await self._require_active_role(role_id)

        now = datetime.now(UTC)
        for role_id in to_remove:
            user_role = await self._user_role_repo.get_active(user.id, role_id)
            if user_role is None:
                continue
            role_name = user_role.role.name
            await self._user_role_repo.soft_delete(user_role, deleted_at=now, deleted_by=actor.id)
            await self._audit_repo.record(
                event_type=AuditEventType.ROLE_REVOKED,
                status=AuditEventStatus.SUCCESS,
                actor_user_id=actor.id,
                target_user_id=user.id,
                metadata={"role_id": str(role_id), "role_name": role_name},
            )

        for role_id, role in roles_by_id.items():
            await self._user_role_repo.add(
                UserRole(user_id=user.id, role_id=role_id, assigned_by=actor.id)
            )
            await self._audit_repo.record(
                event_type=AuditEventType.ROLE_ASSIGNED,
                status=AuditEventStatus.SUCCESS,
                actor_user_id=actor.id,
                target_user_id=user.id,
                metadata={"role_id": str(role_id), "role_name": role.name},
            )

        if to_add or to_remove:
            await self._session.commit()
        return await self._reload_with_fresh_roles(user)

"""Authentication business logic — the `service.py` the architecture
document's folder structure (§8) names as the module's business-rule
layer. Talks to `repository.py` for persistence and to
`password_service.py`/`token_service.py` for crypto; never touches
SQLAlchemy or JWT/Argon2 primitives directly itself.

Does not subclass the shared `BaseService` (app/shared/service/base_service.py):
`BaseService` is explicitly generic over a *single* repository type for
simple CRUD services, and this is a coordinating application service over
six repositories plus two crypto services — a different, legitimate shape,
not a redesign of `BaseService`'s own single-entity contract.

Every method that mutates data ends with an explicit `await
self._session.commit()` — the shared `get_db` dependency
(app/core/dependencies.py) does not auto-commit, only auto-closes (which
discards any uncommitted work), so the service is where each transaction's
boundary is deliberately drawn, exactly once per business operation."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from uuid6 import uuid7

from app.core.config import Settings
from app.core.logging import get_logger
from app.core.token_rotation import ReuseVerdict, RotatedTokenState, classify_reuse
from app.modules.auth.exceptions import (
    AccountLockedError,
    AccountPendingApprovalError,
    AccountPendingEmailVerificationError,
    AccountSuspendedError,
    EmailAlreadyRegisteredError,
    InvalidCredentialsError,
    OtpInvalidError,
    PhoneNumberAlreadyRegisteredError,
    TokenInvalidError,
)
from app.modules.auth.models import (
    AuditEventStatus,
    AuditEventType,
    LoginSession,
    LoginSessionLogoutReason,
    OtpCode,
    OtpPurpose,
    PasswordHistory,
    RefreshToken,
    RefreshTokenRevokedReason,
    Role,
    User,
    UserStatus,
)
from app.modules.auth.otp_service import OtpService
from app.modules.auth.password_service import PasswordService
from app.modules.auth.repository import (
    AuditRepository,
    LoginSessionRepository,
    OtpCodeRepository,
    PasswordHistoryRepository,
    RefreshTokenRepository,
    UserRepository,
)
from app.modules.auth.token_service import TokenService
from app.modules.auth.validators import normalize_email
from app.shared.db_errors import unique_violation_constraint_name
from app.shared.email.service import EmailService, render_otp_email

logger = get_logger(__name__)

# The unique-while-active indexes backing User.email/phone_number — see
# app/modules/auth/models.py and app/shared/db_errors.py for the full
# race-condition rationale (found during post-Phase-5 production QA
# hardening; the identical fix is applied in user_service.py/
# role_service.py/permission_service.py for their own unique fields).
_USER_EMAIL_CONSTRAINT = "ix_user_email_active"
_USER_PHONE_CONSTRAINT = "ix_user_phone_number_active"

_LOGGABLE_STATUSES = (UserStatus.ACTIVE, UserStatus.PENDING_VERIFICATION)


@dataclass(frozen=True)
class LoginResult:
    user: User
    access_token: str
    raw_refresh_token: str
    remember_me: bool


@dataclass(frozen=True)
class RefreshResult:
    user: User
    access_token: str
    raw_refresh_token: str
    remember_me: bool


class AuthService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        user_repository: UserRepository,
        refresh_token_repository: RefreshTokenRepository,
        login_session_repository: LoginSessionRepository,
        password_history_repository: PasswordHistoryRepository,
        audit_repository: AuditRepository,
        password_service: PasswordService,
        token_service: TokenService,
        otp_code_repository: OtpCodeRepository,
        otp_service: OtpService,
        email_service: EmailService,
    ) -> None:
        self._session = session
        self._settings = settings
        self._user_repo = user_repository
        self._refresh_token_repo = refresh_token_repository
        self._login_session_repo = login_session_repository
        self._password_history_repo = password_history_repository
        self._audit_repo = audit_repository
        self._password_service = password_service
        self._token_service = token_service
        self._otp_repo = otp_code_repository
        self._otp_service = otp_service
        self._email_service = email_service

    # ------------------------------------------------------------------
    # Role / permission loading
    # ------------------------------------------------------------------

    def _active_roles(self, user: User, now: datetime) -> list[Role]:
        """Every role currently granted to `user`: not soft-deleted, not
        expired, and the role itself is active and not soft-deleted. This
        walks the already-`lazy="selectin"`-loaded relationship chain
        built in Phase 3 rather than issuing a new query — see
        app/modules/auth/models.py's module docstring for why every
        relationship in this module loads that way.

        Precondition: `user.user_roles` must already be loaded, which
        `selectin` only guarantees for a `User` obtained via a fresh
        `UserRepository` fetch (`get_by_id`/`get_by_email`) — true for
        every caller in this module (`login` re-fetches by email,
        `refresh`/`get_current_user` fetch by id). A `User` built in
        memory and never re-queried after `add()` — e.g. `register`'s
        return value used directly — does not have it loaded, and a sync
        call touching it outside an active async context raises
        SQLAlchemy's `MissingGreenlet`, not a silent empty result."""
        roles: list[Role] = []
        for user_role in user.user_roles:
            if user_role.deleted_at is not None:
                continue
            if user_role.expires_at is not None and user_role.expires_at <= now:
                continue
            role = user_role.role
            if role.deleted_at is not None or not role.is_active:
                continue
            roles.append(role)
        return roles

    def effective_role_names(self, user: User, now: datetime | None = None) -> list[str]:
        now = now or datetime.now(UTC)
        return sorted({role.name for role in self._active_roles(user, now)})

    def effective_permission_codes(self, user: User, now: datetime | None = None) -> set[str]:
        """Union of every permission granted by every active role — see
        the architecture document's §3 "effective permission
        calculation". Deliberately recomputed from relationships rather
        than cached (e.g. in Redis): that optimization was explicitly
        scoped out of this phase (see the final report)."""
        now = now or datetime.now(UTC)
        codes: set[str] = set()
        for role in self._active_roles(user, now):
            for role_permission in role.role_permissions:
                if role_permission.deleted_at is not None:
                    continue
                permission = role_permission.permission
                if permission.deleted_at is not None:
                    continue
                codes.add(permission.code)
        return codes

    # ------------------------------------------------------------------
    # Register
    # ------------------------------------------------------------------

    async def register(
        self,
        *,
        email: str,
        password: str,
        full_name: str,
        phone_number: str | None = None,
    ) -> User:
        """Creates a new, immediately loggable-in account. Not exposed via
        any HTTP endpoint in this phase (see router.py) — no email-
        verification flow exists yet, so gating on `PENDING_VERIFICATION`
        would leave every registered account permanently unable to log
        in; `status=ACTIVE` is set explicitly here rather than relying on
        the model's default for exactly that reason.

        Found during post-Phase-5 production QA hardening: this method
        previously never checked `phone_number` for duplicates at all
        (only `email`), and even the email check was not race-safe on
        its own — two concurrent calls could both pass it before either
        committed. Both are fixed the same way `UserService.create_user`
        already handled them: a pre-check for the fast, common case, and
        a `try`/`except IntegrityError` around the actual insert to
        catch whichever one loses a genuine race; see
        app/shared/db_errors.py."""
        normalized_email = normalize_email(email)
        if await self._user_repo.get_by_email(normalized_email) is not None:
            raise EmailAlreadyRegisteredError
        if (
            phone_number is not None
            and await self._user_repo.get_by_phone_number(phone_number) is not None
        ):
            raise PhoneNumberAlreadyRegisteredError

        self._password_service.validate_policy(password)
        password_hash = await self._password_service.hash(password)

        user = User(
            email=normalized_email,
            password_hash=password_hash,
            full_name=full_name,
            phone_number=phone_number,
            status=UserStatus.ACTIVE,
            # Explicit, not left to the column's own `True` default —
            # same reasoning as SignupService.signup's identical
            # explicit `False` (see that call site's own comment, added
            # in the 2026-08-19 must_change_password enforcement fix
            # pass): this method's caller chooses their own password
            # right here, so there is no temporary credential to force a
            # change away from.
            must_change_password=False,
        )
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
        await self._password_history_repo.add(
            PasswordHistory(user_id=user.id, password_hash=password_hash)
        )
        await self._session.commit()
        return user

    # ------------------------------------------------------------------
    # Login
    # ------------------------------------------------------------------

    async def login(
        self,
        *,
        email: str,
        password: str,
        remember_me: bool,
        ip_address: str | None,
        user_agent: str | None,
    ) -> LoginResult:
        now = datetime.now(UTC)
        user = await self._user_repo.get_by_email(email)

        if user is None:
            # Pays the same Argon2id cost a real verification would, so a
            # client can't distinguish "no such account" from "wrong
            # password" by response latency — see password_service.py.
            await self._password_service.verify_dummy(password)
            await self._audit_repo.record(
                event_type=AuditEventType.LOGIN_FAILED,
                status=AuditEventStatus.FAILURE,
                ip_address=ip_address,
                user_agent=user_agent,
            )
            await self._session.commit()
            raise InvalidCredentialsError

        if user.status == UserStatus.LOCKED or (
            user.locked_until is not None and user.locked_until > now
        ):
            raise AccountLockedError
        if user.status in (UserStatus.SUSPENDED, UserStatus.INACTIVE, UserStatus.REJECTED):
            raise AccountSuspendedError
        # Both checked before password verification, same as every status
        # branch above — a self-service-signup account genuinely cannot
        # log in yet regardless of whether the password it types is
        # correct, so there's no reason to pay the Argon2id cost first
        # (see UserStatus's own docstring for what each of these two
        # states means and how an account moves past them).
        if user.status == UserStatus.PENDING_EMAIL_VERIFICATION:
            raise AccountPendingEmailVerificationError
        if user.status == UserStatus.PENDING_ADMIN_APPROVAL:
            raise AccountPendingApprovalError

        if not await self._password_service.verify(user.password_hash, password):
            user.failed_login_attempts += 1
            if user.failed_login_attempts >= self._settings.account_lockout_threshold:
                user.locked_until = now + timedelta(
                    minutes=self._settings.account_lockout_duration_minutes
                )
            await self._user_repo.add(user)
            await self._audit_repo.record(
                event_type=AuditEventType.LOGIN_FAILED,
                status=AuditEventStatus.FAILURE,
                target_user_id=user.id,
                ip_address=ip_address,
                user_agent=user_agent,
            )
            await self._session.commit()
            raise InvalidCredentialsError

        user.failed_login_attempts = 0
        user.locked_until = None
        user.last_login_at = now
        user.last_login_ip = ip_address
        await self._user_repo.add(user)

        access_token, _jti = self._token_service.create_access_token(
            user.id, self.effective_role_names(user, now)
        )
        raw_refresh_token, refresh_hash = self._token_service.generate_refresh_token()
        expire_days = (
            self._settings.jwt_refresh_token_remember_me_expire_days
            if remember_me
            else self._settings.jwt_refresh_token_expire_days
        )
        refresh_token = RefreshToken(
            user_id=user.id,
            token_hash=refresh_hash,
            family_id=uuid7(),
            expires_at=now + timedelta(days=expire_days),
        )
        await self._refresh_token_repo.add(refresh_token)

        await self._login_session_repo.add(
            LoginSession(
                user_id=user.id,
                refresh_token_id=refresh_token.id,
                ip_address=ip_address,
                user_agent=user_agent,
                remember_me=remember_me,
            )
        )

        await self._audit_repo.record(
            event_type=AuditEventType.LOGIN_SUCCESS,
            status=AuditEventStatus.SUCCESS,
            actor_user_id=user.id,
            target_user_id=user.id,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        await self._session.commit()
        return LoginResult(
            user=user,
            access_token=access_token,
            raw_refresh_token=raw_refresh_token,
            remember_me=remember_me,
        )

    # ------------------------------------------------------------------
    # Refresh (rotation, with reuse detection)
    # ------------------------------------------------------------------

    async def refresh(
        self,
        *,
        raw_refresh_token: str,
        ip_address: str | None,
        user_agent: str | None,
        expected_user_id: UUID | None = None,
    ) -> RefreshResult:
        """`expected_user_id`, when given, is who the *caller* (a specific
        browser tab, per its own in-memory record of who it last logged
        in as — see frontend/src/services/api/tokenStore.js) believes it
        is about to refresh as. It exists to close a cross-tab identity-
        bleed gap found in the 2026-08-19 audit: the refresh cookie is
        scoped per-origin+path, not per-tab, so on a shared front-desk
        machine, Staff B logging in on a second tab silently overwrites
        the one browser-wide cookie Staff A's still-open tab depends on.
        Without this check, Tab A's next silent refresh (on reload, or
        the access-token-expiry retry in httpClient.js) would decode
        *whichever* refresh token the cookie currently holds and hand Tab
        A a valid access token for Staff B — a real identity swap, not
        merely a logout. When the resolved token's owner doesn't match
        what the caller expected, this is treated as an invalid token
        (the same generic `TokenInvalidError` every other refresh failure
        raises — no separate error code, so a client can't use this to
        enumerate whether a given user id is currently logged in
        elsewhere) rather than a successful refresh, *before* any
        rotation is attempted — so a mismatched request never consumes
        or disturbs the legitimate session's own rotation slot. This is
        deliberately not a reuse-attack/family-revocation event: nothing
        was stolen or replayed, one browser legitimately holds two
        different people's login history, so the *other* (matching)
        session must be left completely undisturbed."""
        now = datetime.now(UTC)
        token_hash = self._token_service.hash_refresh_token(raw_refresh_token)
        old_token = await self._refresh_token_repo.get_by_token_hash(token_hash)

        if old_token is None or old_token.expires_at <= now:
            raise TokenInvalidError

        user = await self._user_repo.get_by_id(old_token.user_id)
        if user is None or user.status not in _LOGGABLE_STATUSES:
            raise TokenInvalidError

        if expected_user_id is not None and user.id != expected_user_id:
            logger.warning(
                "refresh_identity_mismatch",
                expected_user_id=str(expected_user_id),
                resolved_user_id=str(user.id),
            )
            raise TokenInvalidError

        login_session = next((s for s in old_token.login_sessions if s.is_active), None)
        remember_me = login_session.remember_me if login_session is not None else False
        expire_days = (
            self._settings.jwt_refresh_token_remember_me_expire_days
            if remember_me
            else self._settings.jwt_refresh_token_expire_days
        )

        raw_new_refresh_token, new_refresh_hash = self._token_service.generate_refresh_token()
        new_token = RefreshToken(
            user_id=user.id,
            token_hash=new_refresh_hash,
            family_id=old_token.family_id,
            expires_at=now + timedelta(days=expire_days),
        )
        await self._refresh_token_repo.add(new_token)

        won = (
            await self._refresh_token_repo.claim_rotation(old_token.id, new_token.id, now)
            if old_token.revoked_at is None
            else False
        )

        if not won:
            current = await self._refresh_token_repo.get_by_id(old_token.id)
            reused_legitimately = (
                current.revoked_reason == RefreshTokenRevokedReason.ROTATED
                and classify_reuse(
                    RotatedTokenState(
                        revoked_at=current.revoked_at, replaced_by_id=current.replaced_by_id
                    ),
                    now=now,
                )
                is ReuseVerdict.BENIGN_REPLAY
            )
            if not reused_legitimately:
                # Either an explicit revocation being replayed (logout,
                # admin action, a prior reuse response) or a genuine
                # rotation-reuse outside the grace window — neither is
                # ever tolerated regardless of timing.
                await self._refresh_token_repo.revoke_family(
                    old_token.family_id, RefreshTokenRevokedReason.REUSE_DETECTED, now
                )
                await self._audit_repo.record(
                    event_type=AuditEventType.TOKEN_REUSE_DETECTED,
                    status=AuditEventStatus.FAILURE,
                    actor_user_id=user.id,
                    target_user_id=user.id,
                    ip_address=ip_address,
                    user_agent=user_agent,
                )
                await self._session.commit()
                raise TokenInvalidError
            # BENIGN_REPLAY: `new_token` (already inserted above) becomes
            # this request's own valid rotation. We cannot hand back the
            # winner's raw token — only its hash was ever persisted — so
            # both racing requests end up with independently valid tokens
            # in the same family instead of one succeeding and one being
            # forced to log in again.

        if login_session is not None:
            login_session.refresh_token_id = new_token.id
            await self._login_session_repo.add(login_session)

        access_token, _jti = self._token_service.create_access_token(
            user.id, self.effective_role_names(user, now)
        )
        await self._audit_repo.record(
            event_type=AuditEventType.TOKEN_REFRESHED,
            status=AuditEventStatus.SUCCESS,
            actor_user_id=user.id,
            target_user_id=user.id,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        await self._session.commit()
        return RefreshResult(
            user=user,
            access_token=access_token,
            raw_refresh_token=raw_new_refresh_token,
            remember_me=remember_me,
        )

    # ------------------------------------------------------------------
    # Logout
    # ------------------------------------------------------------------

    async def logout(self, *, raw_refresh_token: str) -> None:
        """Idempotent by design: an already-invalid or missing cookie
        simply means there is nothing left to revoke, not an error — a
        client retrying a logout call must never be told it failed."""
        token_hash = self._token_service.hash_refresh_token(raw_refresh_token)
        token = await self._refresh_token_repo.get_by_token_hash(token_hash)
        if token is None:
            return

        now = datetime.now(UTC)
        if token.revoked_at is None:
            await self._refresh_token_repo.revoke(token, RefreshTokenRevokedReason.LOGOUT, now)

        login_session = next((s for s in token.login_sessions if s.is_active), None)
        if login_session is not None:
            await self._login_session_repo.revoke(
                login_session, LoginSessionLogoutReason.USER_LOGOUT, now
            )

        await self._audit_repo.record(
            event_type=AuditEventType.LOGOUT,
            status=AuditEventStatus.SUCCESS,
            actor_user_id=token.user_id,
            target_user_id=token.user_id,
        )
        await self._session.commit()

    async def logout_all(self, *, user: User, current_access_token_jti: str | None = None) -> None:
        """Revokes every refresh token and closes every active session
        for `user`. Also blacklists the access token used to authenticate
        *this* call, if given — an access token is otherwise stateless
        and would keep working for up to its remaining short lifetime
        even after "logging out everywhere"; see token_service.py and the
        architecture document's §4/§6 for why that blacklist exists at
        all, and why it's reserved for cases like this one rather than
        every ordinary logout."""
        now = datetime.now(UTC)
        await self._refresh_token_repo.revoke_all_for_user(
            user.id, RefreshTokenRevokedReason.LOGOUT, now
        )
        await self._login_session_repo.revoke_all_for_user(
            user.id, LoginSessionLogoutReason.USER_LOGOUT, now
        )
        if current_access_token_jti:
            await self._token_service.blacklist_jti(
                current_access_token_jti,
                ttl_seconds=self._settings.jwt_access_token_expire_minutes * 60,
            )
        await self._audit_repo.record(
            event_type=AuditEventType.LOGOUT,
            status=AuditEventStatus.SUCCESS,
            actor_user_id=user.id,
            target_user_id=user.id,
            metadata={"scope": "all_devices"},
        )
        await self._session.commit()

    # ------------------------------------------------------------------
    # Change password
    # ------------------------------------------------------------------

    async def change_password(
        self, *, user: User, current_password: str, new_password: str
    ) -> None:
        """Revokes every refresh token and session for `user`, including
        the one used to make this call — the caller must log in again
        afterward. A more elaborate design could reissue a fresh token
        pair for the specific session that made this request, but nothing
        in the access-token flow currently correlates "this access token"
        back to "this refresh token"; forcing a full re-login everywhere
        is the simpler, still-secure behavior for this phase."""
        if not await self._password_service.verify(user.password_hash, current_password):
            raise InvalidCredentialsError

        self._password_service.validate_policy(new_password)
        history = await self._password_history_repo.list_recent(
            user.id, self._settings.password_history_depth
        )
        await self._password_service.check_not_reused(
            new_password, [entry.password_hash for entry in history]
        )

        new_hash = await self._password_service.hash(new_password)
        now = datetime.now(UTC)
        user.password_hash = new_hash
        user.password_changed_at = now
        user.must_change_password = False
        await self._user_repo.add(user)
        await self._password_history_repo.add(
            PasswordHistory(user_id=user.id, password_hash=new_hash)
        )

        await self._refresh_token_repo.revoke_all_for_user(
            user.id, RefreshTokenRevokedReason.PASSWORD_CHANGED, now
        )
        await self._login_session_repo.revoke_all_for_user(
            user.id, LoginSessionLogoutReason.REVOKED, now
        )

        await self._audit_repo.record(
            event_type=AuditEventType.PASSWORD_CHANGED,
            status=AuditEventStatus.SUCCESS,
            actor_user_id=user.id,
            target_user_id=user.id,
        )
        await self._session.commit()

    # ------------------------------------------------------------------
    # Forgot password (self-service, OTP-based — reuses the exact same
    # OtpCode mechanism SignupService built for email verification, per
    # the explicit "don't build a second, parallel OTP system" decision)
    # ------------------------------------------------------------------

    async def request_password_reset(self, *, email: str) -> None:
        """Always returns without raising, whether or not `email` matches
        an active account — the standard "don't reveal whether an email
        is registered" principle this codebase already applies to login's
        own `InvalidCredentialsError` (see exceptions.py's module
        docstring), now applied here too. Only ACTIVE accounts get a code
        — a PENDING_*/LOCKED/SUSPENDED/REJECTED account resetting its
        password would not gain the ability to log in anyway (login's own
        status checks run first regardless), so silently no-op-ing for
        those avoids a confusing "you got a code but it didn't help"
        outcome without leaking which status a matched email is in (the
        caller-visible behavior — a generic acknowledgement — is
        identical to the no-such-email case either way)."""
        normalized_email = normalize_email(email)
        user = await self._user_repo.get_by_email(normalized_email)
        if user is None or user.status != UserStatus.ACTIVE:
            return

        now = datetime.now(UTC)
        existing = await self._otp_repo.get_active_for_user(user.id, OtpPurpose.PASSWORD_RESET)
        if existing is not None:
            elapsed = (now - existing.created_at).total_seconds()
            if elapsed < self._settings.otp_resend_cooldown_seconds:
                # Silently no-ops rather than raising — a caller hammering
                # "forgot password" for someone else's email must see the
                # exact same generic outcome whether or not a code was
                # actually (re)sent, or the timing/response difference
                # itself would leak account existence.
                return
        await self._otp_repo.invalidate_active_for_user(user.id, OtpPurpose.PASSWORD_RESET, now)

        raw_code = self._otp_service.generate_code()
        otp = OtpCode(
            user_id=user.id,
            purpose=OtpPurpose.PASSWORD_RESET,
            code_hash=self._otp_service.hash_code(raw_code),
            expires_at=now + timedelta(minutes=self._settings.otp_expire_minutes),
        )
        await self._otp_repo.add(otp)
        await self._audit_repo.record(
            event_type=AuditEventType.PASSWORD_RESET_REQUESTED,
            status=AuditEventStatus.SUCCESS,
            actor_user_id=user.id,
            target_user_id=user.id,
        )
        await self._session.commit()

        html_body = render_otp_email(
            hospital_name=self._settings.app_name,
            recipient_name=user.full_name,
            code=raw_code,
            purpose_label="reset your password",
            expires_in_minutes=self._settings.otp_expire_minutes,
        )
        await self._email_service.send(
            to=user.email,
            subject=f"Your {self._settings.app_name} password reset code",
            html_body=html_body,
        )

    async def verify_reset_otp(self, *, email: str, code: str) -> None:
        """A non-consuming check — "is this currently a valid code for
        this account's pending password reset". Deliberately does not
        mark the code consumed on success, unlike SignupService.
        verify_signup_otp: the frontend's "Set new password" screen still
        needs to present this same code to `reset_password` to actually
        change anything, and forcing the user to re-request a fresh code
        between "verify" and "set password" would serve no security
        purpose (the attempt-count/rate-limit defenses already apply
        identically to both calls) while adding real friction. Wrong
        attempts still count against `attempts` either way."""
        now = datetime.now(UTC)
        user = await self._user_repo.get_by_email(email)
        if user is None:
            raise OtpInvalidError

        otp = await self._otp_repo.get_active_for_user(user.id, OtpPurpose.PASSWORD_RESET)
        if otp is None or otp.expires_at <= now or otp.attempts >= self._settings.otp_max_attempts:
            raise OtpInvalidError

        if not self._otp_service.verify_code(otp.code_hash, code):
            await self._otp_repo.record_failed_attempt(otp)
            await self._session.commit()
            raise OtpInvalidError
        # Correct verification does not reset `attempts` and does not
        # commit anything — nothing changed; this call is safely
        # repeatable.

    async def reset_password(self, *, email: str, code: str, new_password: str) -> None:
        """The terminal action of the forgot-password flow — re-verifies
        `code` one final time (see verify_reset_otp's docstring for why
        it wasn't consumed there), then sets the new password and revokes
        every existing session/refresh token for the account, exactly
        like `change_password` does (see that method's docstring) — a
        password reset that left old sessions alive would defeat its own
        purpose."""
        now = datetime.now(UTC)
        user = await self._user_repo.get_by_email(email)
        if user is None:
            raise OtpInvalidError

        otp = await self._otp_repo.get_active_for_user(user.id, OtpPurpose.PASSWORD_RESET)
        if otp is None or otp.expires_at <= now or otp.attempts >= self._settings.otp_max_attempts:
            raise OtpInvalidError
        if not self._otp_service.verify_code(otp.code_hash, code):
            await self._otp_repo.record_failed_attempt(otp)
            await self._session.commit()
            raise OtpInvalidError

        self._password_service.validate_policy(new_password)
        history = await self._password_history_repo.list_recent(
            user.id, self._settings.password_history_depth
        )
        await self._password_service.check_not_reused(
            new_password, [entry.password_hash for entry in history]
        )

        new_hash = await self._password_service.hash(new_password)
        user.password_hash = new_hash
        user.password_changed_at = now
        user.must_change_password = False
        await self._user_repo.add(user)
        await self._password_history_repo.add(
            PasswordHistory(user_id=user.id, password_hash=new_hash)
        )
        await self._otp_repo.consume(otp, now)

        await self._refresh_token_repo.revoke_all_for_user(
            user.id, RefreshTokenRevokedReason.PASSWORD_CHANGED, now
        )
        await self._login_session_repo.revoke_all_for_user(
            user.id, LoginSessionLogoutReason.REVOKED, now
        )

        await self._audit_repo.record(
            event_type=AuditEventType.PASSWORD_RESET_COMPLETED,
            status=AuditEventStatus.SUCCESS,
            actor_user_id=user.id,
            target_user_id=user.id,
        )
        await self._session.commit()

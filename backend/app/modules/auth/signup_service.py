"""Self-service signup / email-verification business logic — one
shared self-registration flow serving every role that supports it
(Receptionist and Vitals staff as of this build; see
models.SignupRole's own docstring for how a pending account's
requested role is recorded and later resolved). Talks to
`repository.py` for persistence and to
`otp_service.py`/`password_service.py`/`app.shared.email.service` for
crypto/delivery; never touches SQLAlchemy or Argon2/SMTP primitives
directly itself, same layering discipline as `AuthService`.

Deliberately a separate class from `AuthService`, not more methods
bolted onto it: `AuthService` already coordinates six repositories plus
two crypto services for the login/refresh/session lifecycle; this is a
different application concern (account creation, not authentication of
an existing account) that happens to touch the same `User` table —
`UserService` already establishes the precedent that a second service
can own a distinct concern over `User` without folding into
`AuthService`.

Every method that mutates data ends with an explicit
`await self._session.commit()`, matching this module's established
transaction-boundary convention (see `AuthService`'s own docstring)."""

from datetime import UTC, datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import RateLimitExceededError
from app.modules.auth.exceptions import (
    EmailAlreadyRegisteredError,
    OtpInvalidError,
    PhoneNumberAlreadyRegisteredError,
)
from app.modules.auth.models import (
    AuditEventStatus,
    AuditEventType,
    OtpCode,
    OtpPurpose,
    Shift,
    SignupRole,
    User,
    UserStatus,
)
from app.modules.auth.otp_service import OtpService
from app.modules.auth.password_service import PasswordService
from app.modules.auth.repository import AuditRepository, OtpCodeRepository, UserRepository
from app.modules.auth.validators import normalize_email
from app.shared.db_errors import unique_violation_constraint_name
from app.shared.email.service import EmailService, render_otp_email

_USER_EMAIL_CONSTRAINT = "ix_user_email_active"
_USER_PHONE_CONSTRAINT = "ix_user_phone_number_active"


class SignupService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        user_repository: UserRepository,
        otp_code_repository: OtpCodeRepository,
        audit_repository: AuditRepository,
        password_service: PasswordService,
        otp_service: OtpService,
        email_service: EmailService,
    ) -> None:
        self._session = session
        self._settings = settings
        self._user_repo = user_repository
        self._otp_repo = otp_code_repository
        self._audit_repo = audit_repository
        self._password_service = password_service
        self._otp_service = otp_service
        self._email_service = email_service

    async def _issue_otp(
        self, *, user: User, purpose: OtpPurpose, now: datetime, purpose_label: str
    ) -> None:
        """Invalidates any prior unconsumed code for `(user, purpose)`
        then issues a fresh one and emails it — the one place both
        `signup`, `resend_otp`, and (from AuthService)
        `request_password_reset` create a code, so the "close the
        current one before opening a new one" discipline (OtpCode's own
        model docstring) and the email-sending call are never duplicated
        across call sites.

        Enforces `otp_resend_cooldown_seconds` against the *previous*
        active code's `created_at`, if one exists — independent of and
        in addition to the per-IP `enforce_otp_request_rate_limit`
        dependency (see that function's docstring), the same
        two-independent-layers shape `login_rate_limit_*` and
        `account_lockout_threshold` already establish. A first-ever
        issuance (signup's own initial code, or the first forgot-password
        request) has no prior code to compare against, so the cooldown
        never blocks it."""
        existing = await self._otp_repo.get_active_for_user(user.id, purpose)
        if existing is not None:
            elapsed = (now - existing.created_at).total_seconds()
            if elapsed < self._settings.otp_resend_cooldown_seconds:
                raise RateLimitExceededError(
                    retry_after_seconds=int(self._settings.otp_resend_cooldown_seconds - elapsed)
                    + 1
                )
        await self._otp_repo.invalidate_active_for_user(user.id, purpose, now)
        raw_code = self._otp_service.generate_code()
        otp = OtpCode(
            user_id=user.id,
            purpose=purpose,
            code_hash=self._otp_service.hash_code(raw_code),
            expires_at=now + timedelta(minutes=self._settings.otp_expire_minutes),
        )
        await self._otp_repo.add(otp)
        await self._session.commit()

        html_body = render_otp_email(
            hospital_name=self._settings.app_name,
            recipient_name=user.full_name,
            code=raw_code,
            purpose_label=purpose_label,
            expires_in_minutes=self._settings.otp_expire_minutes,
        )
        await self._email_service.send(
            to=user.email,
            subject=f"Your {self._settings.app_name} verification code",
            html_body=html_body,
        )

    # ------------------------------------------------------------------
    # Signup
    # ------------------------------------------------------------------

    async def signup(
        self,
        *,
        full_name: str,
        email: str,
        phone_number: str,
        password: str,
        shift: Shift,
        signup_role: SignupRole,
    ) -> User:
        """Creates a new account in `PENDING_EMAIL_VERIFICATION` — cannot
        log in until `verify_signup_otp` succeeds, then an admin approves
        it (see UserStatus's own docstring for the full state chain).
        Race-safety for the email/phone uniqueness checks mirrors
        `AuthService.register`/`UserService.create_user` exactly: a
        pre-check for the fast common case, `try`/`except IntegrityError`
        around the actual insert for whichever one loses a genuine race.

        `signup_role` is persisted as-is, not resolved to an actual Role
        row here — that resolution only matters at approval time
        (`UserService.approve_signup`), and doing it this early would
        mean looking up a Role before the account even exists, for no
        benefit (an admin could reject the signup entirely, making that
        lookup wasted work)."""
        now = datetime.now(UTC)
        normalized_email = normalize_email(email)
        if await self._user_repo.get_by_email(normalized_email) is not None:
            raise EmailAlreadyRegisteredError
        if await self._user_repo.get_by_phone_number(phone_number) is not None:
            raise PhoneNumberAlreadyRegisteredError

        self._password_service.validate_policy(password)
        password_hash = await self._password_service.hash(password)

        user = User(
            email=normalized_email,
            password_hash=password_hash,
            full_name=full_name,
            phone_number=phone_number,
            shift=shift,
            signup_role=signup_role,
            status=UserStatus.PENDING_EMAIL_VERIFICATION,
            is_email_verified=False,
            # Explicit, not left to User.must_change_password's own
            # column default (`True`) — found while enforcing that flag
            # in the 2026-08-19 audit fix pass (see
            # dependencies.py's require_permission). A self-service
            # signup chooses its own password right here; unlike an
            # admin-provisioned account (UserService.create_user) or an
            # admin-issued reset (admin_reset_password), there is no
            # system-generated temporary credential to force a change
            # away from. Leaving this unset would have force-routed
            # every self-service-signed-up Receptionist/Vitals account
            # to /change-password on its very first login the moment
            # enforcement went live, for no real security reason.
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

        await self._audit_repo.record(
            event_type=AuditEventType.USER_SIGNED_UP,
            status=AuditEventStatus.SUCCESS,
            actor_user_id=user.id,
            target_user_id=user.id,
        )
        await self._session.commit()

        await self._issue_otp(
            user=user,
            purpose=OtpPurpose.EMAIL_VERIFICATION,
            now=now,
            purpose_label="verify your email",
        )
        return user

    async def verify_signup_otp(self, *, email: str, code: str) -> User:
        """Consumes the code on success (unlike forgot-password's
        `AuthService.verify_reset_otp`, which deliberately doesn't — see
        that method's docstring): once email verification succeeds there
        is no further step that needs to re-check this same code, so
        holding it open past this call serves no purpose and would only
        widen its replay window."""
        now = datetime.now(UTC)
        user = await self._user_repo.get_by_email(email)
        # Same generic OtpInvalidError regardless of "no such user",
        # "wrong status", "no active code", "wrong code", "expired", or
        # "too many attempts" — see that exception's own docstring for
        # why none of these are distinguished in the client-visible
        # response.
        if user is None or user.status != UserStatus.PENDING_EMAIL_VERIFICATION:
            raise OtpInvalidError

        otp = await self._otp_repo.get_active_for_user(user.id, OtpPurpose.EMAIL_VERIFICATION)
        if otp is None or otp.expires_at <= now or otp.attempts >= self._settings.otp_max_attempts:
            raise OtpInvalidError

        if not self._otp_service.verify_code(otp.code_hash, code):
            await self._otp_repo.record_failed_attempt(otp)
            await self._session.commit()
            raise OtpInvalidError

        await self._otp_repo.consume(otp, now)
        user.status = UserStatus.PENDING_ADMIN_APPROVAL
        user.is_email_verified = True
        await self._user_repo.add(user)
        await self._audit_repo.record(
            event_type=AuditEventType.EMAIL_VERIFIED,
            status=AuditEventStatus.SUCCESS,
            actor_user_id=user.id,
            target_user_id=user.id,
        )
        await self._session.commit()
        return user

    async def resend_signup_otp(self, *, email: str) -> None:
        """Unlike forgot-password's resend (see AuthService.
        request_password_reset), this is honestly specific rather than
        enumeration-safe-generic: signup itself already reveals account
        existence via `EmailAlreadyRegisteredError` at the create step,
        so there is no enumeration boundary left to protect here — a
        clear "no pending signup found" is more useful to a genuine
        applicant than a generic non-answer would be."""
        now = datetime.now(UTC)
        user = await self._user_repo.get_by_email(email)
        if user is None or user.status != UserStatus.PENDING_EMAIL_VERIFICATION:
            raise OtpInvalidError
        await self._issue_otp(
            user=user,
            purpose=OtpPurpose.EMAIL_VERIFICATION,
            now=now,
            purpose_label="verify your email",
        )

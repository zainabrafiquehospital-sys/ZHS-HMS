"""SQLAlchemy models for the Authentication & Authorization module (see the
approved architecture document, §1). Registered once into
app/db/base.py's centralized model registry.

Built incrementally, one entity per approved step. Currently defined:
- User
- Role
- Permission
- RolePermission
- UserRole
- RefreshToken
- LoginSession
- PasswordHistory
- AuditLog (table: auth_audit_log)

Relationship conventions applied uniformly across this module:
- Association tables with their own lifecycle (soft delete, audit columns) —
  RolePermission, UserRole — use the SQLAlchemy "association object" pattern
  (direct relationships to/from the join model), never `secondary=`, since
  `secondary=` would hide the join row's own columns.
- Pure audit/actor FK columns (`created_by`, `updated_by`, `assigned_by`,
  `actor_user_id`, `target_user_id`) never get a `relationship()` — they
  stay plain FK columns. Backref collections like `user.created_roles`
  would be rarely useful, clutter `User`, and for the high-volume audit
  table risk an accidental unbounded collection load.
- Every relationship declares `lazy="selectin"` explicitly rather than
  relying on the default `lazy="select"`: this codebase is fully async
  (asyncpg/AsyncSession), and `selectin` is the async-safe strategy —
  plain lazy loading requires an implicit synchronous DB call that async
  SQLAlchemy cannot make outside of an explicit await.
- Collections use `cascade="save-update, merge"` explicitly (SQLAlchemy's
  own default, stated rather than implied) — never `delete-orphan`, since
  the app's deletion model is soft delete (an UPDATE) for normal use and
  DB-level `ON DELETE` for hard purges; an ORM-level cascade-delete on
  collection removal would be a surprising, unwanted third deletion path.
- Collections backed by a DB-level `ON DELETE` clause use
  `passive_deletes="all"`, not `passive_deletes=True`. `True` only
  suppresses the ORM's SELECT to load children before a parent delete —
  it still tries to null out the FK on children already loaded in the
  session, which fails outright for the `CASCADE` (`NOT NULL`) FKs in this
  module and is redundant for the `SET NULL` ones. `"all"` fully defers to
  the database's own `ON DELETE` clause in every case. Found via live
  testing: with every relationship here using `lazy="selectin"`, children
  being already-loaded at parent-delete time is the common case, not an
  edge case.
"""

from datetime import datetime
from enum import Enum as PyEnum
from ipaddress import IPv4Address, IPv6Address
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Enum,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.shared.base_entity import BaseEntity, TimestampedEntity


class UserStatus(PyEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"
    LOCKED = "locked"
    # Reserved before this feature existed (see AuthService.register's and
    # UserService.create_user's docstrings) but deliberately NOT reused for
    # self-service signup: PENDING_VERIFICATION is treated as loggable
    # everywhere it's checked (_LOGGABLE_STATUSES in service.py,
    # get_current_active_user in dependencies.py) — the opposite of what a
    # not-yet-verified signup needs. The two states below are the actual
    # self-service-signup states, both deliberately login-blocking.
    PENDING_VERIFICATION = "pending_verification"
    # Signup submitted, OTP not yet confirmed — cannot log in.
    PENDING_EMAIL_VERIFICATION = "pending_email_verification"
    # OTP confirmed, awaiting an admin's approve/reject decision — cannot
    # log in. Approval assigns a role and moves the account to ACTIVE.
    PENDING_ADMIN_APPROVAL = "pending_admin_approval"
    # An admin rejected a pending signup — cannot log in. Distinct from
    # INACTIVE (which means "was ACTIVE, later deactivated") so the audit
    # trail can always tell "never approved" apart from "approved, then
    # deactivated" — the same fine-grained-status philosophy this enum
    # already applies to LOCKED vs SUSPENDED vs INACTIVE.
    REJECTED = "rejected"


class Shift(PyEnum):
    """Which of the hospital's two operating shifts a staff account
    belongs to — collected at self-service signup (Receptionist and
    Vitals staff both use the same signup flow, see SignupService)
    since front-desk/nursing staffing is shift-based. Nullable on User:
    most accounts (admin, doctors, staff created via the
    admin-provisioned User Management flow) have no shift concept, so
    this is deliberately not required at the database level."""

    MORNING = "morning"
    NIGHT = "night"


class SignupRole(PyEnum):
    """Which role a self-service signup requested — mirrors
    signup_schemas.SignupRole exactly (this is the persisted-column
    twin of that request-schema enum, not a duplicate concept; kept as
    a separate enum here rather than importing the Pydantic one because
    this module must not depend on signup_schemas.py, the same
    layering direction every other model-vs-schema enum in this file
    already follows).

    Recorded at signup time (`SignupService.signup`) and read back by
    `UserService.approve_signup` to decide which Role to actually grant
    — before this field existed, `approve_signup` had no way to know
    which role a pending account had requested at all, and silently
    granted `Receptionist` unconditionally regardless of what the
    signup form said (see this codebase's own investigation history
    for the incident this field fixes). Nullable because admin-created
    accounts (User Management's Create User) never go through signup at
    all and have no requested role to record.

    `DOCTOR` (2026-08-24 addition): the "Doctor" Role itself already
    existed and was already in real use (via admin-provisioned User
    Management, not self-service signup) — investigated directly
    against the live database before adding this member, which found
    it sitting under the informal name `demo-doctor-demo`, the same
    kind of ad hoc leftover `demo-vitals-demo` was before Vitals'
    self-service formalization. See
    `8c263fc375ec_add_doctor_self_service_signup_role.py` for the
    rename to `Doctor` this member's `_SIGNUP_ROLE_TO_ROLE_NAME` entry
    depends on. Unlike Receptionist/Vitals, a Doctor signup carries no
    `shift` — see `User.shift`'s own docstring on doctors having no
    shift concept in this system — enforced at the request-schema level
    (`signup_schemas.SignupRequest`), not here.

    `INVENTORY_MANAGER` (2026-08-26 addition, Ward/Emergency Inventory
    Management module): unlike Doctor, there was no pre-existing ad hoc
    role here to investigate/rename — confirmed directly against both
    dev and production before writing the accompanying migration, which
    creates the "Inventory Manager" Role fresh (with its own
    `inventory:read`/`inventory:manage` grants) rather than renaming
    anything. Also shift-less, for the same reason Doctor is — confirmed
    with the user rather than assumed."""

    RECEPTIONIST = "receptionist"
    VITALS = "vitals"
    DOCTOR = "doctor"
    INVENTORY_MANAGER = "inventory_manager"


class User(BaseEntity):
    """A person who can authenticate into the system. Role membership
    (what they're allowed to do) is tracked via UserRole; this table only
    establishes identity and credential/lockout state."""

    __tablename__ = "user"
    __table_args__ = (
        Index(
            "ix_user_email_active",
            "email",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "ix_user_phone_number_active",
            "phone_number",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    email: Mapped[str] = mapped_column(String(320), nullable=False)
    phone_number: Mapped[str | None] = mapped_column(String(20))
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(150), nullable=False)
    status: Mapped[UserStatus] = mapped_column(
        Enum(
            UserStatus,
            name="user_status",
            native_enum=False,
            length=30,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
            create_constraint=True,
        ),
        nullable=False,
        default=UserStatus.PENDING_VERIFICATION,
    )
    is_email_verified: Mapped[bool] = mapped_column(default=False)
    must_change_password: Mapped[bool] = mapped_column(default=True)
    failed_login_attempts: Mapped[int] = mapped_column(SmallInteger, default=0)
    locked_until: Mapped[datetime | None] = mapped_column()
    last_login_at: Mapped[datetime | None] = mapped_column()
    last_login_ip: Mapped[IPv4Address | IPv6Address | None] = mapped_column(INET)
    password_changed_at: Mapped[datetime | None] = mapped_column()
    mfa_enabled: Mapped[bool] = mapped_column(default=False)
    # See Shift's own docstring for why this is nullable and who sets it
    # (self-service signup only, for now).
    shift: Mapped[Shift | None] = mapped_column(
        Enum(
            Shift,
            name="user_shift",
            native_enum=False,
            length=10,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
            create_constraint=True,
        ),
    )
    # See SignupRole's own docstring for why this exists and who reads
    # it (UserService.approve_signup). Nullable for the same reason
    # `shift` is — admin-provisioned accounts never signed up at all.
    signup_role: Mapped[SignupRole | None] = mapped_column(
        Enum(
            SignupRole,
            name="user_signup_role",
            native_enum=False,
            length=20,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
            create_constraint=True,
        ),
    )

    # UserRole also has `assigned_by`, a second FK to `user.id` — without
    # `foreign_keys` here, SQLAlchemy can't tell which of the two columns
    # this relationship's join should use and raises
    # AmbiguousForeignKeysError at mapper-configuration time. String form
    # because UserRole is defined later in this module.
    user_roles: Mapped[list["UserRole"]] = relationship(
        foreign_keys="UserRole.user_id",
        back_populates="user",
        cascade="save-update, merge",
        passive_deletes="all",
        lazy="selectin",
    )
    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(
        back_populates="user",
        cascade="save-update, merge",
        passive_deletes="all",
        lazy="selectin",
    )
    login_sessions: Mapped[list["LoginSession"]] = relationship(
        back_populates="user",
        cascade="save-update, merge",
        passive_deletes="all",
        lazy="selectin",
    )
    password_history: Mapped[list["PasswordHistory"]] = relationship(
        back_populates="user",
        cascade="save-update, merge",
        passive_deletes="all",
        lazy="selectin",
    )
    otp_codes: Mapped[list["OtpCode"]] = relationship(
        back_populates="user",
        cascade="save-update, merge",
        passive_deletes="all",
        lazy="selectin",
    )


class Role(BaseEntity):
    """A named bundle of permissions assignable to users (e.g. DOCTOR,
    RECEPTIONIST, ADMIN). Permission membership is tracked via
    RolePermission; this table also establishes the role's optional place
    in the role hierarchy via `parent_role_id`."""

    __tablename__ = "role"
    __table_args__ = (
        Index(
            "ix_role_name_active",
            "name",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_role_parent_role_id", "parent_role_id"),
    )

    name: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str | None] = mapped_column(Text())
    parent_role_id: Mapped[UUID | None] = mapped_column(ForeignKey("role.id", ondelete="SET NULL"))
    is_system_role: Mapped[bool] = mapped_column(default=False)
    is_active: Mapped[bool] = mapped_column(default=True)

    role_permissions: Mapped[list["RolePermission"]] = relationship(
        back_populates="role",
        cascade="save-update, merge",
        passive_deletes="all",
        lazy="selectin",
    )
    user_roles: Mapped[list["UserRole"]] = relationship(
        back_populates="role",
        cascade="save-update, merge",
        passive_deletes="all",
        lazy="selectin",
    )


class Permission(BaseEntity):
    """An atomic, checkable action (e.g. `patients:create`, `billing:refund`).
    Role membership is tracked via RolePermission; this table only
    establishes the permission itself.

    `code` is referenced throughout the application as a hardcoded string
    literal (e.g. `require_permission("patients:create")`), so it is
    immutable once created — see app/modules/auth/permission_service.py's
    module docstring for why. `group` is always the `code` prefix before
    its `:` (e.g. "patients") — never independently supplied, computed
    once at creation time (Phase 5 Step 4) and never changes thereafter,
    since `code` itself never changes. `display_name` is the
    human-readable admin-UI label (e.g. "Create Patient" for
    `patients:create`) — added in Phase 5 Step 4; `NOT NULL` at the
    schema level even though the column was added after this table
    already had rows, because the migration that added it backfills
    every pre-existing row before enforcing the constraint (see that
    migration for the backfill rule)."""

    __tablename__ = "permission"
    __table_args__ = (
        Index(
            "ix_permission_code_active",
            "code",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_permission_group", "group"),
    )

    code: Mapped[str] = mapped_column(String(100), nullable=False)
    group: Mapped[str] = mapped_column(String(50), nullable=False)
    display_name: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[str | None] = mapped_column(Text())

    role_permissions: Mapped[list["RolePermission"]] = relationship(
        back_populates="permission",
        cascade="save-update, merge",
        passive_deletes="all",
        lazy="selectin",
    )


class RolePermission(BaseEntity):
    """Association object granting a Permission to a Role. Modeled as its
    own entity (not a bare `secondary=` link table) because it participates
    in soft delete and audit-on-write like every other entity — revoking a
    permission from a role is a soft delete, preserving who granted/revoked
    what and when."""

    __tablename__ = "role_permission"
    __table_args__ = (
        Index(
            "ix_role_permission_role_id_permission_id_active",
            "role_id",
            "permission_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_role_permission_role_id", "role_id"),
        Index("ix_role_permission_permission_id", "permission_id"),
    )

    role_id: Mapped[UUID] = mapped_column(ForeignKey("role.id", ondelete="CASCADE"), nullable=False)
    permission_id: Mapped[UUID] = mapped_column(
        ForeignKey("permission.id", ondelete="CASCADE"), nullable=False
    )

    role: Mapped["Role"] = relationship(back_populates="role_permissions", lazy="selectin")
    permission: Mapped["Permission"] = relationship(
        back_populates="role_permissions", lazy="selectin"
    )


class UserRole(BaseEntity):
    """Association object granting a Role to a User. Modeled as its own
    entity (not a bare `secondary=` link table) for the same reason as
    RolePermission — soft delete and audit-on-write are first-class here —
    plus two fields with no equivalent on RolePermission: `assigned_by`
    (who granted it) and `expires_at` (for temporary role assignment,
    e.g. a locum doctor covering a shift)."""

    __tablename__ = "user_role"
    __table_args__ = (
        Index(
            "ix_user_role_user_id_role_id_active",
            "user_id",
            "role_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_user_role_user_id", "user_id"),
        Index("ix_user_role_role_id", "role_id"),
        Index(
            "ix_user_role_expires_at",
            "expires_at",
            postgresql_where=text("expires_at IS NOT NULL"),
        ),
    )

    user_id: Mapped[UUID] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    role_id: Mapped[UUID] = mapped_column(ForeignKey("role.id", ondelete="CASCADE"), nullable=False)
    assigned_by: Mapped[UUID | None] = mapped_column(ForeignKey("user.id", ondelete="SET NULL"))
    expires_at: Mapped[datetime | None] = mapped_column()

    user: Mapped["User"] = relationship(
        foreign_keys=[user_id], back_populates="user_roles", lazy="selectin"
    )
    role: Mapped["Role"] = relationship(back_populates="user_roles", lazy="selectin")


class RefreshTokenRevokedReason(PyEnum):
    LOGOUT = "logout"
    ROTATED = "rotated"
    REUSE_DETECTED = "reuse_detected"
    ADMIN_REVOKED = "admin_revoked"
    PASSWORD_CHANGED = "password_changed"


class RefreshToken(TimestampedEntity):
    """Server-side record of every refresh token ever issued. Never stores
    the raw token, only its SHA-256 hash. Uses TimestampedEntity, not
    BaseEntity: a refresh token is never soft-deleted (a background
    retention job hard-deletes rows past their expiry, out of scope for
    this phase), and it has no independent audit-actor concept — it
    belongs to exactly one user, already captured by `user_id`.

    `created_at` (from TimestampedEntity) is this token's issuance time.

    Rotation model: `family_id` groups a token with everything it's
    rotated into. `replaced_by_id` chains a token to its direct successor.
    Reusing an already-rotated token past its grace window (see
    app/core/token_rotation.py) means revoking the entire family, not just
    this row — that's the future RefreshTokenRepository's job, not
    something the schema itself can enforce."""

    __tablename__ = "refresh_token"
    __table_args__ = (
        Index("ix_refresh_token_token_hash", "token_hash", unique=True),
        Index("ix_refresh_token_family_id", "family_id"),
        Index("ix_refresh_token_expires_at", "expires_at"),
        Index(
            "ix_refresh_token_user_id_active",
            "user_id",
            postgresql_where=text("revoked_at IS NULL"),
        ),
        CheckConstraint("expires_at > created_at", name="ck_refresh_token_expires_after_issued"),
        CheckConstraint(
            "(revoked_at IS NULL) = (revoked_reason IS NULL)",
            name="ck_refresh_token_revoked_at_reason_paired",
        ),
    )

    user_id: Mapped[UUID] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    family_id: Mapped[UUID] = mapped_column(nullable=False)
    replaced_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("refresh_token.id", ondelete="SET NULL")
    )
    expires_at: Mapped[datetime] = mapped_column(nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column()
    revoked_reason: Mapped[RefreshTokenRevokedReason | None] = mapped_column(
        Enum(
            RefreshTokenRevokedReason,
            name="refresh_token_revoked_reason",
            native_enum=False,
            length=20,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
            create_constraint=True,
        )
    )
    device_info: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    ip_address: Mapped[IPv4Address | IPv6Address | None] = mapped_column(INET)

    user: Mapped["User"] = relationship(back_populates="refresh_tokens", lazy="selectin")
    login_sessions: Mapped[list["LoginSession"]] = relationship(
        back_populates="refresh_token",
        cascade="save-update, merge",
        passive_deletes="all",
        lazy="selectin",
    )


class LoginSessionLogoutReason(PyEnum):
    USER_LOGOUT = "user_logout"
    EXPIRED = "expired"
    REVOKED = "revoked"
    FORCED = "forced"


class LoginSession(TimestampedEntity):
    """Human-readable view of "who is logged in, from where" — what powers
    an "active sessions" / "log out other devices" UI. Distinct from
    RefreshToken, which is security-token bookkeeping; this is the
    user-facing session record. Uses TimestampedEntity, not BaseEntity, for
    the same reason as RefreshToken: never soft-deleted, no independent
    audit-actor concept beyond its own `user_id`.

    `created_at` (from TimestampedEntity) is this session's login time.
    `refresh_token_id` is expected to be kept pointing at the session's
    *current* token by the future AuthService as rotation happens — that
    orchestration lives in the service layer, not the schema."""

    __tablename__ = "login_session"
    __table_args__ = (
        Index(
            "ix_login_session_user_id_active",
            "user_id",
            postgresql_where=text("is_active = true"),
        ),
        Index(
            "ix_login_session_last_activity_at_active",
            "last_activity_at",
            postgresql_where=text("is_active = true"),
        ),
        CheckConstraint(
            "(logout_at IS NULL) = (logout_reason IS NULL)",
            name="ck_login_session_logout_at_reason_paired",
        ),
        CheckConstraint(
            "logout_at IS NULL OR logout_at >= created_at",
            name="ck_login_session_logout_at_after_login",
        ),
    )

    user_id: Mapped[UUID] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    refresh_token_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("refresh_token.id", ondelete="SET NULL")
    )
    ip_address: Mapped[IPv4Address | IPv6Address | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(Text())
    device_info: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    remember_me: Mapped[bool] = mapped_column(default=False)
    last_activity_at: Mapped[datetime] = mapped_column(server_default=func.now())
    logout_at: Mapped[datetime | None] = mapped_column()
    logout_reason: Mapped[LoginSessionLogoutReason | None] = mapped_column(
        Enum(
            LoginSessionLogoutReason,
            name="login_session_logout_reason",
            native_enum=False,
            length=20,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
            create_constraint=True,
        )
    )
    is_active: Mapped[bool] = mapped_column(default=True)

    user: Mapped["User"] = relationship(back_populates="login_sessions", lazy="selectin")
    refresh_token: Mapped["RefreshToken | None"] = relationship(
        back_populates="login_sessions", lazy="selectin"
    )


class PasswordHistory(TimestampedEntity):
    """Prevents password reuse. Append-only: never updated, never
    soft-deleted — a history row is a fact about the past that must never
    change. Uses TimestampedEntity: `deleted_at` on a row whose entire
    purpose is being permanent evidence would be self-defeating, and
    `created_by` is redundant with `user_id`, which already identifies
    whose password this was.

    `created_at` (from TimestampedEntity) is when this password was set."""

    __tablename__ = "password_history"
    __table_args__ = (Index("ix_password_history_user_id_created_at", "user_id", "created_at"),)

    user_id: Mapped[UUID] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    user: Mapped["User"] = relationship(back_populates="password_history", lazy="selectin")


class OtpPurpose(PyEnum):
    """One generic OTP mechanism serves both flows that need a short-lived
    email-delivered code — self-service signup email verification, and
    forgot-password — per the explicit decision to reuse rather than build
    a second, parallel OTP system. `purpose` is what keeps a code issued
    for one flow from being usable in the other, even for the same user."""

    EMAIL_VERIFICATION = "email_verification"
    PASSWORD_RESET = "password_reset"


class OtpCode(TimestampedEntity):
    """A one-time verification code, delivered by email. Uses
    TimestampedEntity, not BaseEntity, for the same reasons as
    RefreshToken (see that model's docstring): never soft-deleted (a
    future retention job purges expired rows, same as RefreshToken's own
    documented out-of-scope follow-up), and it belongs to exactly one
    user with no independent audit-actor concept.

    Never stores the raw code, only its SHA-256 hash — mirrors
    RefreshToken.token_hash exactly (see TokenService.hash_refresh_token):
    a 6-digit code is low-entropy by nature, so the actual defense against
    brute-forcing is `attempts` (this row invalidates itself after too
    many wrong tries, mirroring User.failed_login_attempts/locked_until)
    plus request-level rate limiting (see core/rate_limit.py) — not making
    the hash itself expensive to compute the way Argon2id does for
    passwords, which would add real cost without closing a 10^6-value
    search space any attacker with the hash could already brute-force
    offline regardless of hash speed.

    At most one *unconsumed* OTP per (user, purpose) at a time — enforced
    at the database level (partial unique index below), mirroring
    QueueEntry/Consultation/Invoice's identical single-active-row pattern
    elsewhere in this codebase: requesting a new code (signup resend, or a
    fresh forgot-password request) must close out any prior unconsumed one
    first, the same "close the current one before opening a new one"
    discipline QueueService.route_to already establishes."""

    __tablename__ = "otp_code"
    __table_args__ = (
        Index(
            "ix_otp_code_user_id_purpose_active",
            "user_id",
            "purpose",
            unique=True,
            postgresql_where=text("consumed_at IS NULL"),
        ),
        Index("ix_otp_code_expires_at", "expires_at"),
    )

    user_id: Mapped[UUID] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    purpose: Mapped[OtpPurpose] = mapped_column(
        Enum(
            OtpPurpose,
            name="otp_purpose",
            native_enum=False,
            length=20,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
            create_constraint=True,
        ),
        nullable=False,
    )
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column()
    attempts: Mapped[int] = mapped_column(SmallInteger, default=0)

    user: Mapped["User"] = relationship(back_populates="otp_codes", lazy="selectin")


class AuditEventType(PyEnum):
    LOGIN_SUCCESS = "login_success"
    LOGIN_FAILED = "login_failed"
    LOGOUT = "logout"
    PASSWORD_CHANGED = "password_changed"
    PASSWORD_RESET_REQUESTED = "password_reset_requested"
    PASSWORD_RESET_COMPLETED = "password_reset_completed"
    TOKEN_REFRESHED = "token_refreshed"
    TOKEN_REVOKED = "token_revoked"
    TOKEN_REUSE_DETECTED = "token_reuse_detected"
    ACCOUNT_LOCKED = "account_locked"
    ACCOUNT_UNLOCKED = "account_unlocked"
    ROLE_ASSIGNED = "role_assigned"
    ROLE_REVOKED = "role_revoked"
    # User Management (Phase 5 Step 2) — USER_ACTIVATED/USER_DEACTIVATED are
    # distinct from ACCOUNT_LOCKED/ACCOUNT_UNLOCKED above: the latter two
    # already existed for the LOCKED status specifically (an admin-imposed
    # security lock), while activate/deactivate toggle the separate
    # ACTIVE/INACTIVE state. Both pairs are needed because those are two
    # different status axes a user account moves along.
    USER_CREATED = "user_created"
    USER_UPDATED = "user_updated"
    USER_DELETED = "user_deleted"
    USER_ACTIVATED = "user_activated"
    USER_DEACTIVATED = "user_deactivated"
    PASSWORD_RESET_BY_ADMIN = "password_reset_by_admin"
    PASSWORD_CHANGE_FORCED = "password_change_forced"
    # Role Management (Phase 5 Step 3) — CRUD on the Role entity itself.
    # Distinct from ROLE_ASSIGNED/ROLE_REVOKED above, which record a
    # grant/revoke of a role on a *user* (Phase 5 Step 2), not a change
    # to the role record.
    ROLE_CREATED = "role_created"
    ROLE_UPDATED = "role_updated"
    ROLE_DELETED = "role_deleted"
    # Permission Management (Phase 5 Step 4) — CRUD on the Permission
    # entity itself.
    PERMISSION_CREATED = "permission_created"
    PERMISSION_UPDATED = "permission_updated"
    PERMISSION_DELETED = "permission_deleted"
    # Role <-> Permission Assignment (Phase 5 Step 5) — a grant/revoke of
    # a permission on a *role*, the permission-side counterpart to
    # ROLE_ASSIGNED/ROLE_REVOKED above (which are a grant/revoke of a
    # role on a *user*). Distinct from PERMISSION_CREATED/DELETED, which
    # are about the Permission record itself, not who holds it.
    PERMISSION_GRANTED = "permission_granted"
    PERMISSION_REVOKED = "permission_revoked"
    # Self-Service Signup — SignupService's own lifecycle events. Distinct
    # from USER_CREATED (an admin provisioning an account directly) —
    # this is the applicant's own action. PASSWORD_RESET_REQUESTED/
    # PASSWORD_RESET_COMPLETED below were already reserved for the
    # self-service forgot-password flow (present, unused, before this
    # feature) and are reused as-is rather than duplicated.
    USER_SIGNED_UP = "user_signed_up"
    EMAIL_VERIFIED = "email_verified"
    SIGNUP_APPROVED = "signup_approved"
    SIGNUP_REJECTED = "signup_rejected"


class AuditEventStatus(PyEnum):
    SUCCESS = "success"
    FAILURE = "failure"


class AuditLog(TimestampedEntity):
    """Immutable, queryable record of every security-relevant
    authentication event. Table name is `auth_audit_log`, not the generic
    `audit_log`, specifically so a later decision to introduce a
    module-agnostic generic audit log never collides with a table that
    already holds live compliance history (see the architecture audit's
    Blocking Issue #6). Append-only, same reasoning as PasswordHistory —
    uses TimestampedEntity, not BaseEntity.

    `created_at` (from TimestampedEntity) is when the event occurred.

    Deliberately has NO `relationship()` to User despite two FK columns —
    unlike every other table's audit-actor columns, this is itself the
    audit table: adding `user.audit_logs_as_actor` / `...as_target`
    collections would invite an accidental unbounded load against the
    highest-volume table in the schema. Query it directly, filtered and
    paginated, from the future AuditLogRepository instead."""

    __tablename__ = "auth_audit_log"
    __table_args__ = (
        Index("ix_auth_audit_log_target_user_id_created_at", "target_user_id", "created_at"),
        Index("ix_auth_audit_log_event_type_created_at", "event_type", "created_at"),
        Index("ix_auth_audit_log_actor_user_id", "actor_user_id"),
    )

    event_type: Mapped[AuditEventType] = mapped_column(
        Enum(
            AuditEventType,
            name="auth_audit_event_type",
            native_enum=False,
            length=30,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
            create_constraint=True,
        ),
        nullable=False,
    )
    actor_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("user.id", ondelete="SET NULL"))
    target_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("user.id", ondelete="SET NULL"))
    status: Mapped[AuditEventStatus] = mapped_column(
        Enum(
            AuditEventStatus,
            name="auth_audit_event_status",
            native_enum=False,
            length=10,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
            create_constraint=True,
        ),
        nullable=False,
    )
    ip_address: Mapped[IPv4Address | IPv6Address | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(Text())
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB)

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Gynecology HMS"
    app_env: str = "development"
    debug: bool = False
    api_v1_prefix: str = "/api/v1"

    # IANA zone name used to render local wall-clock times on printed
    # documents (see app/shared/printing/service.py's `_to_local_time`) —
    # every stored timestamp is UTC (Postgres `timestamptz`, decoded by
    # asyncpg as UTC-aware regardless of the database session's own
    # `TimeZone` setting); this is the single place that UTC-to-local
    # conversion is configured, not a number baked into a template.
    display_timezone: str = "Asia/Karachi"

    cors_allowed_origins: str = "http://localhost:3000"

    # The frontend's own login page — linked from the signup-approval
    # confirmation email (see app/modules/auth/user_service.py's
    # `approve_signup`). Deliberately a separate, explicit setting rather
    # than derived from `cors_allowed_origins` (a comma-separated
    # allowlist with no defined "primary" entry) — this is specifically
    # where a human should land after clicking the email, not just any
    # origin permitted to call the API.
    frontend_login_url: str = "http://localhost:3000/login"

    database_url: str
    database_sync_url: str

    redis_url: str = "redis://localhost:6379/0"

    # RS256 JWT key rotation — see app/core/jwt_keys.py. Optional with safe
    # defaults so Settings() keeps loading before any key pair is
    # provisioned; the key registry itself validates strictly, but only
    # when something actually requests a key.
    jwt_keys_dir: str = "./keys"
    jwt_active_kid: str | None = None

    # Refresh-token reuse grace window — see app/core/token_rotation.py.
    # How long after a refresh token is rotated a repeat presentation of it
    # is still treated as a benign concurrent-request race rather than a
    # reuse attack that revokes the whole token family. Bounded: a value of
    # 0 defeats the point (only exact-simultaneous requests would qualify),
    # and a large value materially widens the window in which a genuinely
    # stolen token is tolerated instead of detected.
    refresh_reuse_grace_window_seconds: int = Field(default=5, ge=1, le=60)

    # JWT claims / lifetimes — see app/modules/auth/token_service.py.
    # Access tokens stay short-lived by design (§4 of the architecture
    # document) so a compromised one self-expires quickly; refresh tokens
    # get a short default lifetime and a longer one when the caller opts
    # into "remember me".
    jwt_issuer: str = "gynecology-hms"
    jwt_audience: str = "gynecology-hms-api"
    jwt_access_token_expire_minutes: int = Field(default=15, ge=1, le=60)
    jwt_refresh_token_expire_days: int = Field(default=1, ge=1, le=90)
    jwt_refresh_token_remember_me_expire_days: int = Field(default=30, ge=1, le=365)

    # Account lockout policy — see app/modules/auth/service.py.
    # A capped, temporary lock (rather than an unbounded one) avoids turning
    # the lockout mechanism itself into a denial-of-service vector against a
    # real user, while still slowing down brute-force attempts.
    account_lockout_threshold: int = Field(default=5, ge=1, le=20)
    account_lockout_duration_minutes: int = Field(default=15, ge=1, le=1440)

    # How many previous passwords are checked to reject reuse.
    password_history_depth: int = Field(default=5, ge=1, le=20)

    # Login rate limiting — see app/core/rate_limit.py. Independent of
    # account_lockout_threshold: that throttles repeated failures against
    # one specific account, this throttles overall request volume from one
    # source regardless of which account(s) it targets, which is what
    # actually blunts credential-stuffing sweeps across many accounts.
    login_rate_limit_attempts: int = Field(default=10, ge=1, le=1000)
    login_rate_limit_window_seconds: int = Field(default=60, ge=1, le=3600)

    # Self-service signup / forgot-password OTP — see
    # app/modules/auth/otp_service.py and OtpCode's own model docstring.
    # A short expiry plus a bounded per-code attempt count are the two
    # things that actually defend a 6-digit (10^6-value) code against
    # brute-forcing; the request-level rate limits below are the second,
    # independent layer (bounds how often a *new* code can even be
    # requested/verified from one source), mirroring how
    # account_lockout_threshold and login_rate_limit_* are two
    # independent layers for login itself.
    otp_expire_minutes: int = Field(default=10, ge=1, le=60)
    otp_max_attempts: int = Field(default=5, ge=1, le=20)
    otp_resend_cooldown_seconds: int = Field(default=60, ge=10, le=600)
    otp_request_rate_limit_attempts: int = Field(default=5, ge=1, le=100)
    otp_request_rate_limit_window_seconds: int = Field(default=3600, ge=60, le=86400)
    otp_verify_rate_limit_attempts: int = Field(default=10, ge=1, le=100)
    otp_verify_rate_limit_window_seconds: int = Field(default=3600, ge=60, le=86400)

    # Outbound transactional email (OTP codes, approval confirmations) —
    # see app/shared/email/service.py. `smtp_host` unset (the default) is
    # a deliberate, documented dev fallback: EmailService logs the
    # email's content instead of sending, so the rest of the signup/OTP/
    # reset flows are fully buildable and testable before real SMTP
    # credentials (a Gmail App Password, not the account password —
    # Gmail requires this for third-party SMTP access) are provisioned.
    smtp_host: str | None = None
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_use_tls: bool = True
    smtp_from_email: str = "zainabrafiquehospital@gmail.com"
    smtp_from_name: str = "Zainab Rafique Hospital"

    log_level: str = "INFO"

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_allowed_origins.split(",") if origin.strip()]

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()

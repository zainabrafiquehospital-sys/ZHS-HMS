"""JWT access-token issuance/verification and refresh-token generation —
the other "helper module for crypto" `service.py` talks to (see
password_service.py's module docstring for the same reasoning).

Access tokens are JWTs, signed RS256 via app/core/jwt_keys.py's key
registry (never a raw secret embedded here). Refresh tokens are NOT JWTs —
per the architecture document's §4, an opaque random string is the right
shape for a token that's presented to exactly one endpoint and must be
revocable/reuse-detectable by a database lookup; only its SHA-256 hash is
ever persisted (see app/modules/auth/repository.py).

Claims deliberately exclude the user's full permission list — only role
names. Permissions can change faster than a short-lived access token is
worth invalidating for; resolving them server-side on every request (see
AuthService.get_effective_permissions in service.py) means a permission
change takes effect on the next request, not the next login.

`leeway=30` on decode absorbs ordinary clock drift between processes so a
token isn't spuriously rejected right at its expiry boundary — a High-
severity gap flagged in the architecture audit's §9 and closed here."""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt
from redis.asyncio import Redis
from uuid6 import uuid7

from app.core.config import Settings
from app.core.jwt_keys import ALGORITHM, JWTKeyRegistry
from app.modules.auth.constants import TOKEN_TYPE_ACCESS
from app.modules.auth.exceptions import TokenInvalidError

_DECODE_LEEWAY_SECONDS = 30
_BLACKLIST_KEY_PREFIX = "auth:jwt:blacklist:"


class TokenService:
    """No database access — access-token claims are handed the data they
    need by the caller (AuthService); refresh-token persistence lives in
    RefreshTokenRepository. This class only knows about JWTs, hashing, and
    the Redis-backed access-token blacklist."""

    def __init__(self, key_registry: JWTKeyRegistry, settings: Settings, redis: Redis) -> None:
        self._key_registry = key_registry
        self._settings = settings
        self._redis = redis

    def create_access_token(self, user_id: UUID, role_names: list[str]) -> tuple[str, str]:
        """Returns `(token, jti)` — the caller (AuthService) has no other
        reason to see the `jti`, but needs it to blacklist this specific
        token later (e.g. on logout-all-devices)."""
        signing_key = self._key_registry.signing_key()
        now = datetime.now(UTC)
        jti = str(uuid7())

        claims = {
            "sub": str(user_id),
            "roles": role_names,
            "jti": jti,
            "iat": now,
            "exp": now + timedelta(minutes=self._settings.jwt_access_token_expire_minutes),
            "iss": self._settings.jwt_issuer,
            "aud": self._settings.jwt_audience,
            "token_type": TOKEN_TYPE_ACCESS,
        }
        token = jwt.encode(
            claims,
            signing_key.private_key,
            algorithm=ALGORITHM,
            headers={"kid": signing_key.kid},
        )
        return token, jti

    async def decode_access_token(self, token: str) -> dict:
        """Raises `TokenInvalidError` for every failure mode uniformly
        (malformed, wrong signature, expired, wrong issuer/audience,
        unknown `kid`, blacklisted, wrong `token_type`) — the client never
        learns which, only the server-side log does, per the "no
        information leakage" principle in the architecture document's §6.
        """
        try:
            header = jwt.get_unverified_header(token)
        except jwt.InvalidTokenError as exc:
            raise TokenInvalidError from exc

        kid = header.get("kid")
        key_pair = self._key_registry.verification_key(kid) if kid else None
        if key_pair is None:
            raise TokenInvalidError

        try:
            claims = jwt.decode(
                token,
                key_pair.public_key,
                algorithms=[ALGORITHM],
                issuer=self._settings.jwt_issuer,
                audience=self._settings.jwt_audience,
                leeway=_DECODE_LEEWAY_SECONDS,
            )
        except jwt.InvalidTokenError as exc:
            raise TokenInvalidError from exc

        if claims.get("token_type") != TOKEN_TYPE_ACCESS:
            raise TokenInvalidError

        if await self.is_blacklisted(claims["jti"]):
            raise TokenInvalidError

        return claims

    def generate_refresh_token(self) -> tuple[str, str]:
        """Returns `(raw_token, token_hash)`. Only `token_hash` is ever
        persisted (see RefreshTokenRepository) — `raw_token` is the one
        and only time the caller sees the value that goes in the
        response cookie."""
        raw_token = secrets.token_urlsafe(64)
        return raw_token, self.hash_refresh_token(raw_token)

    def hash_refresh_token(self, raw_token: str) -> str:
        return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()

    async def blacklist_jti(self, jti: str, ttl_seconds: int) -> None:
        """Used only for the cases that need immediate kill of an
        otherwise-still-valid access token (logout-all-devices) rather
        than waiting out its natural short expiry — see app/core/jwt_keys.py
        and the architecture document's §4. `ttl_seconds` should be the
        token's remaining lifetime so the blacklist entry expires exactly
        when the token itself would have anyway."""
        if ttl_seconds > 0:
            await self._redis.set(f"{_BLACKLIST_KEY_PREFIX}{jti}", "1", ex=ttl_seconds)

    async def is_blacklisted(self, jti: str) -> bool:
        return bool(await self._redis.exists(f"{_BLACKLIST_KEY_PREFIX}{jti}"))

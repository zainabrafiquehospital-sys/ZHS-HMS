"""RS256 key management and rotation for JWT signing/verification.

Keys are never stored in the repository or in `.env` directly. Each key pair
lives as a PEM-encoded RSA private key file named `<kid>.pem` inside
`settings.jwt_keys_dir` — a directory mounted from a secrets volume/manager
in production, gitignored locally. The public key is derived from the
private key at load time, so only the private key file needs to be
provisioned.

Rotation model: every `*.pem` file present in the directory is a valid
*verification* key, so tokens signed before a rotation keep validating until
they naturally expire. Exactly one key, named by `settings.jwt_active_kid`,
is the *signing* key used for newly issued tokens. To rotate: generate a new
`<new-kid>.pem`, add it to the directory, point `JWT_ACTIVE_KID` at the new
kid, redeploy. Old tokens keep verifying via their original `kid` until they
expire, then the old key file can be removed.

This module only loads and exposes key material by `kid`. It performs no
JWT encoding/decoding itself — that belongs to the Authentication module
once it exists.
"""

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey, RSAPublicKey
from cryptography.hazmat.primitives.serialization import load_pem_private_key

from app.core.config import get_settings

ALGORITHM = "RS256"
MIN_KEY_SIZE_BITS = 2048


class JWTKeyConfigurationError(RuntimeError):
    """Raised when configured JWT key material is missing or invalid.

    Deliberately not a `DomainException`: this is a server misconfiguration
    to surface at startup/first-use, never a client-facing API error."""


@dataclass(frozen=True)
class JWTKeyPair:
    kid: str
    private_key: RSAPrivateKey
    public_key: RSAPublicKey


def _load_key_pair(path: Path) -> JWTKeyPair:
    kid = path.stem
    try:
        private_key = load_pem_private_key(path.read_bytes(), password=None)
    except (ValueError, TypeError) as exc:
        raise JWTKeyConfigurationError(
            f"'{path}' is not a valid, unencrypted PEM RSA private key "
            "(password-protected keys are not supported)."
        ) from exc

    if not isinstance(private_key, RSAPrivateKey):
        raise JWTKeyConfigurationError(f"'{path}' is not an RSA key ({ALGORITHM} requires RSA).")

    if private_key.key_size < MIN_KEY_SIZE_BITS:
        raise JWTKeyConfigurationError(
            f"'{path}' is a {private_key.key_size}-bit RSA key; "
            f"{ALGORITHM} requires at least {MIN_KEY_SIZE_BITS} bits."
        )

    return JWTKeyPair(kid=kid, private_key=private_key, public_key=private_key.public_key())


class JWTKeyRegistry:
    """Loads every RS256 key pair available for verification and identifies
    which one is currently used for signing."""

    def __init__(self, keys_dir: Path, active_kid: str | None) -> None:
        if not keys_dir.is_dir():
            raise JWTKeyConfigurationError(
                f"JWT keys directory '{keys_dir}' does not exist. Provision at least one RSA "
                "private key file there (see app/core/jwt_keys.py docstring)."
            )

        key_files = sorted(keys_dir.glob("*.pem"))
        if not key_files:
            raise JWTKeyConfigurationError(f"No '*.pem' key files found in '{keys_dir}'.")

        keys: dict[str, JWTKeyPair] = {}
        for path in key_files:
            pair = _load_key_pair(path)
            if pair.kid in keys:
                raise JWTKeyConfigurationError(f"Duplicate kid '{pair.kid}' in '{keys_dir}'.")
            keys[pair.kid] = pair
        self._keys = keys

        if not active_kid:
            raise JWTKeyConfigurationError("JWT_ACTIVE_KID is not configured.")
        if active_kid not in self._keys:
            raise JWTKeyConfigurationError(
                f"JWT_ACTIVE_KID '{active_kid}' has no matching '{active_kid}.pem' "
                f"in '{keys_dir}'."
            )
        self._active_kid = active_kid

    def signing_key(self) -> JWTKeyPair:
        """The single key pair used to sign newly issued tokens."""
        return self._keys[self._active_kid]

    def verification_key(self, kid: str) -> JWTKeyPair | None:
        """Looks up a key pair by `kid` to verify an incoming token,
        regardless of whether it is still the active signing key."""
        return self._keys.get(kid)


@lru_cache
def get_jwt_key_registry() -> JWTKeyRegistry:
    settings = get_settings()
    return JWTKeyRegistry(
        keys_dir=Path(settings.jwt_keys_dir),
        active_kid=settings.jwt_active_kid,
    )

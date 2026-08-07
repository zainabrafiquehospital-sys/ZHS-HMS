"""Password hashing, verification, and policy enforcement — the "hashing
helper module" the architecture document's folder structure (§8) describes
`service.py` as talking to, kept separate from `service.py` because it's a
crypto primitive, not authentication business logic.

Argon2id via argon2-cffi, per the architecture document's §5 decision:
winner of the Password Hashing Competition, memory-hard (GPU/ASIC
cracking resistant unlike bcrypt/scrypt at comparable cost), and Argon2id
specifically balances side-channel and GPU resistance better than
Argon2i/Argon2d. Parameters are pinned explicitly rather than left at
"whatever argon2-cffi's current default is" — they happen to currently
match argon2-cffi's own defaults, but stating them is what makes that a
verified fact instead of an assumption that silently drifts on a library
upgrade.

Hashing is deliberately expensive (that's the entire point of Argon2), so
running it inline would block the async event loop for the duration of
every login/register/change-password call — `asyncio.to_thread` moves the
CPU-bound work off the loop, matching "async where appropriate": the I/O
around it is async, the CPU-bound hashing itself is offloaded, not force-
wrapped in an `async def` that would still block."""

import asyncio
import secrets
import string

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from app.modules.auth.constants import TEMPORARY_PASSWORD_LENGTH
from app.modules.auth.exceptions import PasswordPolicyViolationError, PasswordReusedError
from app.modules.auth.validators import validate_password_policy

# argon2-cffi's own current defaults, stated explicitly rather than implied.
_TIME_COST = 3
_MEMORY_COST_KIB = 65536  # 64 MiB
_PARALLELISM = 4
_HASH_LEN = 32
_SALT_LEN = 16

_TEMP_PASSWORD_SYMBOLS = "!@#$%^&*-_=+"
_TEMP_PASSWORD_ALPHABET = (
    string.ascii_uppercase + string.ascii_lowercase + string.digits + _TEMP_PASSWORD_SYMBOLS
)


class PasswordService:
    """Stateless password crypto. No database access, no HTTP concerns —
    `AuthService` (service.py) is the only caller and owns everything
    about *when* these operations happen."""

    def __init__(self) -> None:
        self._hasher = PasswordHasher(
            time_cost=_TIME_COST,
            memory_cost=_MEMORY_COST_KIB,
            parallelism=_PARALLELISM,
            hash_len=_HASH_LEN,
            salt_len=_SALT_LEN,
        )
        # Computed once, off the hot path, so the login flow's
        # enumeration-timing mitigation (§8 of the architecture document)
        # has a real Argon2id hash to verify a login attempt against when
        # no matching user exists — paying the same CPU cost as a real
        # verification, not returning early with none at all.
        self._dummy_hash = self._hasher.hash("dummy-password-for-timing-parity")

    async def hash(self, password: str) -> str:
        return await asyncio.to_thread(self._hasher.hash, password)

    async def verify(self, password_hash: str, password: str) -> bool:
        try:
            return await asyncio.to_thread(self._hasher.verify, password_hash, password)
        except VerifyMismatchError:
            return False

    async def verify_dummy(self, password: str) -> None:
        """Pays the same Argon2id CPU cost as a real `verify()` call
        without needing an actual stored hash — call this on the
        not-found branch of a login attempt so a client can't distinguish
        "wrong password" from "no such account" by response latency."""
        await self.verify(self._dummy_hash, password)

    def needs_rehash(self, password_hash: str) -> bool:
        """True if `password_hash` was produced with different parameters
        than this service's current ones (e.g. after a deliberate
        parameter upgrade) — callers rehash on the next successful login
        rather than forcing every existing user to reset their password."""
        return self._hasher.check_needs_rehash(password_hash)

    def validate_policy(self, password: str) -> None:
        """Raises `PasswordPolicyViolationError` if `password` fails the
        structural policy (length, character-class diversity, common-
        password denylist). Delegates to the centralized validator so this
        rule is defined in exactly one place regardless of caller."""
        validate_password_policy(password)

    async def check_not_reused(self, password: str, history_hashes: list[str]) -> None:
        """Raises `PasswordReusedError` if `password` matches any of the
        caller-supplied previous password hashes (typically the user's
        last N from PasswordHistoryRepository.list_recent)."""
        for previous_hash in history_hashes:
            if await self.verify(previous_hash, password):
                raise PasswordReusedError

    def generate_temporary_password(self) -> str:
        """Cryptographically random password for admin-provisioned
        accounts (User Management's Create User and Admin Reset
        Password) — never chosen by a human, so it can't be weak or
        reused across accounts. Built via the stdlib `secrets` module
        (CSPRNG-backed, unlike `random`), guaranteeing one character from
        each of the four required classes and filling the rest randomly
        from the full alphabet, with a CSPRNG shuffle so the guaranteed
        characters aren't predictably positioned. Then re-validated
        against the same policy every other password goes through as a
        defensive check — the astronomically unlikely case of colliding
        with the common-password denylist is handled by simply
        generating again."""
        rng = secrets.SystemRandom()
        while True:
            required_characters = [
                secrets.choice(string.ascii_uppercase),
                secrets.choice(string.ascii_lowercase),
                secrets.choice(string.digits),
                secrets.choice(_TEMP_PASSWORD_SYMBOLS),
            ]
            remaining_length = TEMPORARY_PASSWORD_LENGTH - len(required_characters)
            remaining_characters = [
                secrets.choice(_TEMP_PASSWORD_ALPHABET) for _ in range(remaining_length)
            ]
            characters = required_characters + remaining_characters
            rng.shuffle(characters)
            password = "".join(characters)
            try:
                validate_password_policy(password)
            except PasswordPolicyViolationError:
                continue
            return password

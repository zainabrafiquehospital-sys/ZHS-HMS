"""One-time-code generation/hashing — the OTP equivalent of
password_service.py's "stateless crypto helper" shape (no database
access, no HTTP concerns; the caller — SignupService / AuthService's
forgot-password methods — owns everything about when and against what
these operations happen).

Unlike PasswordService, this has no async-offload concern: SHA-256 is
fast by design (see OtpCode's own model docstring for why a fast hash,
not Argon2id, is the right choice for a low-entropy 6-digit code whose
real defense is rate limiting + a bounded attempt counter, not hash
cost), so nothing here needs `asyncio.to_thread`."""

import hashlib
import hmac
import secrets

_OTP_DIGITS = 6
_OTP_MIN = 0
_OTP_MAX = 10**_OTP_DIGITS - 1


class OtpService:
    def generate_code(self) -> str:
        """A cryptographically random 6-digit code (CSPRNG-backed via the
        stdlib `secrets` module, not `random`), zero-padded — e.g. "004821".
        Uses `secrets.randbelow` over the full 0-999999 range rather than
        `secrets.choice` per digit, so every one of the 10^6 possible codes
        is equally likely (per-digit choice would be equivalent here, but
        this reads more directly as "pick one of a million codes")."""
        return f"{secrets.randbelow(_OTP_MAX - _OTP_MIN + 1):0{_OTP_DIGITS}d}"

    def hash_code(self, code: str) -> str:
        return hashlib.sha256(code.encode("utf-8")).hexdigest()

    def verify_code(self, code_hash: str, code: str) -> bool:
        """Constant-time comparison (`hmac.compare_digest`, not `==`) —
        same rationale as every other secret-hash comparison in this
        codebase (see token_service.py's refresh-token lookup): a naive
        `==` short-circuits on the first mismatched character, which is
        exactly the kind of timing signal that turns an offline-looking
        comparison into a practical oracle for a small search space."""
        return hmac.compare_digest(self.hash_code(code), code_hash)

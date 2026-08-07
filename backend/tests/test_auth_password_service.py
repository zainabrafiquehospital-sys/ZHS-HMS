import time

import pytest

from app.modules.auth.exceptions import PasswordPolicyViolationError, PasswordReusedError


async def test_hash_and_verify_round_trip(password_service):
    password_hash = await password_service.hash("Str0ng!Passw0rd#2026")

    assert await password_service.verify(password_hash, "Str0ng!Passw0rd#2026") is True


async def test_verify_wrong_password_returns_false_not_raises(password_service):
    password_hash = await password_service.hash("Str0ng!Passw0rd#2026")

    assert await password_service.verify(password_hash, "totally-wrong") is False


async def test_hash_uses_argon2id(password_service):
    password_hash = await password_service.hash("Str0ng!Passw0rd#2026")

    assert password_hash.startswith("$argon2id$")


async def test_verify_dummy_does_not_raise_and_pays_real_cost(password_service):
    """Regression guard for the login-flow enumeration-timing mitigation:
    verify_dummy must actually invoke a real Argon2id verification (not a
    fast no-op), or a not-found login attempt would respond measurably
    faster than a real one, defeating its purpose."""
    start = time.perf_counter()
    await password_service.verify_dummy("anything")
    elapsed = time.perf_counter() - start

    real_hash = await password_service.hash("Str0ng!Passw0rd#2026")
    start = time.perf_counter()
    await password_service.verify(real_hash, "anything")
    real_elapsed = time.perf_counter() - start

    # Both pay Argon2id's deliberate cost; neither should be near-instant.
    assert elapsed > 0.01
    assert real_elapsed > 0.01


async def test_needs_rehash_false_for_current_parameters(password_service):
    password_hash = await password_service.hash("Str0ng!Passw0rd#2026")

    assert password_service.needs_rehash(password_hash) is False


@pytest.mark.parametrize(
    "password",
    [
        "short",  # too short
        "alllowercase12",  # only 2 character classes
        "password12345",  # common password, fails even though 12+ chars
    ],
)
def test_validate_policy_rejects_weak_passwords(password_service, password):
    with pytest.raises(PasswordPolicyViolationError):
        password_service.validate_policy(password)


def test_validate_policy_accepts_strong_password(password_service):
    password_service.validate_policy("Str0ng!Passw0rd#2026")  # must not raise


async def test_check_not_reused_raises_on_match(password_service):
    password_hash = await password_service.hash("Str0ng!Passw0rd#2026")

    with pytest.raises(PasswordReusedError):
        await password_service.check_not_reused("Str0ng!Passw0rd#2026", [password_hash])


async def test_check_not_reused_passes_when_no_match(password_service):
    password_hash = await password_service.hash("Str0ng!Passw0rd#2026")

    await password_service.check_not_reused("SomethingElse!9988", [password_hash])  # no raise

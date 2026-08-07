import asyncio
from datetime import UTC, datetime, timedelta

from uuid6 import uuid7

from app.modules.auth.models import RefreshToken, RefreshTokenRevokedReason, User
from app.modules.auth.repository import RefreshTokenRepository, UserRepository
from tests.conftest import make_test_email


async def _make_user(db_session) -> User:
    user = User(
        email=make_test_email("repo-user"),
        password_hash="hash",
        full_name="Repo Test User",
    )
    return await UserRepository(db_session).add(user)


async def test_get_by_email_normalizes_case_and_whitespace(db_session):
    user = await _make_user(db_session)
    repo = UserRepository(db_session)

    found = await repo.get_by_email(f"  {user.email.upper()}  ")

    assert found is not None
    assert found.id == user.id


async def test_get_by_email_returns_none_when_missing(db_session):
    repo = UserRepository(db_session)

    assert await repo.get_by_email(make_test_email("nobody")) is None


async def test_claim_rotation_exactly_one_winner_under_concurrency(db_session):
    """The core correctness guarantee refresh-token rotation depends on:
    of N concurrent claim attempts against the same not-yet-revoked
    token, exactly one must win, regardless of how many race."""
    user = await _make_user(db_session)
    repo = RefreshTokenRepository(db_session)
    now = datetime.now(UTC)

    original = await repo.add(
        RefreshToken(
            user_id=user.id,
            token_hash="a" * 64,
            family_id=user.id,
            expires_at=now + timedelta(days=1),
        )
    )

    successors = [
        await repo.add(
            RefreshToken(
                user_id=user.id,
                token_hash=f"{i:0>63}b",
                family_id=original.family_id,
                expires_at=now + timedelta(days=1),
            )
        )
        for i in range(10)
    ]

    results = await asyncio.gather(
        *(repo.claim_rotation(original.id, successor.id, now) for successor in successors)
    )

    assert sum(results) == 1, "exactly one concurrent claim must win"

    refreshed = await repo.get_by_token_hash("a" * 64)
    assert refreshed.revoked_reason == RefreshTokenRevokedReason.ROTATED
    winning_successor_id = successors[results.index(True)].id
    assert refreshed.replaced_by_id == winning_successor_id


async def test_claim_rotation_fails_on_already_revoked_token(db_session):
    user = await _make_user(db_session)
    repo = RefreshTokenRepository(db_session)
    now = datetime.now(UTC)

    token = await repo.add(
        RefreshToken(
            user_id=user.id,
            token_hash="c" * 64,
            family_id=user.id,
            expires_at=now + timedelta(days=1),
            revoked_at=now,
            revoked_reason=RefreshTokenRevokedReason.LOGOUT,
        )
    )
    successor = await repo.add(
        RefreshToken(
            user_id=user.id,
            token_hash="d" * 64,
            family_id=user.id,
            expires_at=now + timedelta(days=1),
        )
    )

    won = await repo.claim_rotation(token.id, successor.id, now)

    assert won is False


async def test_revoke_family_revokes_only_that_family(db_session):
    user = await _make_user(db_session)
    repo = RefreshTokenRepository(db_session)
    now = datetime.now(UTC)

    family_a = await repo.add(
        RefreshToken(
            user_id=user.id,
            token_hash="e" * 64,
            family_id=user.id,
            expires_at=now + timedelta(days=1),
        )
    )
    other_family_id = uuid7()
    family_b = await repo.add(
        RefreshToken(
            user_id=user.id,
            token_hash="f" * 64,
            family_id=other_family_id,
            expires_at=now + timedelta(days=1),
        )
    )

    await repo.revoke_family(family_a.family_id, RefreshTokenRevokedReason.REUSE_DETECTED, now)

    refreshed_a = await repo.get_by_id(family_a.id)
    refreshed_b = await repo.get_by_id(family_b.id)
    assert refreshed_a.revoked_reason == RefreshTokenRevokedReason.REUSE_DETECTED
    assert refreshed_b.revoked_at is None


async def test_revoke_all_for_user_only_affects_that_user(db_session):
    user_a = await _make_user(db_session)
    user_b = User(email=make_test_email("repo-user-b"), password_hash="hash", full_name="B")
    user_repo = UserRepository(db_session)
    await user_repo.add(user_b)
    repo = RefreshTokenRepository(db_session)
    now = datetime.now(UTC)

    token_a = await repo.add(
        RefreshToken(
            user_id=user_a.id,
            token_hash="1" * 64,
            family_id=user_a.id,
            expires_at=now + timedelta(days=1),
        )
    )
    token_b = await repo.add(
        RefreshToken(
            user_id=user_b.id,
            token_hash="2" * 64,
            family_id=user_b.id,
            expires_at=now + timedelta(days=1),
        )
    )

    await repo.revoke_all_for_user(user_a.id, RefreshTokenRevokedReason.LOGOUT, now)

    assert (await repo.get_by_id(token_a.id)).revoked_at is not None
    assert (await repo.get_by_id(token_b.id)).revoked_at is None

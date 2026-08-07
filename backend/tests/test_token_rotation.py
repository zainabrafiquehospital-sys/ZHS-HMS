import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from app.core.config import Settings, get_settings
from app.core.token_rotation import (
    ReuseVerdict,
    RotatedTokenState,
    classify_reuse,
    default_grace_window,
)


@dataclass
class _FakeTokenStore:
    """Minimal in-memory stand-in for the eventual RefreshTokenRepository's
    atomic rotation claim (a conditional `UPDATE ... WHERE revoked_at IS
    NULL`). Used only to drive a realistic concurrent race in these tests —
    not part of the shipped module, which stays storage-agnostic by design."""

    revoked_at: datetime | None = None
    replaced_by_id: UUID | None = None
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def try_rotate(self) -> UUID:
        """First caller in wins and performs the rotation; every other
        concurrent caller observes it already rotated."""
        async with self._lock:
            if self.revoked_at is None:
                self.revoked_at = datetime.now(UTC)
                self.replaced_by_id = uuid4()
            return self.replaced_by_id


async def test_concurrent_rotation_race_all_losers_get_benign_replay():
    store = _FakeTokenStore()

    async def attempt_refresh() -> tuple[UUID, ReuseVerdict]:
        winning_id = await store.try_rotate()
        state = RotatedTokenState(revoked_at=store.revoked_at, replaced_by_id=store.replaced_by_id)
        verdict = classify_reuse(state, grace_window=timedelta(seconds=5))
        return winning_id, verdict

    results = await asyncio.gather(*(attempt_refresh() for _ in range(20)))

    issued_ids = {issued_id for issued_id, _ in results}
    assert len(issued_ids) == 1, "every racer must observe the same winning replacement token"
    assert all(verdict is ReuseVerdict.BENIGN_REPLAY for _, verdict in results)


async def test_reuse_outside_grace_window_is_flagged_as_attack():
    revoked_at = datetime.now(UTC) - timedelta(seconds=30)
    state = RotatedTokenState(revoked_at=revoked_at, replaced_by_id=uuid4())

    verdict = classify_reuse(state, grace_window=timedelta(seconds=5))

    assert verdict is ReuseVerdict.REUSE_ATTACK


async def test_reuse_at_exact_grace_window_boundary_is_benign():
    grace = timedelta(seconds=5)
    now = datetime.now(UTC)
    state = RotatedTokenState(revoked_at=now - grace, replaced_by_id=uuid4())

    verdict = classify_reuse(state, now=now, grace_window=grace)

    assert verdict is ReuseVerdict.BENIGN_REPLAY


async def test_reuse_just_past_grace_window_is_attack():
    grace = timedelta(seconds=5)
    now = datetime.now(UTC)
    state = RotatedTokenState(
        revoked_at=now - grace - timedelta(milliseconds=1), replaced_by_id=uuid4()
    )

    verdict = classify_reuse(state, now=now, grace_window=grace)

    assert verdict is ReuseVerdict.REUSE_ATTACK


async def test_clock_skew_where_revocation_appears_in_the_future_is_benign():
    now = datetime.now(UTC)
    state = RotatedTokenState(revoked_at=now + timedelta(seconds=10), replaced_by_id=uuid4())

    verdict = classify_reuse(state, now=now, grace_window=timedelta(seconds=5))

    assert verdict is ReuseVerdict.BENIGN_REPLAY


def test_default_grace_window_reads_from_settings(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("REFRESH_REUSE_GRACE_WINDOW_SECONDS", "12")
    try:
        assert default_grace_window() == timedelta(seconds=12)
    finally:
        get_settings.cache_clear()


def test_classify_reuse_without_explicit_grace_window_honors_configured_setting(monkeypatch):
    """Regression test: classify_reuse(state) — called the way any real
    caller would, relying on its own default — must use the configured
    REFRESH_REUSE_GRACE_WINDOW_SECONDS, not a hardcoded fallback. This is
    exactly the bug found in the final security audit: a 30s-configured
    deployment silently got 5s of leniency unless every call site
    remembered to pass grace_window explicitly."""
    get_settings.cache_clear()
    monkeypatch.setenv("REFRESH_REUSE_GRACE_WINDOW_SECONDS", "30")
    try:
        now = datetime.now(UTC)
        state = RotatedTokenState(revoked_at=now - timedelta(seconds=10), replaced_by_id=uuid4())

        verdict = classify_reuse(state, now=now)

        assert verdict is ReuseVerdict.BENIGN_REPLAY
    finally:
        get_settings.cache_clear()


@pytest.mark.parametrize("invalid_seconds", [0, -1, 61])
def test_refresh_reuse_grace_window_seconds_is_bounded(invalid_seconds):
    with pytest.raises(ValidationError):
        Settings(
            database_url="postgresql+asyncpg://u:p@localhost/db",
            database_sync_url="postgresql+psycopg2://u:p@localhost/db",
            refresh_reuse_grace_window_seconds=invalid_seconds,
        )

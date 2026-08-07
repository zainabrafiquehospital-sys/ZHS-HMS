import asyncio

import pytest

from app.core.exceptions import RateLimitExceededError
from app.core.rate_limit import RateLimiter


async def test_enforce_allows_up_to_the_limit(fake_redis):
    limiter = RateLimiter(fake_redis)

    for _ in range(5):
        await limiter.enforce(key="test-allow", limit=5, window_seconds=60)  # must not raise


async def test_enforce_raises_once_limit_is_exceeded(fake_redis):
    limiter = RateLimiter(fake_redis)

    for _ in range(5):
        await limiter.enforce(key="test-exceed", limit=5, window_seconds=60)

    with pytest.raises(RateLimitExceededError) as exc_info:
        await limiter.enforce(key="test-exceed", limit=5, window_seconds=60)

    assert 0 < exc_info.value.retry_after_seconds <= 60
    assert exc_info.value.code == "RATE_LIMIT_EXCEEDED"
    assert exc_info.value.status_code == 429


async def test_enforce_keys_are_independent(fake_redis):
    limiter = RateLimiter(fake_redis)

    for _ in range(5):
        await limiter.enforce(key="key-a", limit=5, window_seconds=60)

    await limiter.enforce(key="key-b", limit=5, window_seconds=60)  # must not raise


async def test_enforce_resets_after_the_window_expires(fake_redis):
    limiter = RateLimiter(fake_redis)

    await limiter.enforce(key="test-window", limit=1, window_seconds=1)
    with pytest.raises(RateLimitExceededError):
        await limiter.enforce(key="test-window", limit=1, window_seconds=1)

    await asyncio.sleep(1.2)

    await limiter.enforce(key="test-window", limit=1, window_seconds=1)  # must not raise

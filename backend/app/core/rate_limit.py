"""Generic Redis-backed rate limiting — a fixed-window counter, reusable
by any endpoint that needs to bound how often a given key (e.g. an IP
address) may act within a time window. This lives in app/core rather than
inside the auth module because it is not auth-specific: future modules
(password-reset requests, OTP verification, public-facing search, etc.)
will need the identical primitive.

A fixed window (rather than a sliding one) is a deliberate simplicity
trade-off: it can allow up to roughly 2x the nominal limit across a
window boundary (e.g. `limit` requests in the last second of one window
plus `limit` more in the first second of the next), which is a
well-documented property of fixed-window counters. That is acceptable
here because this limiter's job is to blunt sustained brute-force and
credential-stuffing traffic, not to enforce an exact quota — a true
sliding-window-log would cost unbounded Redis memory per key instead of
one integer plus a TTL.
"""

from redis.asyncio import Redis

from app.core.exceptions import RateLimitExceededError

_KEY_PREFIX = "ratelimit"


class RateLimiter:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def enforce(self, key: str, limit: int, window_seconds: int) -> None:
        """Records one hit for `key` and raises `RateLimitExceededError`
        if that pushes it past `limit` hits within the current
        `window_seconds` window. INCR and TTL are read back together via
        a transactional pipeline so the count and the window's remaining
        lifetime always describe the same window."""
        redis_key = f"{_KEY_PREFIX}:{key}"
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.incr(redis_key)
            pipe.ttl(redis_key)
            count, ttl = await pipe.execute()

        if ttl <= 0:
            # Either this is the first hit in a new window (INCR just
            # created the key with no expiry), or the key somehow lost
            # its TTL — either way, (re)establish the window from now.
            # A concurrent request racing this same branch just resets
            # the same TTL to the same value, which is harmless.
            await self._redis.expire(redis_key, window_seconds)
            ttl = window_seconds

        if count > limit:
            raise RateLimitExceededError(retry_after_seconds=ttl)

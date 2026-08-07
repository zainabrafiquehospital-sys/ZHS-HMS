from collections.abc import AsyncGenerator

from fastapi import Depends
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rate_limit import RateLimiter
from app.db.session import async_session_factory
from app.redis.client import get_redis_client


async def get_db() -> AsyncGenerator[AsyncSession]:
    async with async_session_factory() as session:
        yield session


def get_rate_limiter(redis: Redis = Depends(get_redis_client)) -> RateLimiter:
    return RateLimiter(redis)

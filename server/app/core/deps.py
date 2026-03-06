from typing import Annotated

from fastapi import Depends
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.redis import get_redis, get_pubsub_redis
from app.core.rate_limiter import APIRateLimiter, ExchangeRateLimiter


def get_api_rate_limiter(redis: Redis = Depends(get_redis)) -> APIRateLimiter:
    return APIRateLimiter(redis)


def get_exchange_rate_limiter(redis: Redis = Depends(get_redis)) -> ExchangeRateLimiter:
    return ExchangeRateLimiter(redis)


# Type aliases for dependency injection
DbSession = Annotated[AsyncSession, Depends(get_db)]
RedisClient = Annotated[Redis, Depends(get_redis)]
PubSubRedisClient = Annotated[Redis, Depends(get_pubsub_redis)]
ApiRateLimiter = Annotated[APIRateLimiter, Depends(get_api_rate_limiter)]
ExchangeLimiter = Annotated[ExchangeRateLimiter, Depends(get_exchange_rate_limiter)]

# Auth dependencies will be added here:
# CurrentUser = Annotated[User, Depends(get_current_user)]
# CurrentUserOptional = Annotated[User | None, Depends(get_current_user_optional)]

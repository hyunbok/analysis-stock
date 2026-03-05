import redis.asyncio as redis
from redis.asyncio import Redis

_redis_client: Redis | None = None


async def init_redis(redis_url: str) -> None:
    global _redis_client
    _redis_client = redis.from_url(
        redis_url,
        encoding="utf-8",
        decode_responses=True,
    )
    await _redis_client.ping()


def get_redis() -> Redis:
    if _redis_client is None:
        raise RuntimeError("Redis client not initialized. Call init_redis first.")
    return _redis_client


async def close_redis() -> None:
    global _redis_client
    if _redis_client is not None:
        await _redis_client.aclose()
        _redis_client = None

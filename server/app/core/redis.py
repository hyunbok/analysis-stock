import redis.asyncio as redis
from redis.asyncio import Redis
from redis.asyncio.connection import ConnectionPool
from redis.backoff import ExponentialBackoff
from redis.retry import Retry

_redis_client: Redis | None = None
_pubsub_client: Redis | None = None

# Exponential Backoff: 0.5s base, 10s cap, 3 retries
_RETRY = Retry(ExponentialBackoff(cap=10, base=0.5), retries=3)


async def init_redis(redis_url: str) -> None:
    """일반 캐시/Rate Limit 풀 + Pub/Sub 전용 풀 초기화."""
    global _redis_client, _pubsub_client

    # 일반 풀: max_connections=50, timeout=5s
    _redis_client = redis.from_url(
        redis_url,
        encoding="utf-8",
        decode_responses=True,
        max_connections=50,
        socket_connect_timeout=5,
        socket_timeout=5,
        retry=_RETRY,
        retry_on_timeout=True,
    )
    await _redis_client.ping()

    # Pub/Sub 전용 풀: max_connections=20, socket_timeout=None (블로킹 listen)
    _pubsub_client = redis.from_url(
        redis_url,
        encoding="utf-8",
        decode_responses=True,
        max_connections=20,
        socket_connect_timeout=5,
        socket_timeout=None,
        retry=_RETRY,
        retry_on_timeout=False,
    )
    await _pubsub_client.ping()


def get_redis() -> Redis:
    if _redis_client is None:
        raise RuntimeError("Redis client not initialized. Call init_redis first.")
    return _redis_client


def get_pubsub_redis() -> Redis:
    """Pub/Sub 전용 Redis 클라이언트 반환 (socket_timeout=None)."""
    if _pubsub_client is None:
        raise RuntimeError("Redis pubsub client not initialized. Call init_redis first.")
    return _pubsub_client


async def close_redis() -> None:
    global _redis_client, _pubsub_client
    if _redis_client is not None:
        await _redis_client.aclose()
        _redis_client = None
    if _pubsub_client is not None:
        await _pubsub_client.aclose()
        _pubsub_client = None

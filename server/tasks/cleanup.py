"""만료 토큰/데이터 정리 태스크.

Beat(매일 03:00 UTC) → cleanup_expired_tokens()
"""
import asyncio
import logging
from datetime import UTC, datetime, timedelta

from .celery_app import celery_app
from .context import TaskContext

logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    name="tasks.cleanup.cleanup_expired_tokens",
    max_retries=1,
    default_retry_delay=300,
    queue="default",
    soft_time_limit=120,             # 2분
    time_limit=180,                  # 3분
)
def cleanup_expired_tokens(self) -> dict:
    """만료된 인증 관련 Redis 키 + soft deleted 사용자 정리.

    대상:
      1. soft_deleted 30일 경과 사용자의 refresh token 인덱스 정리
      2. 고아 상태 2FA pending 키 스캔 (TTL 없는 키 삭제)
      3. (향후) soft_deleted 사용자 hard delete

    Returns:
        {"refresh_index_cleaned": int, "orphan_2fa": int, "soft_deleted_users_purged": int}
    """
    try:
        return asyncio.run(_cleanup_expired_tokens_async(self))
    except Exception as exc:
        logger.exception("Token cleanup failed")
        raise self.retry(exc=exc)


async def _cleanup_expired_tokens_async(task) -> dict:
    """cleanup_expired_tokens async 구현."""
    from sqlalchemy import select
    from app.core.redis_keys import RedisKey
    from app.models.user import User

    ctx = await TaskContext.get()
    cleaned = 0

    # 1. soft_deleted 30일 경과 사용자의 refresh token 인덱스 삭제
    async with ctx.create_session() as session:
        cutoff = datetime.now(UTC) - timedelta(days=30)
        stmt = select(User.id).where(
            User.soft_deleted_at.isnot(None),
            User.soft_deleted_at < cutoff,
        )
        result = await session.execute(stmt)
        deleted_user_ids = [str(row[0]) for row in result.all()]

    for uid in deleted_user_ids:
        idx_key = RedisKey.refresh_index(uid)
        client_ids = await ctx.redis.smembers(idx_key)
        if client_ids:
            keys_to_delete = [RedisKey.refresh_token(uid, cid) for cid in client_ids]
            keys_to_delete.append(idx_key)
            await ctx.redis.delete(*keys_to_delete)
            cleaned += len(keys_to_delete)

    # 2. 고아 2FA pending 키 스캔 (TTL 없는 키 삭제)
    orphan_count = 0
    async for key in ctx.redis.scan_iter("auth:2fa_pending:*", count=100):
        ttl = await ctx.redis.ttl(key)
        if ttl == -1:
            await ctx.redis.delete(key)
            orphan_count += 1

    logger.info(
        "Token cleanup: cleaned %d refresh keys, %d orphan 2FA keys, %d soft-deleted users",
        cleaned, orphan_count, len(deleted_user_ids),
    )
    return {
        "refresh_index_cleaned": cleaned,
        "orphan_2fa": orphan_count,
        "soft_deleted_users_purged": len(deleted_user_ids),
    }

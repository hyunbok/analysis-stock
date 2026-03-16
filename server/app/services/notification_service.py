"""알림 기록 조회/읽음/미읽 카운트 서비스."""
from __future__ import annotations

import uuid
from datetime import UTC

from redis.asyncio import Redis

from app.core.exceptions import NotificationErrors
from app.core.pubsub import RedisPublisher
from app.core.redis_keys import RedisKey, RedisTTL
from app.documents.notifications import Notification
from app.repositories.notification_repository import NotificationRepository
from app.schemas.notification import NotificationListResponse, NotificationResponse


class NotificationService:
    def __init__(
        self,
        notification_repo: NotificationRepository,
        redis: Redis,
        publisher: RedisPublisher,
    ) -> None:
        self._repo = notification_repo
        self._redis = redis
        self._publisher = publisher

    async def list_notifications(
        self,
        user_id: uuid.UUID,
        type_filter: str | None,
        cursor,
        limit: int,
    ) -> NotificationListResponse:
        """커서 기반 페이지네이션 목록 조회."""
        notifications = await self._repo.list_by_user(
            user_id, type_filter=type_filter, cursor=cursor, limit=limit
        )
        next_cursor: str | None = None
        if len(notifications) == limit:
            last = notifications[-1]
            next_cursor = (
                last.created_at.astimezone(UTC)
                .isoformat(timespec="seconds")
                .replace("+00:00", "Z")
            )

        unread_count = await self.get_unread_count(user_id)
        return NotificationListResponse(
            notifications=[_to_response(n) for n in notifications],
            next_cursor=next_cursor,
            unread_count=unread_count,
        )

    async def mark_as_read(self, user_id: uuid.UUID, notification_id: str) -> None:
        """단건 읽음 처리 + Redis DECR."""
        notification = await self._repo.get_by_id(notification_id)
        if notification is None:
            raise NotificationErrors.not_found()
        if notification.user_id != user_id:
            raise NotificationErrors.access_denied()
        if notification.is_read:
            return

        await self._repo.mark_read(notification_id)

        # Redis 카운터 DECR (0 이하 방지)
        key = RedisKey.unread_count(str(user_id))
        current = await self._redis.get(key)
        if current is not None:
            new_val = max(0, int(current) - 1)
            await self._redis.setex(key, RedisTTL.UNREAD_COUNT, new_val)

    async def mark_all_as_read(self, user_id: uuid.UUID) -> int:
        """전체 읽음 처리 + Redis DEL."""
        marked = await self._repo.mark_all_read(user_id)
        await self._redis.delete(RedisKey.unread_count(str(user_id)))
        return marked

    async def get_unread_count(self, user_id: uuid.UUID) -> int:
        """Redis → 없으면 MongoDB count → SETEX."""
        key = RedisKey.unread_count(str(user_id))
        cached = await self._redis.get(key)
        if cached is not None:
            return int(cached)
        count = await self._repo.count_unread(user_id)
        await self._redis.setex(key, RedisTTL.UNREAD_COUNT, count)
        return count

    async def create_notification(
        self,
        user_id: uuid.UUID,
        type: str,
        title: str,
        body: str,
        data: dict | None = None,
    ) -> Notification:
        """알림 생성 + Redis INCR + Pub/Sub 발행."""
        notification = await self._repo.create(
            user_id=user_id, type=type, title=title, body=body, data=data
        )
        # Redis 미읽 카운트 INCR
        key = RedisKey.unread_count(str(user_id))
        await self._redis.incr(key)
        await self._redis.expire(key, RedisTTL.UNREAD_COUNT, nx=True)

        # Pub/Sub 발행 (WS → 클라이언트 배지 업데이트)
        await self._publisher.publish_notification(
            str(user_id),
            {
                "notification_id": str(notification.id),
                "type": type,
                "title": title,
                "body": body,
                "data": data,
                "is_read": False,
            },
        )
        return notification


def _to_response(n: Notification) -> NotificationResponse:
    return NotificationResponse(
        notification_id=str(n.id),
        type=n.type,
        title=n.title,
        body=n.body,
        data=n.data,
        is_read=n.is_read,
        created_at=n.created_at,
    )

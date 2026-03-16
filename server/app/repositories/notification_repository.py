"""알림 기록 DB 접근 계층 (MongoDB/Beanie)."""
from __future__ import annotations

import uuid
from datetime import datetime

from beanie import PydanticObjectId
from pymongo import DESCENDING

from app.documents.notifications import Notification


class NotificationRepository:
    """Beanie Document 직접 호출을 서비스에서 분리 (일관성 패턴)."""

    async def create(
        self,
        *,
        user_id: uuid.UUID,
        type: str,
        title: str,
        body: str,
        data: dict | None = None,
    ) -> Notification:
        """Notification INSERT."""
        notification = Notification(
            user_id=user_id,
            type=type,
            title=title,
            body=body,
            data=data,
        )
        await notification.insert()
        return notification

    async def get_by_id(self, notification_id: str) -> Notification | None:
        """ObjectId 문자열 → Notification 조회."""
        try:
            oid = PydanticObjectId(notification_id)
        except Exception:
            return None
        return await Notification.get(oid)

    async def list_by_user(
        self,
        user_id: uuid.UUID,
        *,
        type_filter: str | None = None,
        cursor: datetime | None = None,
        limit: int = 20,
    ) -> list[Notification]:
        """커서 기반 페이지네이션. created_at DESC.
        cursor 있으면: created_at < cursor."""
        query = Notification.find(Notification.user_id == user_id)
        if type_filter:
            query = query.find(Notification.type == type_filter)
        if cursor:
            query = query.find(Notification.created_at < cursor)
        results = (
            await query.sort([("created_at", DESCENDING)]).limit(limit).to_list()
        )
        return results

    async def mark_read(self, notification_id: str) -> bool:
        """is_read = True. Returns: modified."""
        notification = await self.get_by_id(notification_id)
        if notification is None:
            return False
        if notification.is_read:
            return True
        await notification.set({Notification.is_read: True})
        return True

    async def mark_all_read(self, user_id: uuid.UUID) -> int:
        """user_id + is_read=False → True. Returns: modified_count."""
        result = await Notification.find(
            Notification.user_id == user_id,
            Notification.is_read == False,  # noqa: E712
        ).update({"$set": {"is_read": True}})
        return result.modified_count if result else 0

    async def count_unread(self, user_id: uuid.UUID) -> int:
        """user_id + is_read=False 카운트."""
        return await Notification.find(
            Notification.user_id == user_id,
            Notification.is_read == False,  # noqa: E712
        ).count()

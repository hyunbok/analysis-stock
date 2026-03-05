from datetime import datetime, UTC
from typing import Optional
from uuid import UUID

import pymongo
from beanie import Document, Indexed
from pydantic import Field


class Notification(Document):
    user_id: Indexed(UUID)
    type: str  # price_alert / ai_trading / order_execution
    title: str = Field(max_length=100)
    body: str = Field(max_length=500)
    data: Optional[dict] = None
    is_read: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    class Settings:
        name = "notifications"
        indexes = [
            pymongo.IndexModel(
                [("user_id", pymongo.ASCENDING), ("is_read", pymongo.ASCENDING)],
            ),
            pymongo.IndexModel(
                [("user_id", pymongo.ASCENDING), ("created_at", pymongo.DESCENDING)],
            ),
            pymongo.IndexModel(
                [("created_at", pymongo.ASCENDING)],
                expireAfterSeconds=7776000,  # 90 days TTL
            ),
            # Composite: 읽지 않은 알림 최신순 조회 (3-field)
            pymongo.IndexModel(
                [("user_id", pymongo.ASCENDING), ("is_read", pymongo.ASCENDING), ("created_at", pymongo.DESCENDING)],
                name="notifications_user_read_created",
            ),
        ]

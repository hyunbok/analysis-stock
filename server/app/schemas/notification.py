"""알림 기록 응답 스키마."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class NotificationResponse(BaseModel):
    notification_id: str       # MongoDB ObjectId as string
    type: str                  # "price_alert" | "ai_trading" | "order_execution"
    title: str
    body: str
    data: dict | None
    is_read: bool
    created_at: datetime


class NotificationListResponse(BaseModel):
    notifications: list[NotificationResponse]
    next_cursor: str | None    # ISO datetime string, None = 마지막 페이지
    unread_count: int


class UnreadCountResponse(BaseModel):
    unread_count: int


class MarkAllReadResponse(BaseModel):
    marked: int

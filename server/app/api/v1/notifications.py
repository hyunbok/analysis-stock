"""알림 기록 조회 및 읽음 처리 API 엔드포인트."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Query

from app.core.deps import CurrentUser, NotificationServiceDep
from app.schemas.common import ApiResponse
from app.schemas.notification import (
    MarkAllReadResponse,
    NotificationListResponse,
    UnreadCountResponse,
)

router = APIRouter()


# 경로 충돌 방지: 정적 경로 먼저 등록

@router.get("/unread-count", response_model=ApiResponse[UnreadCountResponse])
async def get_unread_count(
    current_user: CurrentUser,
    service: NotificationServiceDep,
) -> ApiResponse[UnreadCountResponse]:
    """미읽 알림 카운트 조회 (Redis 캐시 우선)."""
    count = await service.get_unread_count(current_user.id)
    return ApiResponse(data=UnreadCountResponse(unread_count=count))


@router.patch("/mark-all-read", response_model=ApiResponse[MarkAllReadResponse])
async def mark_all_read(
    current_user: CurrentUser,
    service: NotificationServiceDep,
) -> ApiResponse[MarkAllReadResponse]:
    """전체 알림 읽음 처리."""
    marked = await service.mark_all_as_read(current_user.id)
    return ApiResponse(data=MarkAllReadResponse(marked=marked))


@router.get("", response_model=ApiResponse[NotificationListResponse])
async def list_notifications(
    current_user: CurrentUser,
    service: NotificationServiceDep,
    type: str | None = Query(
        default=None, alias="type", description="알림 타입 필터 (price_alert 등)"
    ),
    limit: int = Query(default=20, ge=1, le=100),
    cursor: str | None = Query(
        default=None, description="ISO 8601 datetime — 이전 응답의 next_cursor"
    ),
) -> ApiResponse[NotificationListResponse]:
    """알림 목록 조회 (커서 기반 페이지네이션)."""
    cursor_dt: datetime | None = None
    if cursor:
        try:
            cursor_dt = datetime.fromisoformat(cursor.replace("Z", "+00:00"))
        except ValueError:
            cursor_dt = None

    result = await service.list_notifications(
        user_id=current_user.id,
        type_filter=type,
        cursor=cursor_dt,
        limit=limit,
    )
    return ApiResponse(data=result)


@router.patch("/{notification_id}/mark-read", response_model=ApiResponse[None])
async def mark_read(
    notification_id: str,
    current_user: CurrentUser,
    service: NotificationServiceDep,
) -> ApiResponse[None]:
    """단건 알림 읽음 처리."""
    await service.mark_as_read(current_user.id, notification_id)
    return ApiResponse(data=None)

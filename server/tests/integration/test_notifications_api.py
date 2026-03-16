"""알림 기록 조회/읽음 API 통합 테스트 — /api/v1/notifications.

설계서: docs/tasks/v1-21-price-alert-system-plan.md §4.2
패턴:  test_orders_api.py와 동일 — 서비스 계층 Mock + HTTP 검증
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.exceptions import NotificationErrors
from app.middleware.correlation_id import CorrelationIdMiddleware
from app.middleware.error_handler import register_error_handlers
from app.models.user import User
from app.schemas.notification import (
    NotificationListResponse,
    NotificationResponse,
    UnreadCountResponse,
)


# ── 헬퍼 ─────────────────────────────────────────────────────────────────────


def _make_user(email: str = "test@example.com") -> User:
    user = MagicMock(spec=User)
    user.id = uuid.uuid4()
    user.email = email
    user.nickname = "테스터"
    user.email_verified_at = datetime.now(UTC)
    user.soft_deleted_at = None
    return user


def _make_notification_response(
    notification_id: str = "64f1a2b3c4d5e6f7a8b9c0d1",
    type: str = "price_alert",
    is_read: bool = False,
) -> NotificationResponse:
    return NotificationResponse(
        notification_id=notification_id,
        type=type,
        title="BTC/KRW 목표가 도달",
        body="BTC/KRW이(가) 85,000,000원에 도달했습니다.",
        data={
            "alert_id": str(uuid.uuid4()),
            "coin_symbol": "BTC/KRW",
            "exchange_type": "upbit",
            "condition": "above",
            "target_price": "85000000",
            "current_price": "85100000",
        },
        is_read=is_read,
        created_at=datetime.now(UTC),
    )


def _make_list_response(
    notifications: list[NotificationResponse] | None = None,
    next_cursor: str | None = None,
    unread_count: int = 0,
) -> NotificationListResponse:
    return NotificationListResponse(
        notifications=notifications or [],
        next_cursor=next_cursor,
        unread_count=unread_count,
    )


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_notification_service() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def mock_user() -> User:
    return _make_user()


def _build_app(
    mock_service: AsyncMock,
    current_user: User | None = None,
) -> FastAPI:
    from app.api.v1.notifications import router as notifications_router
    from app.core.deps import get_current_user, get_notification_service

    app = FastAPI()
    register_error_handlers(app)
    app.add_middleware(CorrelationIdMiddleware)
    app.include_router(notifications_router, prefix="/notifications")

    app.dependency_overrides[get_notification_service] = lambda: mock_service
    if current_user is not None:
        app.dependency_overrides[get_current_user] = lambda: current_user
    return app


@pytest.fixture
def test_app(mock_notification_service: AsyncMock, mock_user: User) -> FastAPI:
    return _build_app(mock_notification_service, current_user=mock_user)


@pytest.fixture
def test_app_no_auth(mock_notification_service: AsyncMock) -> FastAPI:
    return _build_app(mock_notification_service, current_user=None)


@pytest.fixture
async def client(test_app: FastAPI) -> AsyncClient:
    async with AsyncClient(
        transport=ASGITransport(app=test_app), base_url="http://test"
    ) as c:
        yield c


@pytest.fixture
async def anon_client(test_app_no_auth: FastAPI) -> AsyncClient:
    async with AsyncClient(
        transport=ASGITransport(app=test_app_no_auth), base_url="http://test"
    ) as c:
        yield c


# ── 인증 검증 ─────────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_list_notifications_unauthenticated_returns_401(
    anon_client: AsyncClient,
):
    """인증 없이 알림 목록 조회 → 401."""
    resp = await anon_client.get("/notifications")
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_mark_read_unauthenticated_returns_401(anon_client: AsyncClient):
    """인증 없이 읽음 처리 → 401."""
    resp = await anon_client.patch(
        f"/notifications/{uuid.uuid4()}/mark-read"
    )
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_mark_all_read_unauthenticated_returns_401(anon_client: AsyncClient):
    """인증 없이 전체 읽음 → 401."""
    resp = await anon_client.patch("/notifications/mark-all-read")
    assert resp.status_code == 401


# ── GET /notifications — 알림 목록 ───────────────────────────────────────────


@pytest.mark.anyio
async def test_list_notifications_returns_200_with_items(
    client: AsyncClient, mock_notification_service: AsyncMock
):
    """알림 목록 조회 → 200 + notifications + unread_count + next_cursor."""
    notifications = [
        _make_notification_response("id1"),
        _make_notification_response("id2"),
    ]
    mock_notification_service.list_notifications.return_value = _make_list_response(
        notifications=notifications, unread_count=2
    )

    resp = await client.get("/notifications")

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert isinstance(data["notifications"], list)
    assert len(data["notifications"]) == 2
    assert data["unread_count"] == 2
    assert "next_cursor" in data
    assert resp.json()["error"] is None


@pytest.mark.anyio
async def test_list_notifications_type_filter_applied(
    client: AsyncClient, mock_notification_service: AsyncMock
):
    """type=price_alert 필터 → 서비스에 전달."""
    mock_notification_service.list_notifications.return_value = _make_list_response()

    resp = await client.get("/notifications", params={"type": "price_alert"})

    assert resp.status_code == 200
    mock_notification_service.list_notifications.assert_called_once()


@pytest.mark.anyio
async def test_list_notifications_cursor_pagination(
    client: AsyncClient, mock_notification_service: AsyncMock
):
    """cursor 기반 페이지네이션 파라미터 전달."""
    cursor = "2026-03-16T10:00:00Z"
    mock_notification_service.list_notifications.return_value = _make_list_response()

    resp = await client.get("/notifications", params={"cursor": cursor})

    assert resp.status_code == 200


@pytest.mark.anyio
async def test_list_notifications_empty_returns_empty(
    client: AsyncClient, mock_notification_service: AsyncMock
):
    """알림 없을 때 → 200 + 빈 목록 + next_cursor=None."""
    mock_notification_service.list_notifications.return_value = _make_list_response()

    resp = await client.get("/notifications")

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["notifications"] == []
    assert data["next_cursor"] is None


@pytest.mark.anyio
async def test_list_notifications_item_has_required_fields(
    client: AsyncClient, mock_notification_service: AsyncMock
):
    """알림 아이템에 필수 필드 포함 확인."""
    notifications = [_make_notification_response()]
    mock_notification_service.list_notifications.return_value = _make_list_response(
        notifications=notifications
    )

    resp = await client.get("/notifications")

    item = resp.json()["data"]["notifications"][0]
    required = [
        "notification_id", "type", "title", "body",
        "data", "is_read", "created_at",
    ]
    for field in required:
        assert field in item, f"필드 누락: {field}"


# ── GET /notifications/unread-count ───────────────────────────────────────────


@pytest.mark.anyio
async def test_get_unread_count_returns_200_with_count(
    client: AsyncClient, mock_notification_service: AsyncMock
):
    """미읽 카운트 조회 → 200 + unread_count."""
    mock_notification_service.get_unread_count.return_value = 5

    resp = await client.get("/notifications/unread-count")

    assert resp.status_code == 200
    assert resp.json()["data"]["unread_count"] == 5


# ── PATCH /notifications/{id}/mark-read ──────────────────────────────────────


@pytest.mark.anyio
async def test_mark_notification_read_returns_200(
    client: AsyncClient, mock_notification_service: AsyncMock
):
    """읽음 처리 → 200."""
    mock_notification_service.mark_as_read.return_value = None

    resp = await client.patch(
        "/notifications/64f1a2b3c4d5e6f7a8b9c0d1/mark-read"
    )

    assert resp.status_code == 200
    assert resp.json()["error"] is None


@pytest.mark.anyio
async def test_mark_notification_read_not_found_returns_404(
    client: AsyncClient, mock_notification_service: AsyncMock
):
    """미존재 알림 읽음 처리 → 404."""
    mock_notification_service.mark_as_read.side_effect = (
        NotificationErrors.not_found()
    )

    resp = await client.patch(
        "/notifications/nonexistent_id/mark-read"
    )

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "NOTIFICATION_NOT_FOUND"


@pytest.mark.anyio
async def test_mark_notification_read_access_denied_returns_403(
    client: AsyncClient, mock_notification_service: AsyncMock
):
    """타인 알림 읽음 처리 → 403."""
    mock_notification_service.mark_as_read.side_effect = (
        NotificationErrors.access_denied()
    )

    resp = await client.patch(
        "/notifications/64f1a2b3c4d5e6f7a8b9c0d1/mark-read"
    )

    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "NOTIFICATION_ACCESS_DENIED"


# ── PATCH /notifications/mark-all-read ───────────────────────────────────────


@pytest.mark.anyio
async def test_mark_all_read_returns_200_with_marked_count(
    client: AsyncClient, mock_notification_service: AsyncMock
):
    """전체 읽음 → 200 + marked 카운트."""
    mock_notification_service.mark_all_as_read.return_value = 5

    resp = await client.patch("/notifications/mark-all-read")

    assert resp.status_code == 200
    assert resp.json()["data"]["marked"] == 5
    assert resp.json()["error"] is None


@pytest.mark.anyio
async def test_mark_all_read_no_unread_returns_zero(
    client: AsyncClient, mock_notification_service: AsyncMock
):
    """읽지 않은 알림 없음 → 200 + marked=0."""
    mock_notification_service.mark_all_as_read.return_value = 0

    resp = await client.patch("/notifications/mark-all-read")

    assert resp.status_code == 200
    assert resp.json()["data"]["marked"] == 0


# ── 응답 포맷 공통 검증 ────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_success_response_has_meta_timestamp(
    client: AsyncClient, mock_notification_service: AsyncMock
):
    """성공 응답에 meta.timestamp 포함."""
    mock_notification_service.list_notifications.return_value = _make_list_response()

    resp = await client.get("/notifications")

    assert "meta" in resp.json()
    assert "timestamp" in resp.json()["meta"]

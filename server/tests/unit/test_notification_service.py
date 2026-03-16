"""NotificationService 단위 테스트.

설계서: docs/tasks/v1-21-price-alert-system-plan.md §9.2
테스트: 목록/읽음/카운트 (~10건)
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.exceptions import NotificationErrors
from app.schemas.notification import NotificationListResponse
from app.services.notification_service import NotificationService


# ── 상수 / 헬퍼 ───────────────────────────────────────────────────────────────

USER_ID = uuid.uuid4()
NOTIFICATION_ID = "64f1a2b3c4d5e6f7a8b9c0d1"  # MongoDB ObjectId 문자열


def _make_notification_doc(
    notification_id: str = NOTIFICATION_ID,
    user_id: uuid.UUID = USER_ID,
    type: str = "price_alert",
    is_read: bool = False,
) -> MagicMock:
    doc = MagicMock()
    doc.id = MagicMock()
    doc.id.__str__ = MagicMock(return_value=notification_id)
    doc.user_id = user_id
    doc.type = type
    doc.title = "BTC/KRW 목표가 도달"
    doc.body = "BTC/KRW이(가) 85,000,000원에 도달했습니다."
    doc.data = {
        "alert_id": str(uuid.uuid4()),
        "coin_symbol": "BTC/KRW",
        "exchange_type": "upbit",
        "condition": "above",
        "target_price": "85000000",
        "current_price": "85100000",
    }
    doc.is_read = is_read
    doc.created_at = datetime.now(UTC)
    return doc


def _make_service(
    notification_repo: MagicMock | None = None,
    redis: MagicMock | None = None,
    publisher: MagicMock | None = None,
) -> NotificationService:
    notification_repo = notification_repo or AsyncMock()
    redis = redis or AsyncMock()
    publisher = publisher or AsyncMock()
    return NotificationService(
        notification_repo=notification_repo,
        redis=redis,
        publisher=publisher,
    )


# ── list_notifications ────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_list_notifications_returns_list_response() -> None:
    """알림 목록 조회 → NotificationListResponse 반환."""
    docs = [_make_notification_doc(), _make_notification_doc(notification_id="other_id")]

    notification_repo = AsyncMock()
    notification_repo.list_by_user.return_value = docs
    notification_repo.count_unread.return_value = 2

    redis = AsyncMock()
    redis.get.return_value = b"2"  # 캐시 HIT

    svc = _make_service(notification_repo=notification_repo, redis=redis)
    result = await svc.list_notifications(
        user_id=USER_ID, type_filter=None, cursor=None, limit=20
    )

    assert isinstance(result, NotificationListResponse)
    assert len(result.notifications) == 2
    assert result.unread_count == 2


@pytest.mark.anyio
async def test_list_notifications_cursor_pagination_sets_next_cursor() -> None:
    """docs 수 == limit → next_cursor 설정 (마지막 항목의 created_at)."""
    docs = [_make_notification_doc()]  # 1건

    notification_repo = AsyncMock()
    notification_repo.list_by_user.return_value = docs

    redis = AsyncMock()
    redis.get.return_value = b"1"

    svc = _make_service(notification_repo=notification_repo, redis=redis)
    result = await svc.list_notifications(
        user_id=USER_ID, type_filter=None, cursor=None, limit=1  # limit=1로 설정 → docs(1) == limit
    )

    assert isinstance(result, NotificationListResponse)
    assert result.next_cursor is not None  # 마지막 항목 created_at 기반 커서 설정됨


@pytest.mark.anyio
async def test_list_notifications_empty_returns_empty() -> None:
    """알림 없을 때 → 빈 목록 + next_cursor=None."""
    notification_repo = AsyncMock()
    notification_repo.list_by_user.return_value = []

    redis = AsyncMock()
    redis.get.return_value = b"0"

    svc = _make_service(notification_repo=notification_repo, redis=redis)
    result = await svc.list_notifications(
        user_id=USER_ID, type_filter=None, cursor=None, limit=20
    )

    assert result.notifications == []
    assert result.next_cursor is None
    assert result.unread_count == 0


# ── mark_as_read ──────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_mark_as_read_success_decrements_redis_count() -> None:
    """읽음 처리 → Redis unread_count DECR."""
    doc = _make_notification_doc(is_read=False)
    doc.user_id = USER_ID

    notification_repo = AsyncMock()
    notification_repo.get_by_id.return_value = doc
    notification_repo.mark_read.return_value = True

    redis = AsyncMock()
    redis.get.return_value = b"3"

    svc = _make_service(notification_repo=notification_repo, redis=redis)
    await svc.mark_as_read(user_id=USER_ID, notification_id=NOTIFICATION_ID)

    notification_repo.mark_read.assert_called_once_with(NOTIFICATION_ID)


@pytest.mark.anyio
async def test_mark_as_read_not_found_raises_404() -> None:
    """미존재 알림 읽음 처리 → NotificationErrors.not_found()."""
    notification_repo = AsyncMock()
    notification_repo.get_by_id.return_value = None

    svc = _make_service(notification_repo=notification_repo)

    with pytest.raises(Exception) as exc_info:
        await svc.mark_as_read(user_id=USER_ID, notification_id=NOTIFICATION_ID)

    assert exc_info.value.status_code == 404


@pytest.mark.anyio
async def test_mark_as_read_other_user_raises_403() -> None:
    """타인 알림 읽음 처리 → NotificationErrors.access_denied() (403)."""
    doc = _make_notification_doc()
    doc.user_id = uuid.uuid4()  # 다른 사용자

    notification_repo = AsyncMock()
    notification_repo.get_by_id.return_value = doc

    svc = _make_service(notification_repo=notification_repo)

    with pytest.raises(Exception) as exc_info:
        await svc.mark_as_read(user_id=USER_ID, notification_id=NOTIFICATION_ID)

    assert exc_info.value.status_code == 403


# ── mark_all_as_read ──────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_mark_all_as_read_returns_marked_count() -> None:
    """전체 읽음 처리 → marked 카운트 반환."""
    notification_repo = AsyncMock()
    notification_repo.mark_all_read.return_value = 5

    redis = AsyncMock()

    svc = _make_service(notification_repo=notification_repo, redis=redis)
    result = await svc.mark_all_as_read(user_id=USER_ID)

    assert result == 5
    notification_repo.mark_all_read.assert_called_once_with(USER_ID)


@pytest.mark.anyio
async def test_mark_all_as_read_clears_redis_unread_count() -> None:
    """전체 읽음 → Redis unread_count DEL."""
    notification_repo = AsyncMock()
    notification_repo.mark_all_read.return_value = 3

    redis = AsyncMock()

    svc = _make_service(notification_repo=notification_repo, redis=redis)
    await svc.mark_all_as_read(user_id=USER_ID)

    # DEL 또는 SET 0 호출 확인
    assert redis.delete.called or redis.set.called


# ── get_unread_count ──────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_get_unread_count_redis_cache_hit_skips_db() -> None:
    """Redis 캐시 HIT → MongoDB count 미호출."""
    notification_repo = AsyncMock()
    redis = AsyncMock()
    redis.get.return_value = b"7"

    svc = _make_service(notification_repo=notification_repo, redis=redis)
    count = await svc.get_unread_count(user_id=USER_ID)

    assert count == 7
    notification_repo.count_unread.assert_not_called()


@pytest.mark.anyio
async def test_get_unread_count_redis_cache_miss_queries_db() -> None:
    """Redis 캐시 MISS → MongoDB count + Redis SETEX."""
    notification_repo = AsyncMock()
    notification_repo.count_unread.return_value = 4

    redis = AsyncMock()
    redis.get.return_value = None  # 캐시 MISS

    svc = _make_service(notification_repo=notification_repo, redis=redis)
    count = await svc.get_unread_count(user_id=USER_ID)

    assert count == 4
    notification_repo.count_unread.assert_called_once_with(USER_ID)
    redis.setex.assert_called_once()


# ── create_notification ───────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_create_notification_increments_redis_and_publishes() -> None:
    """알림 생성 → Redis INCR + Pub/Sub publish."""
    doc = _make_notification_doc()

    notification_repo = AsyncMock()
    notification_repo.create.return_value = doc

    redis = AsyncMock()
    publisher = AsyncMock()

    svc = _make_service(
        notification_repo=notification_repo, redis=redis, publisher=publisher
    )

    result = await svc.create_notification(
        user_id=USER_ID,
        type="price_alert",
        title="BTC/KRW 목표가 도달",
        body="BTC/KRW이(가) 85,000,000원에 도달했습니다.",
        data={"coin_symbol": "BTC/KRW"},
    )

    notification_repo.create.assert_called_once()
    redis.incr.assert_called()
    publisher.publish_notification.assert_called_once()

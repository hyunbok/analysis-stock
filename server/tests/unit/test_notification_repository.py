"""NotificationRepository 단위 테스트.

설계서: docs/tasks/v1-21-price-alert-system-plan.md §8.2
테스트: Beanie Document 메서드를 직접 모킹하여 실제 구현 코드를 실행.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.repositories.notification_repository import NotificationRepository


# ── 상수 / 헬퍼 ───────────────────────────────────────────────────────────────

USER_ID = uuid.uuid4()
NOTIFICATION_ID = "64f1a2b3c4d5e6f7a8b9c0d1"
_NOTIF_MODULE = "app.repositories.notification_repository"


def _make_notification_doc(
    notification_id: str = NOTIFICATION_ID,
    user_id: uuid.UUID = USER_ID,
    type: str = "price_alert",
    is_read: bool = False,
    created_at: datetime | None = None,
) -> MagicMock:
    doc = MagicMock()
    doc.id = MagicMock()
    doc.id.__str__ = MagicMock(return_value=notification_id)
    doc.user_id = user_id
    doc.type = type
    doc.title = "BTC/KRW 목표가 도달"
    doc.body = "BTC/KRW이(가) 85,000,000원에 도달했습니다."
    doc.data = {"coin_symbol": "BTC/KRW"}
    doc.is_read = is_read
    doc.created_at = created_at or datetime.now(UTC)
    doc.set = AsyncMock(return_value=None)
    doc.insert = AsyncMock(return_value=None)
    return doc


def _make_find_chain(
    return_value: list | None = None,
    count_value: int = 0,
    modified_count: int = 0,
) -> MagicMock:
    """Beanie find() 체인 mock 생성 (find/sort/limit/to_list/count/update 지원)."""
    mock_query = MagicMock()
    mock_query.find = MagicMock(return_value=mock_query)
    mock_query.sort = MagicMock(return_value=mock_query)
    mock_query.limit = MagicMock(return_value=mock_query)
    mock_query.to_list = AsyncMock(return_value=return_value or [])
    mock_query.count = AsyncMock(return_value=count_value)
    update_result = MagicMock()
    update_result.modified_count = modified_count
    mock_query.update = AsyncMock(return_value=update_result)
    return mock_query


def _make_repo() -> NotificationRepository:
    return NotificationRepository()


# ── create ────────────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_create_notification_calls_insert() -> None:
    """알림 생성 → Notification() 인스턴스 생성 + insert() 호출."""
    repo = _make_repo()
    instance = _make_notification_doc()

    with patch(f"{_NOTIF_MODULE}.Notification") as MockNotif:
        MockNotif.return_value = instance

        result = await repo.create(
            user_id=USER_ID,
            type="price_alert",
            title="BTC/KRW 목표가 도달",
            body="BTC/KRW이(가) 85,000,000원에 도달했습니다.",
            data={"coin_symbol": "BTC/KRW"},
        )

    MockNotif.assert_called_once()
    instance.insert.assert_called_once()
    assert result is instance


# ── get_by_id ─────────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_get_by_id_existing_returns_doc() -> None:
    """존재하는 ObjectId → Notification.get() 호출 후 반환."""
    repo = _make_repo()
    doc = _make_notification_doc()

    with patch(f"{_NOTIF_MODULE}.PydanticObjectId") as MockOID, \
         patch(f"{_NOTIF_MODULE}.Notification") as MockNotif:
        MockOID.return_value = "mock_oid"
        MockNotif.get = AsyncMock(return_value=doc)

        result = await repo.get_by_id(NOTIFICATION_ID)

    MockNotif.get.assert_called_once_with("mock_oid")
    assert result is doc


@pytest.mark.anyio
async def test_get_by_id_invalid_object_id_returns_none() -> None:
    """잘못된 ObjectId 문자열 → PydanticObjectId 예외 → None 반환."""
    repo = _make_repo()

    with patch(f"{_NOTIF_MODULE}.PydanticObjectId", side_effect=Exception("invalid id")):
        result = await repo.get_by_id("not-a-valid-objectid")

    assert result is None


# ── list_by_user ──────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_list_by_user_returns_notifications() -> None:
    """사용자 알림 목록 → find().sort().limit().to_list() 체인 호출."""
    repo = _make_repo()
    docs = [_make_notification_doc("id1"), _make_notification_doc("id2")]
    mock_query = _make_find_chain(return_value=docs)

    with patch(f"{_NOTIF_MODULE}.Notification") as MockNotif:
        MockNotif.find = MagicMock(return_value=mock_query)
        MockNotif.user_id = MagicMock()
        MockNotif.type = MagicMock()
        MockNotif.created_at = MagicMock()
        MockNotif.is_read = MagicMock()

        result = await repo.list_by_user(USER_ID, limit=20)

    assert len(result) == 2
    mock_query.to_list.assert_called_once()
    mock_query.sort.assert_called_once()
    mock_query.limit.assert_called_once_with(20)


@pytest.mark.anyio
async def test_list_by_user_type_filter_adds_find_call() -> None:
    """type_filter 지정 시 find() 체인에 추가 필터 적용."""
    repo = _make_repo()
    docs = [_make_notification_doc(type="price_alert")]
    mock_query = _make_find_chain(return_value=docs)

    with patch(f"{_NOTIF_MODULE}.Notification") as MockNotif:
        MockNotif.find = MagicMock(return_value=mock_query)
        MockNotif.user_id = MagicMock()
        MockNotif.type = MagicMock()
        MockNotif.created_at = MagicMock()
        MockNotif.is_read = MagicMock()

        result = await repo.list_by_user(USER_ID, type_filter="price_alert", limit=20)

    assert len(result) == 1
    # type_filter 적용 시 query.find() 추가 호출됨
    assert mock_query.find.call_count >= 1


@pytest.mark.anyio
async def test_list_by_user_cursor_adds_find_call() -> None:
    """cursor 지정 시 created_at < cursor 필터 추가 (find() 추가 호출)."""
    repo = _make_repo()
    cursor_dt = datetime.now(UTC)
    mock_query = _make_find_chain(return_value=[])

    # created_at 속성에서 < 비교 연산자 지원 (Beanie 필터 표현식 생성)
    created_at_attr = MagicMock()
    type(created_at_attr).__lt__ = MagicMock(return_value=MagicMock())

    with patch(f"{_NOTIF_MODULE}.Notification") as MockNotif:
        MockNotif.find = MagicMock(return_value=mock_query)
        MockNotif.user_id = MagicMock()
        MockNotif.type = MagicMock()
        MockNotif.created_at = created_at_attr
        MockNotif.is_read = MagicMock()

        result = await repo.list_by_user(USER_ID, cursor=cursor_dt, limit=20)

    assert result == []
    # cursor 적용 시 query.find() 추가 호출됨
    assert mock_query.find.call_count >= 1


# ── mark_read ─────────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_mark_read_unread_notification_returns_true() -> None:
    """읽지 않은 알림 → notification.set() 호출 + True 반환."""
    repo = _make_repo()
    doc = _make_notification_doc(is_read=False)

    with patch(f"{_NOTIF_MODULE}.PydanticObjectId") as MockOID, \
         patch(f"{_NOTIF_MODULE}.Notification") as MockNotif:
        MockOID.return_value = "mock_oid"
        MockNotif.get = AsyncMock(return_value=doc)
        MockNotif.is_read = MagicMock()

        result = await repo.mark_read(NOTIFICATION_ID)

    assert result is True
    doc.set.assert_called_once()


@pytest.mark.anyio
async def test_mark_read_not_found_returns_false() -> None:
    """미존재 알림 → get() None → False 반환, set() 미호출."""
    repo = _make_repo()

    with patch(f"{_NOTIF_MODULE}.PydanticObjectId") as MockOID, \
         patch(f"{_NOTIF_MODULE}.Notification") as MockNotif:
        MockOID.return_value = "mock_oid"
        MockNotif.get = AsyncMock(return_value=None)

        result = await repo.mark_read("nonexistent")

    assert result is False


# ── mark_all_read ─────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_mark_all_read_returns_modified_count() -> None:
    """전체 읽음 → find().update() 호출 + modified_count 반환."""
    repo = _make_repo()
    mock_query = _make_find_chain(modified_count=5)

    with patch(f"{_NOTIF_MODULE}.Notification") as MockNotif:
        MockNotif.find = MagicMock(return_value=mock_query)
        MockNotif.user_id = MagicMock()
        MockNotif.is_read = MagicMock()

        result = await repo.mark_all_read(USER_ID)

    assert result == 5
    mock_query.update.assert_called_once()


@pytest.mark.anyio
async def test_mark_all_read_no_unread_returns_zero() -> None:
    """읽지 않은 알림 없음 → modified_count=0."""
    repo = _make_repo()
    mock_query = _make_find_chain(modified_count=0)

    with patch(f"{_NOTIF_MODULE}.Notification") as MockNotif:
        MockNotif.find = MagicMock(return_value=mock_query)
        MockNotif.user_id = MagicMock()
        MockNotif.is_read = MagicMock()

        result = await repo.mark_all_read(USER_ID)

    assert result == 0


# ── count_unread ──────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_count_unread_returns_correct_count() -> None:
    """미읽 카운트 → find().count() 호출 + 값 반환."""
    repo = _make_repo()
    mock_query = _make_find_chain(count_value=7)

    with patch(f"{_NOTIF_MODULE}.Notification") as MockNotif:
        MockNotif.find = MagicMock(return_value=mock_query)
        MockNotif.user_id = MagicMock()
        MockNotif.is_read = MagicMock()

        result = await repo.count_unread(USER_ID)

    assert result == 7
    mock_query.count.assert_called_once()


@pytest.mark.anyio
async def test_count_unread_no_notifications_returns_zero() -> None:
    """알림 없음 → 0 반환."""
    repo = _make_repo()
    mock_query = _make_find_chain(count_value=0)

    with patch(f"{_NOTIF_MODULE}.Notification") as MockNotif:
        MockNotif.find = MagicMock(return_value=mock_query)
        MockNotif.user_id = MagicMock()
        MockNotif.is_read = MagicMock()

        result = await repo.count_unread(USER_ID)

    assert result == 0

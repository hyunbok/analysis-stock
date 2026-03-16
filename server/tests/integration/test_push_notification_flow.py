"""푸시 알림 발송 플로우 통합 테스트.

설계서: docs/tasks/v1-22-fcm-push-notification-plan.md §5.2, §9
패턴: PushService 인스턴스 + 의존성 전부 Mock — 알림 유형별 발송 E2E 검증
"""
from __future__ import annotations

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.push_service import PushService

# ── 헬퍼 ──────────────────────────────────────────────────────────────────────

USER_ID = uuid.uuid4()


def _make_client_mock(fcm_token: str = "fcm_token_abc") -> MagicMock:
    c = MagicMock()
    c.fcm_token = fcm_token
    return c


def _make_service(
    rate_limit_count: int = 1,
    dedup_acquired: bool = True,
    clients: list | None = None,
    fcm_multicast_result: tuple = (1, []),
) -> tuple[PushService, AsyncMock, AsyncMock, AsyncMock, AsyncMock]:
    """PushService + 모든 의존성 mock 반환.

    Returns:
        (service, fcm_service, notification_service, client_repo, redis)
    """
    redis = AsyncMock()
    redis.incr.return_value = rate_limit_count
    redis.expire = AsyncMock()
    redis.set.return_value = True if dedup_acquired else None

    notification_service = AsyncMock()
    notification_service.create_notification.return_value = MagicMock()

    client_repo = AsyncMock()
    client_repo.get_by_user.return_value = (
        clients if clients is not None else [_make_client_mock()]
    )

    fcm_service = AsyncMock()
    fcm_service.send_multicast.return_value = fcm_multicast_result
    fcm_service.send_silent.return_value = True

    settings = MagicMock()
    settings.FCM_RATE_LIMIT_PER_MINUTE = 10

    svc = PushService(fcm_service, notification_service, client_repo, redis, settings)
    return svc, fcm_service, notification_service, client_repo, redis


# ── 가격 알림 플로우 ──────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_price_alert_notification_flow_saves_and_sends_fcm() -> None:
    """가격 알림 전체 플로우: notification 저장 + FCM 멀티캐스트 발송."""
    svc, fcm_svc, notif_svc, _, _ = _make_service()

    result = await svc.send_price_alert_notification(
        user_id=USER_ID,
        alert_id="alert-001",
        coin_symbol="BTC/KRW",
        condition="above",
        target_price=Decimal("85000000"),
        current_price=Decimal("85100000"),
    )

    assert result is True
    notif_svc.create_notification.assert_called_once()
    fcm_svc.send_multicast.assert_called_once()
    # notification type 검증
    notif_call = notif_svc.create_notification.call_args.kwargs
    assert notif_call["type"] == "price_alert"
    assert notif_call["user_id"] == USER_ID


# ── 주문 체결 알림 플로우 ──────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_order_execution_notification_flow() -> None:
    """주문 체결 알림 전체 플로우."""
    svc, fcm_svc, notif_svc, _, _ = _make_service()

    result = await svc.send_order_execution(
        user_id=USER_ID,
        order_id="ord-001",
        coin_symbol="ETH/KRW",
        side="sell",
        filled_qty=Decimal("1.5"),
        price=Decimal("3000000"),
    )

    assert result is True
    notif_svc.create_notification.assert_called_once()
    fcm_svc.send_multicast.assert_called_once()
    notif_call = notif_svc.create_notification.call_args.kwargs
    assert notif_call["type"] == "order_execution"


# ── AI 매매 신호 알림 플로우 ──────────────────────────────────────────────────


@pytest.mark.anyio
async def test_ai_trading_signal_notification_flow() -> None:
    """AI 매매 신호 알림 전체 플로우."""
    svc, fcm_svc, notif_svc, _, _ = _make_service()

    result = await svc.send_ai_trading_signal(
        user_id=USER_ID,
        signal_type="BUY",
        coin_symbol="BTC/KRW",
        reason="강세 신호 감지",
    )

    assert result is True
    notif_svc.create_notification.assert_called_once()
    notif_call = notif_svc.create_notification.call_args.kwargs
    assert notif_call["type"] == "ai_trading_signal"


# ── 시스템 알림 플로우 ────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_system_alert_notification_flow() -> None:
    """시스템 알림 전체 플로우."""
    svc, fcm_svc, notif_svc, _, _ = _make_service()

    result = await svc.send_system_alert(
        user_id=USER_ID,
        message="Upbit 연결 5분째 실패",
        severity="warning",
    )

    assert result is True
    notif_svc.create_notification.assert_called_once()
    notif_call = notif_svc.create_notification.call_args.kwargs
    assert notif_call["type"] == "system_alert"


# ── Rate Limit ────────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_rate_limit_exceeded_drops_notification() -> None:
    """Rate Limit 초과 → notification 미저장, FCM 미발송, False 반환."""
    svc, fcm_svc, notif_svc, _, _ = _make_service(rate_limit_count=11)

    result = await svc.send_order_execution(
        user_id=USER_ID,
        order_id="ord-002",
        coin_symbol="BTC/KRW",
        side="buy",
        filled_qty=Decimal("0.1"),
        price=Decimal("50000000"),
    )

    assert result is False
    notif_svc.create_notification.assert_not_called()
    fcm_svc.send_multicast.assert_not_called()


# ── Dedup ─────────────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_dedup_hit_drops_notification() -> None:
    """Dedup 중복 (SETNX 실패) → notification 미저장, False 반환."""
    svc, fcm_svc, notif_svc, _, _ = _make_service(dedup_acquired=False)

    result = await svc.send_price_alert_notification(
        user_id=USER_ID,
        alert_id="dup-alert-001",
        coin_symbol="BTC/KRW",
        condition="above",
        target_price=Decimal("85000000"),
        current_price=Decimal("85100000"),
    )

    assert result is False
    notif_svc.create_notification.assert_not_called()
    fcm_svc.send_multicast.assert_not_called()


# ── Silent Push ───────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_silent_push_skips_notification_service() -> None:
    """silent=True → NotificationService 미호출, send_silent 호출."""
    svc, fcm_svc, notif_svc, _, _ = _make_service()

    result = await svc.send_to_user(
        user_id=USER_ID,
        notification_type="badge_update",
        title="",
        body="",
        data={"type": "badge_update", "unread_count": "5"},
        silent=True,
    )

    assert result is True
    notif_svc.create_notification.assert_not_called()
    fcm_svc.send_silent.assert_called_once()
    fcm_svc.send_multicast.assert_not_called()


# ── FCM 토큰 없음 ─────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_notification_flow_no_fcm_tokens_returns_true() -> None:
    """활성 FCM 토큰 없음 → notification 저장 완료, FCM 미발송, True 반환."""
    svc, fcm_svc, notif_svc, _, _ = _make_service(clients=[])

    result = await svc.send_system_alert(
        user_id=USER_ID,
        message="시스템 점검 예정",
        severity="info",
    )

    assert result is True
    notif_svc.create_notification.assert_called_once()
    fcm_svc.send_multicast.assert_not_called()

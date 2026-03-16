"""PushService 단위 테스트.

설계서: docs/tasks/v1-22-fcm-push-notification-plan.md §5.2
테스트: Rate Limit + Dedup + 오케스트레이션 (~16건)
"""
from __future__ import annotations

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.push_service import PushService

# ── 헬퍼 ──────────────────────────────────────────────────────────────────────

USER_ID = uuid.uuid4()


def _make_client_mock(fcm_token: str | None = "fcm_token_abc") -> MagicMock:
    c = MagicMock()
    c.fcm_token = fcm_token
    return c


def _make_service(
    fcm_service: MagicMock | None = None,
    notification_service: MagicMock | None = None,
    client_repo: MagicMock | None = None,
    redis: MagicMock | None = None,
    rate_limit: int = 10,
) -> PushService:
    fcm_service = fcm_service or AsyncMock()
    notification_service = notification_service or AsyncMock()
    client_repo = client_repo or AsyncMock()
    redis = redis or AsyncMock()
    settings = MagicMock()
    settings.FCM_RATE_LIMIT_PER_MINUTE = rate_limit
    return PushService(fcm_service, notification_service, client_repo, redis, settings)


# ── send_to_user — Rate Limit ──────────────────────────────────────────────────


@pytest.mark.anyio
async def test_send_to_user_rate_limit_exceeded_returns_false() -> None:
    """Rate Limit 초과 → False 반환, notification 미저장."""
    redis = AsyncMock()
    redis.incr.return_value = 11  # limit=10 초과
    redis.expire = AsyncMock()

    notification_service = AsyncMock()
    svc = _make_service(
        redis=redis, notification_service=notification_service, rate_limit=10
    )

    result = await svc.send_to_user(USER_ID, "price_alert", "제목", "본문")

    assert result is False
    notification_service.create_notification.assert_not_called()


@pytest.mark.anyio
async def test_send_to_user_rate_limit_at_boundary_allows() -> None:
    """Rate Limit 정확히 10 (경계값) → 허용, True 반환."""
    redis = AsyncMock()
    redis.incr.return_value = 10  # 정확히 limit
    redis.expire = AsyncMock()
    redis.set.return_value = True  # dedup SETNX 성공

    client_repo = AsyncMock()
    client_repo.get_by_user.return_value = []  # 토큰 없음

    notification_service = AsyncMock()
    notification_service.create_notification.return_value = MagicMock()

    svc = _make_service(
        redis=redis,
        client_repo=client_repo,
        notification_service=notification_service,
        rate_limit=10,
    )

    result = await svc.send_to_user(USER_ID, "price_alert", "제목", "본문")
    assert result is True


# ── send_to_user — Dedup ──────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_send_to_user_dedup_hit_returns_false() -> None:
    """Dedup 중복 (SETNX 실패) → False, notification 미저장."""
    redis = AsyncMock()
    redis.incr.return_value = 1
    redis.expire = AsyncMock()
    redis.set.return_value = None  # SETNX 실패

    notification_service = AsyncMock()
    svc = _make_service(redis=redis, notification_service=notification_service)

    result = await svc.send_to_user(
        USER_ID, "order_execution", "제목", "본문",
        dedup_key="order:order-123",
    )

    assert result is False
    notification_service.create_notification.assert_not_called()


@pytest.mark.anyio
async def test_send_to_user_no_dedup_key_skips_dedup_check() -> None:
    """dedup_key 없음 → dedup 체크 스킵, Redis set 미호출."""
    redis = AsyncMock()
    redis.incr.return_value = 1
    redis.expire = AsyncMock()

    client_repo = AsyncMock()
    client_repo.get_by_user.return_value = []

    notification_service = AsyncMock()
    notification_service.create_notification.return_value = MagicMock()

    svc = _make_service(
        redis=redis, client_repo=client_repo, notification_service=notification_service
    )

    result = await svc.send_to_user(USER_ID, "system_alert", "제목", "본문")

    assert result is True
    redis.set.assert_not_called()


# ── send_to_user — 정상 발송 ──────────────────────────────────────────────────


@pytest.mark.anyio
async def test_send_to_user_no_fcm_tokens_saves_notification_returns_true() -> None:
    """FCM 토큰 없는 사용자 → notification 저장 성공, True 반환."""
    redis = AsyncMock()
    redis.incr.return_value = 1
    redis.expire = AsyncMock()
    redis.set.return_value = True

    notification_service = AsyncMock()
    notification_service.create_notification.return_value = MagicMock()

    client_repo = AsyncMock()
    client_repo.get_by_user.return_value = []  # 활성 기기 없음

    fcm_service = AsyncMock()

    svc = _make_service(
        fcm_service=fcm_service,
        redis=redis,
        notification_service=notification_service,
        client_repo=client_repo,
    )

    result = await svc.send_to_user(
        USER_ID, "price_alert", "제목", "본문", dedup_key="key1"
    )

    assert result is True
    notification_service.create_notification.assert_called_once()
    fcm_service.send_multicast.assert_not_called()


@pytest.mark.anyio
async def test_send_to_user_sends_multicast_to_all_tokens() -> None:
    """활성 FCM 토큰 2개 → send_multicast에 두 토큰 전달."""
    redis = AsyncMock()
    redis.incr.return_value = 1
    redis.expire = AsyncMock()
    redis.set.return_value = True

    notification_service = AsyncMock()
    notification_service.create_notification.return_value = MagicMock()

    clients = [_make_client_mock("tok1"), _make_client_mock("tok2")]
    client_repo = AsyncMock()
    client_repo.get_by_user.return_value = clients

    fcm_service = AsyncMock()
    fcm_service.send_multicast.return_value = (2, [])

    svc = _make_service(
        fcm_service=fcm_service,
        redis=redis,
        notification_service=notification_service,
        client_repo=client_repo,
    )

    result = await svc.send_to_user(USER_ID, "price_alert", "제목", "본문", dedup_key="key1")

    assert result is True
    fcm_service.send_multicast.assert_called_once()
    sent_tokens = fcm_service.send_multicast.call_args.args[0]
    assert "tok1" in sent_tokens
    assert "tok2" in sent_tokens


# ── send_to_user — silent ─────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_send_to_user_silent_skips_notification_service() -> None:
    """silent=True → NotificationService.create_notification() 미호출."""
    redis = AsyncMock()
    redis.incr.return_value = 1
    redis.expire = AsyncMock()

    notification_service = AsyncMock()
    client_repo = AsyncMock()
    client_repo.get_by_user.return_value = []

    svc = _make_service(
        redis=redis, notification_service=notification_service, client_repo=client_repo
    )

    await svc.send_to_user(USER_ID, "badge_update", "", "", silent=True)

    notification_service.create_notification.assert_not_called()


@pytest.mark.anyio
async def test_send_to_user_silent_calls_send_silent_per_token() -> None:
    """silent=True + 토큰 2개 → send_silent 2회 호출."""
    redis = AsyncMock()
    redis.incr.return_value = 1
    redis.expire = AsyncMock()

    clients = [_make_client_mock("tok1"), _make_client_mock("tok2")]
    client_repo = AsyncMock()
    client_repo.get_by_user.return_value = clients

    fcm_service = AsyncMock()

    svc = _make_service(
        fcm_service=fcm_service, redis=redis, client_repo=client_repo
    )

    await svc.send_to_user(
        USER_ID, "badge_update", "", "",
        data={"type": "badge_update", "count": "3"},
        silent=True,
    )

    assert fcm_service.send_silent.call_count == 2
    fcm_service.send_multicast.assert_not_called()


# ── 실패 토큰 정리 ────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_send_to_user_clears_invalid_fcm_tokens() -> None:
    """send_multicast 실패 토큰 반환 시 clear_fcm_token_by_value() 호출."""
    redis = AsyncMock()
    redis.incr.return_value = 1
    redis.expire = AsyncMock()
    redis.set.return_value = True

    notification_service = AsyncMock()
    notification_service.create_notification.return_value = MagicMock()

    clients = [_make_client_mock("tok_valid"), _make_client_mock("tok_expired")]
    client_repo = AsyncMock()
    client_repo.get_by_user.return_value = clients

    fcm_service = AsyncMock()
    fcm_service.send_multicast.return_value = (1, ["tok_expired"])  # tok_expired 실패

    svc = _make_service(
        fcm_service=fcm_service,
        redis=redis,
        notification_service=notification_service,
        client_repo=client_repo,
    )

    await svc.send_to_user(USER_ID, "price_alert", "제목", "본문", dedup_key="key1")

    client_repo.clear_fcm_token_by_value.assert_called_once_with("tok_expired")


# ── 알림 유형별 헬퍼 ───────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_send_order_execution_builds_correct_title_and_dedup_key() -> None:
    """send_order_execution() → 제목에 코인/방향 포함, dedup_key=order:{id}."""
    svc = _make_service()
    svc.send_to_user = AsyncMock(return_value=True)

    order_id = "ord-001"
    await svc.send_order_execution(
        user_id=USER_ID,
        order_id=order_id,
        coin_symbol="BTC/KRW",
        side="buy",
        filled_qty=Decimal("0.1"),
        price=Decimal("50000000"),
    )

    call_kwargs = svc.send_to_user.call_args
    title = call_kwargs.args[2]
    assert "BTC/KRW" in title
    assert "매수" in title
    assert call_kwargs.kwargs["dedup_key"] == f"order:{order_id}"


@pytest.mark.anyio
async def test_send_ai_trading_signal_builds_correct_title_and_dedup_key() -> None:
    """send_ai_trading_signal() → AI 신호 제목 + dedup_key."""
    svc = _make_service()
    svc.send_to_user = AsyncMock(return_value=True)

    await svc.send_ai_trading_signal(
        user_id=USER_ID,
        signal_type="BUY",
        coin_symbol="ETH/KRW",
        reason="추세 장세 감지",
    )

    call_kwargs = svc.send_to_user.call_args
    title = call_kwargs.args[2]
    assert "AI" in title
    assert "매수" in title
    assert "ETH/KRW" in title
    assert call_kwargs.kwargs["dedup_key"] == "ai_signal:ETH/KRW:BUY"


@pytest.mark.anyio
async def test_send_price_alert_notification_builds_correct_body() -> None:
    """send_price_alert_notification() → body에 target_price + condition_kr."""
    svc = _make_service()
    svc.send_to_user = AsyncMock(return_value=True)

    await svc.send_price_alert_notification(
        user_id=USER_ID,
        alert_id="alert-001",
        coin_symbol="BTC/KRW",
        condition="above",
        target_price=Decimal("85000000"),
        current_price=Decimal("85100000"),
    )

    call_kwargs = svc.send_to_user.call_args
    body = call_kwargs.args[3]
    assert "이상" in body
    assert call_kwargs.kwargs["dedup_key"] == "price_alert:alert-001"


@pytest.mark.anyio
async def test_send_system_alert_severity_maps_to_title() -> None:
    """send_system_alert() → severity별 제목 매핑."""
    severity_title_map = {
        "info": "시스템 안내",
        "warning": "시스템 경고",
        "critical": "긴급 알림",
    }
    for severity, expected_title in severity_title_map.items():
        svc = _make_service()
        svc.send_to_user = AsyncMock(return_value=True)

        await svc.send_system_alert(USER_ID, "서비스 점검 예정", severity=severity)

        call_kwargs = svc.send_to_user.call_args
        assert call_kwargs.args[2] == expected_title


# ── _check_rate_limit ─────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_check_rate_limit_increments_and_expires() -> None:
    """_check_rate_limit → INCR + EXPIRE(nx=True) 호출, count<=limit이면 True."""
    redis = AsyncMock()
    redis.incr.return_value = 3
    redis.expire = AsyncMock()

    svc = _make_service(redis=redis, rate_limit=10)
    result = await svc._check_rate_limit(USER_ID)

    assert result is True
    redis.incr.assert_called_once()
    redis.expire.assert_called_once()
    expire_kwargs = redis.expire.call_args.kwargs
    assert expire_kwargs.get("nx") is True


# ── _check_dedup ──────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_check_dedup_setnx_success_returns_true() -> None:
    """SETNX 성공 → True (첫 번째 발송)."""
    redis = AsyncMock()
    redis.set.return_value = True

    svc = _make_service(redis=redis)
    result = await svc._check_dedup(USER_ID, "order:ord-001")

    assert result is True
    redis.set.assert_called_once()
    call_kwargs = redis.set.call_args.kwargs
    assert call_kwargs.get("nx") is True
    assert call_kwargs.get("ex") is not None


@pytest.mark.anyio
async def test_check_dedup_setnx_fail_returns_false() -> None:
    """SETNX 실패 → False (중복 알림)."""
    redis = AsyncMock()
    redis.set.return_value = None  # 키 이미 존재

    svc = _make_service(redis=redis)
    result = await svc._check_dedup(USER_ID, "order:ord-001")

    assert result is False

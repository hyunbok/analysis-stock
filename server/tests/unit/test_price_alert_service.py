"""PriceAlertService 단위 테스트.

설계서: docs/tasks/v1-21-price-alert-system-plan.md §9.1
테스트: CRUD + 트리거 로직 (~15건)
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.exceptions import PriceAlertErrors
from app.schemas.price_alert import (
    CreatePriceAlertRequest,
    PriceAlertListResponse,
    PriceAlertResponse,
    UpdatePriceAlertRequest,
)
from app.services.price_alert_service import PriceAlertService


# ── 상수 / 헬퍼 ───────────────────────────────────────────────────────────────

USER_ID = uuid.uuid4()
COIN_ID = uuid.uuid4()
ALERT_ID = uuid.uuid4()
EXCHANGE_ACCOUNT_ID = uuid.uuid4()


def _make_alert_model(
    alert_id: uuid.UUID = ALERT_ID,
    user_id: uuid.UUID = USER_ID,
    coin_id: uuid.UUID = COIN_ID,
    condition: str = "above",
    target_price: Decimal = Decimal("85000000"),
    is_triggered: bool = False,
    is_active: bool = True,
    exchange_account_id: uuid.UUID | None = None,
) -> MagicMock:
    alert = MagicMock()
    alert.id = alert_id
    alert.user_id = user_id
    alert.coin_id = coin_id
    alert.condition = condition
    alert.target_price = target_price
    alert.is_triggered = is_triggered
    alert.is_active = is_active
    alert.exchange_account_id = exchange_account_id
    alert.triggered_at = None
    alert.created_at = datetime.now(UTC)
    alert.updated_at = datetime.now(UTC)
    # coin 관계
    alert.coin = MagicMock()
    alert.coin.symbol = "BTC/KRW"
    alert.coin.name_ko = "비트코인"
    return alert


def _make_alert_response(
    alert_id: uuid.UUID = ALERT_ID,
    condition: str = "above",
    target_price: Decimal = Decimal("85000000"),
    is_triggered: bool = False,
    is_active: bool = True,
) -> PriceAlertResponse:
    now = datetime.now(UTC)
    return PriceAlertResponse(
        id=alert_id,
        coin_id=COIN_ID,
        coin_symbol="BTC/KRW",
        coin_name_ko="비트코인",
        exchange_account_id=None,
        condition=condition,
        target_price=target_price,
        is_triggered=is_triggered,
        is_active=is_active,
        triggered_at=None,
        created_at=now,
    )


def _make_service(
    alert_repo: MagicMock | None = None,
    coin_repo: MagicMock | None = None,
    exchange_account_repo: MagicMock | None = None,
    notification_service: MagicMock | None = None,
    fcm_service: MagicMock | None = None,
    client_repo: MagicMock | None = None,
    redis: MagicMock | None = None,
) -> PriceAlertService:
    alert_repo = alert_repo or AsyncMock()
    coin_repo = coin_repo or AsyncMock()
    exchange_account_repo = exchange_account_repo or AsyncMock()
    notification_service = notification_service or AsyncMock()
    fcm_service = fcm_service or AsyncMock()
    client_repo = client_repo or AsyncMock()
    redis = redis or AsyncMock()
    return PriceAlertService(
        alert_repo=alert_repo,
        coin_repo=coin_repo,
        exchange_account_repo=exchange_account_repo,
        notification_service=notification_service,
        fcm_service=fcm_service,
        client_repo=client_repo,
        redis=redis,
    )


# ── create_alert ──────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_create_alert_success_returns_response() -> None:
    """정상 알림 생성 → PriceAlertResponse 반환."""
    alert_model = _make_alert_model()
    alert_repo = AsyncMock()
    alert_repo.create.return_value = alert_model
    alert_repo.count_by_user.return_value = 0

    coin_repo = AsyncMock()
    coin_repo.get_by_id.return_value = MagicMock()  # 코인 존재

    svc = _make_service(alert_repo=alert_repo, coin_repo=coin_repo)

    body = CreatePriceAlertRequest(
        coin_id=COIN_ID,
        condition="above",
        target_price=Decimal("85000000"),
    )
    result = await svc.create_alert(user_id=USER_ID, body=body)

    assert isinstance(result, PriceAlertResponse)
    assert result.condition == "above"
    assert result.is_active is True
    alert_repo.create.assert_called_once()


@pytest.mark.anyio
async def test_create_alert_coin_not_found_raises_404() -> None:
    """coin_id 미존재 → PriceAlertErrors.coin_not_found() (404)."""
    coin_repo = AsyncMock()
    coin_repo.get_by_id.return_value = None

    svc = _make_service(coin_repo=coin_repo)

    body = CreatePriceAlertRequest(
        coin_id=uuid.uuid4(),
        condition="above",
        target_price=Decimal("85000000"),
    )
    with pytest.raises(Exception) as exc_info:
        await svc.create_alert(user_id=USER_ID, body=body)

    assert exc_info.value.code == "PRICE_ALERT_COIN_NOT_FOUND"
    assert exc_info.value.status_code == 404


@pytest.mark.anyio
async def test_create_alert_exchange_account_not_owned_raises_403() -> None:
    """타인 소유 거래소 계정 지정 → PriceAlertErrors.exchange_account_not_owned() (403)."""
    coin_repo = AsyncMock()
    coin_repo.get_by_id.return_value = MagicMock()

    exchange_account_repo = AsyncMock()
    exchange_account_repo.get_by_id.return_value = None  # 소유하지 않음

    alert_repo = AsyncMock()
    alert_repo.count_by_user.return_value = 0

    svc = _make_service(
        coin_repo=coin_repo,
        exchange_account_repo=exchange_account_repo,
        alert_repo=alert_repo,
    )

    body = CreatePriceAlertRequest(
        coin_id=COIN_ID,
        exchange_account_id=uuid.uuid4(),
        condition="above",
        target_price=Decimal("85000000"),
    )
    with pytest.raises(Exception) as exc_info:
        await svc.create_alert(user_id=USER_ID, body=body)

    assert exc_info.value.code == "PRICE_ALERT_ACCOUNT_NOT_OWNED"
    assert exc_info.value.status_code == 403


@pytest.mark.anyio
async def test_create_alert_max_exceeded_raises_400() -> None:
    """사용자 알림 50개 초과 → PriceAlertErrors.max_exceeded() (400)."""
    coin_repo = AsyncMock()
    coin_repo.get_by_id.return_value = MagicMock()

    alert_repo = AsyncMock()
    alert_repo.count_by_user.return_value = 50  # 이미 50개

    svc = _make_service(alert_repo=alert_repo, coin_repo=coin_repo)

    body = CreatePriceAlertRequest(
        coin_id=COIN_ID,
        condition="above",
        target_price=Decimal("85000000"),
    )
    with pytest.raises(Exception) as exc_info:
        await svc.create_alert(user_id=USER_ID, body=body)

    assert exc_info.value.code == "PRICE_ALERT_MAX_EXCEEDED"
    assert exc_info.value.status_code == 400


# ── get_alerts ────────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_get_alerts_returns_list_with_unread_count() -> None:
    """목록 조회 → PriceAlertListResponse (alerts + unread_count).
    notification_service.get_unread_count() 위임 방식.
    """
    alerts = [_make_alert_model(), _make_alert_model(alert_id=uuid.uuid4())]

    alert_repo = AsyncMock()
    alert_repo.get_by_user.return_value = alerts

    notification_service = AsyncMock()
    notification_service.get_unread_count.return_value = 3

    svc = _make_service(alert_repo=alert_repo, notification_service=notification_service)

    result = await svc.get_alerts(user_id=USER_ID, active=None)

    assert isinstance(result, PriceAlertListResponse)
    assert len(result.alerts) == 2
    assert result.unread_count == 3


@pytest.mark.anyio
async def test_get_alerts_active_filter_passed_to_repo() -> None:
    """active=True 필터 → repo에 전달."""
    alert_repo = AsyncMock()
    alert_repo.get_by_user.return_value = []

    notification_service = AsyncMock()
    notification_service.get_unread_count.return_value = 0

    svc = _make_service(alert_repo=alert_repo, notification_service=notification_service)
    await svc.get_alerts(user_id=USER_ID, active=True)

    call_kwargs = alert_repo.get_by_user.call_args.kwargs
    assert call_kwargs.get("active") is True


# ── update_alert ──────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_update_alert_success_returns_response() -> None:
    """정상 수정 → PriceAlertResponse 반환."""
    alert = _make_alert_model()
    alert_repo = AsyncMock()
    alert_repo.get_by_user_and_id.return_value = alert
    alert_repo.update.return_value = alert

    svc = _make_service(alert_repo=alert_repo)

    body = UpdatePriceAlertRequest(target_price=Decimal("90000000"))
    result = await svc.update_alert(user_id=USER_ID, alert_id=ALERT_ID, body=body)

    assert isinstance(result, PriceAlertResponse)
    alert_repo.update.assert_called_once()


@pytest.mark.anyio
async def test_update_alert_not_found_raises_404() -> None:
    """알림 미존재 → 404."""
    alert_repo = AsyncMock()
    alert_repo.get_by_user_and_id.return_value = None
    alert_repo.get_by_id.return_value = None  # 알림 자체가 존재하지 않음

    svc = _make_service(alert_repo=alert_repo)

    body = UpdatePriceAlertRequest(target_price=Decimal("90000000"))
    with pytest.raises(Exception) as exc_info:
        await svc.update_alert(user_id=USER_ID, alert_id=ALERT_ID, body=body)

    assert exc_info.value.status_code == 404


@pytest.mark.anyio
async def test_update_alert_reactivate_triggered_raises_409() -> None:
    """이미 트리거된 알림 재활성화 → 409 PRICE_ALERT_ALREADY_TRIGGERED."""
    alert = _make_alert_model(is_triggered=True, is_active=False)
    alert_repo = AsyncMock()
    alert_repo.get_by_user_and_id.return_value = alert

    svc = _make_service(alert_repo=alert_repo)

    body = UpdatePriceAlertRequest(is_active=True)
    with pytest.raises(Exception) as exc_info:
        await svc.update_alert(user_id=USER_ID, alert_id=ALERT_ID, body=body)

    assert exc_info.value.code == "PRICE_ALERT_ALREADY_TRIGGERED"
    assert exc_info.value.status_code == 409


# ── delete_alert ──────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_delete_alert_success_calls_repo_delete() -> None:
    """정상 삭제 → repo.delete() 호출."""
    alert = _make_alert_model()
    alert_repo = AsyncMock()
    alert_repo.get_by_user_and_id.return_value = alert

    svc = _make_service(alert_repo=alert_repo)
    await svc.delete_alert(user_id=USER_ID, alert_id=ALERT_ID)

    alert_repo.delete.assert_called_once_with(ALERT_ID)


@pytest.mark.anyio
async def test_delete_alert_not_found_raises_error() -> None:
    """미존재 알림 삭제 → 404."""
    alert_repo = AsyncMock()
    alert_repo.get_by_user_and_id.return_value = None
    alert_repo.get_by_id.return_value = None  # 알림 자체가 존재하지 않음

    svc = _make_service(alert_repo=alert_repo)

    with pytest.raises(Exception) as exc_info:
        await svc.delete_alert(user_id=USER_ID, alert_id=ALERT_ID)

    assert exc_info.value.status_code == 404


# ── process_ticker / trigger ──────────────────────────────────────────────────


@pytest.mark.anyio
async def test_process_ticker_above_condition_triggers_alert() -> None:
    """above 조건: current_price >= target_price → _trigger_alert 호출."""
    target_price = Decimal("85000000")
    current_price = Decimal("85100000")  # target_price 이상

    alert = _make_alert_model(condition="above", target_price=target_price)
    alert_repo = AsyncMock()
    alert_repo.get_active_untriggered_by_market.return_value = [alert]
    alert_repo.mark_triggered.return_value = True

    notification_service = AsyncMock()
    notification_service.create_notification.return_value = MagicMock()

    redis = AsyncMock()
    redis.set.return_value = True  # SETNX 성공

    client_repo = AsyncMock()
    client_repo.get_by_user.return_value = []

    svc = _make_service(
        alert_repo=alert_repo,
        notification_service=notification_service,
        redis=redis,
        client_repo=client_repo,
    )

    await svc.process_ticker("upbit", "KRW-BTC", current_price)

    alert_repo.mark_triggered.assert_called_once()
    notification_service.create_notification.assert_called_once()


@pytest.mark.anyio
async def test_process_ticker_below_condition_triggers_alert() -> None:
    """below 조건: current_price <= target_price → 트리거 발생."""
    target_price = Decimal("80000000")
    current_price = Decimal("79900000")  # target_price 이하

    alert = _make_alert_model(condition="below", target_price=target_price)
    alert_repo = AsyncMock()
    alert_repo.get_active_untriggered_by_market.return_value = [alert]
    alert_repo.mark_triggered.return_value = True

    notification_service = AsyncMock()
    notification_service.create_notification.return_value = MagicMock()

    redis = AsyncMock()
    redis.set.return_value = True

    client_repo = AsyncMock()
    client_repo.get_by_user.return_value = []

    svc = _make_service(
        alert_repo=alert_repo,
        notification_service=notification_service,
        redis=redis,
        client_repo=client_repo,
    )

    await svc.process_ticker("upbit", "KRW-BTC", current_price)

    alert_repo.mark_triggered.assert_called_once()


@pytest.mark.anyio
async def test_process_ticker_condition_not_met_no_trigger() -> None:
    """above 조건 미달 → 트리거 없음."""
    target_price = Decimal("85000000")
    current_price = Decimal("84900000")  # target_price 미만

    alert = _make_alert_model(condition="above", target_price=target_price)
    alert_repo = AsyncMock()
    alert_repo.get_active_untriggered_by_market.return_value = [alert]

    svc = _make_service(alert_repo=alert_repo)

    await svc.process_ticker("upbit", "KRW-BTC", current_price)

    alert_repo.mark_triggered.assert_not_called()


@pytest.mark.anyio
async def test_trigger_alert_duplicate_redis_lock_skips() -> None:
    """Redis SETNX 실패 (이미 처리 중) → mark_triggered 호출 안 함."""
    target_price = Decimal("85000000")
    current_price = Decimal("86000000")

    alert = _make_alert_model(condition="above", target_price=target_price)
    alert_repo = AsyncMock()
    alert_repo.get_active_untriggered_by_market.return_value = [alert]

    redis = AsyncMock()
    redis.set.return_value = None  # SETNX 실패 (이미 잠김)

    svc = _make_service(alert_repo=alert_repo, redis=redis)

    await svc.process_ticker("upbit", "KRW-BTC", current_price)

    alert_repo.mark_triggered.assert_not_called()


@pytest.mark.anyio
async def test_trigger_alert_db_race_condition_skips() -> None:
    """mark_triggered returns False (DB 경합) → notification 생성 안 함."""
    target_price = Decimal("85000000")
    current_price = Decimal("86000000")

    alert = _make_alert_model(condition="above", target_price=target_price)
    alert_repo = AsyncMock()
    alert_repo.get_active_untriggered_by_market.return_value = [alert]
    alert_repo.mark_triggered.return_value = False  # 이미 트리거됨

    redis = AsyncMock()
    redis.set.return_value = True  # SETNX 성공

    notification_service = AsyncMock()

    svc = _make_service(
        alert_repo=alert_repo,
        redis=redis,
        notification_service=notification_service,
    )

    await svc.process_ticker("upbit", "KRW-BTC", current_price)

    notification_service.create_notification.assert_not_called()

"""가격 알림 비즈니스 로직 서비스."""
from __future__ import annotations

import logging
import uuid
from decimal import Decimal

from redis.asyncio import Redis

from app.core.exceptions import PriceAlertErrors
from app.core.redis_keys import RedisKey, RedisTTL
from app.repositories.client_repository import ClientRepository
from app.repositories.coin_repository import CoinRepository
from app.repositories.exchange_account_repository import ExchangeAccountRepository
from app.repositories.price_alert_repository import PriceAlertRepository
from app.schemas.price_alert import (
    CreatePriceAlertRequest,
    PriceAlertListResponse,
    PriceAlertResponse,
    UpdatePriceAlertRequest,
)
from app.services.fcm_service import FCMService
from app.services.notification_service import NotificationService

logger = logging.getLogger(__name__)


class PriceAlertService:
    def __init__(
        self,
        alert_repo: PriceAlertRepository,
        coin_repo: CoinRepository,
        exchange_account_repo: ExchangeAccountRepository,
        notification_service: NotificationService,
        fcm_service: FCMService,
        client_repo: ClientRepository,
        redis: Redis,
    ) -> None:
        self._alert_repo = alert_repo
        self._coin_repo = coin_repo
        self._exchange_account_repo = exchange_account_repo
        self._notification_service = notification_service
        self._fcm_service = fcm_service
        self._client_repo = client_repo
        self._redis = redis

    async def create_alert(
        self, user_id: uuid.UUID, body: CreatePriceAlertRequest
    ) -> PriceAlertResponse:
        # 1. coin_id 존재 확인
        coin = await self._coin_repo.get_by_id(body.coin_id)
        if coin is None:
            raise PriceAlertErrors.coin_not_found()

        # 2. exchange_account_id 있으면 소유권 확인
        if body.exchange_account_id is not None:
            account = await self._exchange_account_repo.get_by_id(body.exchange_account_id)
            if account is None or account.user_id != user_id:
                raise PriceAlertErrors.exchange_account_not_owned()

        # 3. 최대 50개 체크
        count = await self._alert_repo.count_by_user(user_id)
        if count >= 50:
            raise PriceAlertErrors.max_exceeded()

        # 4. PG INSERT
        alert = await self._alert_repo.create(
            user_id=user_id,
            coin_id=body.coin_id,
            exchange_account_id=body.exchange_account_id,
            condition=body.condition,
            target_price=body.target_price,
        )
        return _to_response(alert)

    async def get_alerts(
        self, user_id: uuid.UUID, active: bool | None
    ) -> PriceAlertListResponse:
        alerts = await self._alert_repo.get_by_user(user_id, active=active)
        unread_count = await self._notification_service.get_unread_count(user_id)
        return PriceAlertListResponse(
            alerts=[_to_response(a) for a in alerts],
            unread_count=unread_count,
        )

    async def update_alert(
        self,
        user_id: uuid.UUID,
        alert_id: uuid.UUID,
        body: UpdatePriceAlertRequest,
    ) -> PriceAlertResponse:
        # 1. 소유권 확인
        alert = await self._alert_repo.get_by_user_and_id(user_id, alert_id)
        if alert is None:
            # 알림 자체 존재 여부 구분
            existing = await self._alert_repo.get_by_id(alert_id)
            if existing is None:
                raise PriceAlertErrors.not_found()
            raise PriceAlertErrors.access_denied()

        # 2. 이미 트리거된 알림 재활성화 불가
        if body.is_active is True and alert.is_triggered:
            raise PriceAlertErrors.already_triggered()

        # 3. PG UPDATE
        kwargs = {k: v for k, v in body.model_dump(exclude_none=True).items()}
        updated = await self._alert_repo.update(alert, **kwargs)
        return _to_response(updated)

    async def delete_alert(self, user_id: uuid.UUID, alert_id: uuid.UUID) -> None:
        # 소유권 확인
        alert = await self._alert_repo.get_by_user_and_id(user_id, alert_id)
        if alert is None:
            existing = await self._alert_repo.get_by_id(alert_id)
            if existing is None:
                raise PriceAlertErrors.not_found()
            raise PriceAlertErrors.access_denied()
        await self._alert_repo.delete(alert_id)

    async def process_ticker(
        self, exchange_type: str, market_code: str, current_price: Decimal
    ) -> None:
        """PriceAlertMonitor에서 호출 (백그라운드).
        활성 미트리거 알림 조회 → 조건 비교 → 트리거."""
        alerts = await self._alert_repo.get_active_untriggered_by_market(
            exchange_type, market_code
        )
        for alert in alerts:
            condition_met = (
                (alert.condition == "above" and current_price >= alert.target_price)
                or (alert.condition == "below" and current_price <= alert.target_price)
            )
            if condition_met:
                coin_symbol = alert.coin.symbol if alert.coin else market_code
                try:
                    await self._trigger_alert(
                        alert, current_price, coin_symbol, exchange_type
                    )
                except Exception:
                    logger.exception(
                        "Failed to trigger alert %s for user %s", alert.id, alert.user_id
                    )

    async def _trigger_alert(
        self,
        alert,
        current_price: Decimal,
        coin_symbol: str,
        exchange_type: str,
    ) -> None:
        """개별 알림 트리거 처리."""
        # a. Redis SETNX 중복 방지 (30초 TTL)
        lock_key = RedisKey.price_alert_triggering(str(alert.id))
        acquired = await self._redis.set(lock_key, "1", nx=True, ex=RedisTTL.PRICE_ALERT_TRIGGERING)
        if not acquired:
            logger.debug("Alert %s already triggering (Redis lock), skip", alert.id)
            return

        # b. PG UPDATE WHERE is_triggered=False (1차 방어)
        triggered = await self._alert_repo.mark_triggered(alert.id)
        if not triggered:
            logger.debug("Alert %s already triggered (DB), skip", alert.id)
            return

        # c. 알림 기록 생성
        title = f"{coin_symbol} 목표가 도달"
        body = f"{coin_symbol}이(가) {alert.target_price:,}원에 도달했습니다."
        data = {
            "alert_id": str(alert.id),
            "coin_symbol": coin_symbol,
            "exchange_type": exchange_type,
            "condition": alert.condition,
            "target_price": str(alert.target_price),
            "current_price": str(current_price),
        }
        await self._notification_service.create_notification(
            user_id=alert.user_id,
            type="price_alert",
            title=title,
            body=body,
            data=data,
        )

        # Redis 가격 알림 전용 미읽 카운트 INCR
        pa_unread_key = RedisKey.price_alert_unread_count(str(alert.user_id))
        await self._redis.incr(pa_unread_key)
        await self._redis.expire(pa_unread_key, RedisTTL.PRICE_ALERT_UNREAD_COUNT, nx=True)

        # d. FCM 발송 (복수 기기, fire-and-forget)
        try:
            clients = await self._client_repo.get_by_user(alert.user_id)
            for client in clients:
                if client.fcm_token:
                    await self._fcm_service.send_price_alert(
                        fcm_token=client.fcm_token,
                        coin_symbol=coin_symbol,
                        condition=alert.condition,
                        target_price=alert.target_price,
                        current_price=current_price,
                    )
        except Exception:
            logger.exception("FCM send failed for alert %s", alert.id)


def _to_response(alert) -> PriceAlertResponse:
    return PriceAlertResponse(
        id=alert.id,
        coin_id=alert.coin_id,
        coin_symbol=alert.coin.symbol if alert.coin else "",
        coin_name_ko=alert.coin.name_ko if alert.coin else None,
        exchange_account_id=alert.exchange_account_id,
        condition=alert.condition,
        target_price=alert.target_price,
        is_triggered=alert.is_triggered,
        is_active=alert.is_active,
        triggered_at=alert.triggered_at,
        created_at=alert.created_at,
    )

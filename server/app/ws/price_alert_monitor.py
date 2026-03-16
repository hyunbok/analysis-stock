"""PriceAlertMonitor — Redis Pub/Sub ticker 채널 구독 → 가격 알림 조건 체크.

FastAPI lifespan에서 시작/중지. 별도 asyncio.Task로 실행.
ch:ticker:{exchange}:{market} 패턴 구독.

두 가지 초기화 모드:
  - 테스트: PriceAlertMonitor(price_alert_service=mock_svc, pubsub_redis=redis)
  - 프로덕션: PriceAlertMonitor(session_factory=..., pubsub_redis=..., main_redis=..., settings=...)
"""
from __future__ import annotations

import asyncio
import json
import logging
from contextlib import suppress
from decimal import Decimal, InvalidOperation

from redis.asyncio import Redis

logger = logging.getLogger(__name__)


class PriceAlertMonitor:
    """Redis Pub/Sub ticker 채널 구독 → 가격 알림 조건 체크."""

    def __init__(
        self,
        pubsub_redis: Redis,
        price_alert_service=None,          # 테스트/직접 주입 시
        session_factory=None,              # 프로덕션: 매 호출마다 새 세션
        main_redis: Redis | None = None,   # 프로덕션 전용
        settings=None,                     # 프로덕션 전용
    ) -> None:
        self._pubsub_redis = pubsub_redis
        self._service = price_alert_service   # 직접 주입 모드
        self._session_factory = session_factory
        self._main_redis = main_redis
        self._settings = settings
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        """lifespan startup에서 호출. 구독 루프 시작."""
        self._task = asyncio.create_task(
            self._subscribe_loop(), name="price_alert_monitor"
        )
        logger.info("PriceAlertMonitor started")

    async def _subscribe_loop(self) -> None:
        """ch:ticker:*:* 패턴 구독, 메시지 수신 시 _on_ticker 호출."""
        pubsub = self._pubsub_redis.pubsub()
        await pubsub.psubscribe("ch:ticker:*:*")
        logger.debug("PriceAlertMonitor subscribed to ch:ticker:*:*")
        try:
            async for message in pubsub.listen():
                if message["type"] != "pmessage":
                    continue
                try:
                    await self._on_ticker(message)
                except Exception:
                    logger.exception("PriceAlertMonitor _on_ticker error")
        except asyncio.CancelledError:
            logger.info("PriceAlertMonitor subscribe loop cancelled")
            raise
        finally:
            with suppress(Exception):
                await pubsub.punsubscribe("ch:ticker:*:*")
            with suppress(Exception):
                await pubsub.aclose()

    async def _on_ticker(self, message: dict) -> None:
        """ticker 메시지 파싱 → process_ticker 호출."""
        # channel: "ch:ticker:{exchange}:{market}"
        channel: bytes | str = message.get("channel", b"")
        if isinstance(channel, bytes):
            channel = channel.decode()

        parts = channel.split(":")  # ["ch", "ticker", exchange, market]
        if len(parts) < 4:
            return

        exchange = parts[2]
        market = parts[3]

        raw_data = message.get("data", b"")
        if isinstance(raw_data, bytes):
            raw_data = raw_data.decode()

        try:
            envelope = json.loads(raw_data)
        except (json.JSONDecodeError, TypeError):
            return

        inner = envelope.get("data", {})
        price_raw = inner.get("price") or inner.get("trade_price")
        if price_raw is None:
            return

        try:
            current_price = Decimal(str(price_raw))
        except InvalidOperation:
            return

        # 직접 주입 모드 (테스트 등)
        if self._service is not None:
            await self._service.process_ticker(exchange, market, current_price)
            return

        # 프로덕션: 새 DB 세션으로 서비스 인스턴스 생성 후 처리
        if self._session_factory is not None:
            await self._process_with_session(exchange, market, current_price)

    async def _process_with_session(
        self, exchange: str, market: str, current_price: Decimal
    ) -> None:
        """새 AsyncSession으로 서비스 인스턴스 생성 후 process_ticker 실행."""
        from app.core.pubsub import RedisPublisher
        from app.repositories.client_repository import ClientRepository
        from app.repositories.coin_repository import CoinRepository
        from app.repositories.exchange_account_repository import ExchangeAccountRepository
        from app.repositories.notification_repository import NotificationRepository
        from app.repositories.price_alert_repository import PriceAlertRepository
        from app.services.fcm_service import FCMService
        from app.services.notification_service import NotificationService
        from app.services.price_alert_service import PriceAlertService

        async with self._session_factory() as db:
            try:
                alert_repo = PriceAlertRepository(db)
                coin_repo = CoinRepository(db)
                exchange_account_repo = ExchangeAccountRepository(db)
                notification_repo = NotificationRepository()
                client_repo = ClientRepository(db)
                fcm_svc = FCMService(self._settings)
                publisher = RedisPublisher(self._pubsub_redis)
                notification_svc = NotificationService(
                    notification_repo, self._main_redis, publisher
                )

                svc = PriceAlertService(
                    alert_repo,
                    coin_repo,
                    exchange_account_repo,
                    notification_svc,
                    fcm_svc,
                    client_repo,
                    self._main_redis,
                )
                await svc.process_ticker(exchange, market, current_price)
                await db.commit()
            except Exception:
                await db.rollback()
                logger.exception(
                    "PriceAlertMonitor process error: %s %s price=%s",
                    exchange, market, current_price,
                )

    async def stop(self) -> None:
        """lifespan shutdown에서 호출."""
        if self._task:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
        logger.info("PriceAlertMonitor stopped")

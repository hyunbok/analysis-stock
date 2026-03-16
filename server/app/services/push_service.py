"""FCM 푸시 알림 오케스트레이션 서비스.

Rate Limiting + Dedup + NotificationService 저장 + FCMService 멀티캐스트.
모든 알림 유형의 진입점.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import uuid
from decimal import Decimal
from typing import Any

from redis.asyncio import Redis

from app.core.config import Settings
from app.core.redis_keys import RedisKey, RedisTTL
from app.repositories.client_repository import ClientRepository
from app.services.fcm_service import FCMService
from app.services.notification_service import NotificationService

logger = logging.getLogger(__name__)


class PushService:
    """FCM 푸시 알림 오케스트레이터.

    Rate Limiting + Dedup + NotificationService 저장 + FCMService 멀티캐스트.
    모든 알림 유형의 진입점.
    """

    def __init__(
        self,
        fcm_service: FCMService,
        notification_service: NotificationService,
        client_repo: ClientRepository,
        redis: Redis,
        settings: Settings,
    ) -> None:
        self._fcm = fcm_service
        self._notification = notification_service
        self._client_repo = client_repo
        self._redis = redis
        self._rate_limit = settings.FCM_RATE_LIMIT_PER_MINUTE

    async def send_to_user(
        self,
        user_id: uuid.UUID,
        notification_type: str,
        title: str,
        body: str,
        data: dict[str, Any] | None = None,
        *,
        dedup_key: str | None = None,
        silent: bool = False,
    ) -> bool:
        """사용자에게 알림 발송 (핵심 메서드).

        1. Rate Limit 체크 (분당 N건)
        2. Dedup 체크 (1시간 내 동일 dedup_key → skip)
        3. NotificationService.create_notification() — MongoDB 저장 + Redis INCR + Pub/Sub
        4. ClientRepository.get_by_user() → 활성 FCM 토큰 수집
        5. FCMService.send_multicast() or send_silent() — 복수 기기 발송
        6. 무효 토큰 자동 정리 (NotRegistered/InvalidRegistration)
        """
        # 1. Rate Limit
        if not await self._check_rate_limit(user_id):
            logger.info("FCM rate limited: user=%s type=%s", user_id, notification_type)
            return False

        # 2. Dedup
        if dedup_key and not await self._check_dedup(user_id, dedup_key):
            logger.debug("FCM dedup hit: user=%s key=%s", user_id, dedup_key)
            return False

        # str 변환 (한 번만 수행)
        str_data = {k: str(v) for k, v in data.items()} if data else None

        # 3. MongoDB 알림 저장 + Redis + Pub/Sub (silent=True이면 스킵)
        if not silent:
            await self._notification.create_notification(
                user_id=user_id,
                type=notification_type,
                title=title,
                body=body,
                data=str_data,
            )

        # 4. FCM 토큰 수집
        clients = await self._client_repo.get_by_user(user_id)
        fcm_tokens = [c.fcm_token for c in clients if c.fcm_token]
        if not fcm_tokens:
            return True  # 알림 저장은 성공, FCM 기기 없음

        # 5. FCM 발송
        if silent:
            await asyncio.gather(
                *[self._fcm.send_silent(token, str_data or {}) for token in fcm_tokens]
            )
        else:
            _, failed_tokens = await self._fcm.send_multicast(fcm_tokens, title, body, str_data)
            # 6. 무효 토큰 자동 정리
            for token in failed_tokens:
                await self._client_repo.clear_fcm_token_by_value(token)

        return True

    # ── 알림 유형별 헬퍼 ──────────────────────────────────────────────────────

    async def send_order_execution(
        self,
        user_id: uuid.UUID,
        order_id: str,
        coin_symbol: str,
        side: str,
        filled_qty: Decimal,
        price: Decimal,
    ) -> bool:
        """주문 체결 알림."""
        side_kr = "매수" if side == "buy" else "매도"
        title = f"{coin_symbol} {side_kr} 체결 완료"
        body = f"{filled_qty} {coin_symbol.split('/')[0]} @ {price:,}원"
        data = {
            "type": "order_execution",
            "order_id": order_id,
            "coin_symbol": coin_symbol,
            "side": side,
            "filled_qty": str(filled_qty),
            "price": str(price),
        }
        return await self.send_to_user(
            user_id,
            "order_execution",
            title,
            body,
            data,
            dedup_key=f"order:{order_id}",
        )

    async def send_ai_trading_signal(
        self,
        user_id: uuid.UUID,
        signal_type: str,
        coin_symbol: str,
        reason: str,
    ) -> bool:
        """AI 매매 신호 알림."""
        type_kr = {"BUY": "매수", "SELL": "매도", "HOLD": "관망"}.get(signal_type, signal_type)
        title = f"AI {type_kr} 신호 | {coin_symbol}"
        data = {
            "type": "ai_trading_signal",
            "signal_type": signal_type,
            "coin_symbol": coin_symbol,
        }
        return await self.send_to_user(
            user_id,
            "ai_trading_signal",
            title,
            reason,
            data,
            dedup_key=f"ai_signal:{coin_symbol}:{signal_type}",
        )

    async def send_price_alert_notification(
        self,
        user_id: uuid.UUID,
        alert_id: str,
        coin_symbol: str,
        condition: str,
        target_price: Decimal,
        current_price: Decimal,
    ) -> bool:
        """가격 알림."""
        condition_kr = "이상" if condition == "above" else "이하"
        title = f"{coin_symbol} 목표가 도달"
        body = f"{target_price:,}원 {condition_kr} | 현재: {current_price:,}원"
        data = {
            "type": "price_alert",
            "alert_id": alert_id,
            "coin_symbol": coin_symbol,
            "condition": condition,
            "target_price": str(target_price),
            "current_price": str(current_price),
        }
        return await self.send_to_user(
            user_id,
            "price_alert",
            title,
            body,
            data,
            dedup_key=f"price_alert:{alert_id}",
        )

    async def send_system_alert(
        self,
        user_id: uuid.UUID,
        message: str,
        *,
        severity: str = "info",
    ) -> bool:
        """시스템 알림."""
        title_map = {
            "info": "시스템 안내",
            "warning": "시스템 경고",
            "critical": "긴급 알림",
        }
        title = title_map.get(severity, "시스템 알림")
        data = {
            "type": "system_alert",
            "severity": severity,
        }
        return await self.send_to_user(
            user_id,
            "system_alert",
            title,
            message,
            data,
            dedup_key=f"system:{severity}:{hashlib.sha256(message.encode()).hexdigest()[:8]}",
        )

    # ── 내부 메서드 ───────────────────────────────────────────────────────────

    async def _check_rate_limit(self, user_id: uuid.UUID) -> bool:
        """분당 N건 제한. True=허용, False=초과."""
        key = RedisKey.fcm_rate(str(user_id))
        count = await self._redis.incr(key)
        await self._redis.expire(key, RedisTTL.FCM_RATE_WINDOW, nx=True)
        return count <= self._rate_limit

    async def _check_dedup(self, user_id: uuid.UUID, dedup_key: str) -> bool:
        """1시간 내 동일 dedup_key 중복 방지. True=발송 가능, False=중복."""
        dedup_hash = hashlib.sha256(dedup_key.encode()).hexdigest()[:16]
        key = RedisKey.fcm_dedup(str(user_id), dedup_hash)
        acquired = await self._redis.set(key, "1", nx=True, ex=RedisTTL.FCM_DEDUP)
        return bool(acquired)

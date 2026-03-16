"""FCM 푸시 알림 서비스 (스텁)."""
from __future__ import annotations

import logging
from decimal import Decimal

from app.core.config import Settings

logger = logging.getLogger(__name__)


class FCMService:
    def __init__(self, settings: Settings) -> None:
        self._enabled = bool(settings.FCM_SERVER_KEY)

    async def send_price_alert(
        self,
        fcm_token: str,
        coin_symbol: str,
        condition: str,
        target_price: Decimal,
        current_price: Decimal,
    ) -> bool:
        """FCM 발송. 미설정 시 로깅만. 실패 시 False (fire-and-forget)."""
        if not self._enabled:
            logger.debug("FCM disabled, skipping push for %s", coin_symbol)
            return False
        # TODO: FCM v1 API 또는 Firebase Admin SDK 구현
        logger.info(
            "FCM stub: %s %s target=%s current=%s token=%s",
            coin_symbol, condition, target_price, current_price, fcm_token[:8] + "...",
        )
        return False

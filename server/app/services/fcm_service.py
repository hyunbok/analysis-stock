"""FCM 푸시 알림 서비스 — Firebase Admin SDK 기반 저수준 전송."""

from __future__ import annotations

import asyncio
import logging
from decimal import Decimal

from app.core.config import Settings

logger = logging.getLogger(__name__)

# FCM 오류 코드 중 토큰 정리 대상
_INVALID_TOKEN_ERROR_CODES = frozenset(
    [
        "registration-token-not-registered",
        "invalid-registration-token",
    ]
)


class FCMService:
    """Firebase Cloud Messaging 저수준 전송 서비스.

    Settings만 의존. firebase_admin 초기화 + 개별/멀티캐스트/silent 전송.
    FIREBASE_CREDENTIALS_JSON 미설정 시 graceful degradation (로깅만).
    """

    def __init__(self, settings: Settings) -> None:
        self._enabled = False
        if settings.FIREBASE_CREDENTIALS_JSON:
            try:
                import json

                import firebase_admin
                from firebase_admin import credentials

                cred_dict = json.loads(settings.FIREBASE_CREDENTIALS_JSON)
                cred = credentials.Certificate(cred_dict)
                if not firebase_admin._apps:
                    firebase_admin.initialize_app(cred)
                self._enabled = True
            except Exception:
                logger.exception("Failed to initialize Firebase Admin SDK")

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    async def send_notification(
        self,
        fcm_token: str,
        title: str,
        body: str,
        data: dict[str, str] | None = None,
        *,
        collapse_key: str | None = None,
    ) -> bool:
        """알림 + 데이터 푸시. 실패 시 False (fire-and-forget)."""
        if not self._enabled:
            logger.debug("FCM disabled, skipping notification push")
            return False
        from firebase_admin import messaging

        msg = messaging.Message(
            notification=messaging.Notification(title=title, body=body),
            data=data or {},
            token=fcm_token,
            android=messaging.AndroidConfig(
                priority="high",
                collapse_key=collapse_key,
            ),
            apns=messaging.APNSConfig(
                payload=messaging.APNSPayload(aps=messaging.Aps(sound="default"))
            ),
        )
        try:
            await asyncio.to_thread(messaging.send, msg)
            return True
        except Exception:
            logger.exception("FCM send_notification failed: token=%s", fcm_token[:8])
            return False

    async def send_silent(
        self,
        fcm_token: str,
        data: dict[str, str],
    ) -> bool:
        """data-only silent push. 실패 시 False."""
        if not self._enabled:
            return False
        from firebase_admin import messaging

        msg = messaging.Message(
            data=data,
            token=fcm_token,
            android=messaging.AndroidConfig(priority="normal"),
            apns=messaging.APNSConfig(
                headers={"apns-push-type": "background", "apns-priority": "5"}
            ),
        )
        try:
            await asyncio.to_thread(messaging.send, msg)
            return True
        except Exception:
            logger.exception("FCM send_silent failed: token=%s", fcm_token[:8])
            return False

    async def send_multicast(
        self,
        fcm_tokens: list[str],
        title: str,
        body: str,
        data: dict[str, str] | None = None,
    ) -> tuple[int, list[str]]:
        """멀티캐스트 발송.

        Returns:
            (success_count, failed_tokens) — failed_tokens는 무효 토큰 목록
            (NotRegistered/InvalidRegistration → 정리 대상).
        """
        if not self._enabled or not fcm_tokens:
            return 0, []
        from firebase_admin import messaging

        messages = [
            messaging.Message(
                notification=messaging.Notification(title=title, body=body),
                data=data or {},
                token=token,
                android=messaging.AndroidConfig(priority="high"),
                apns=messaging.APNSConfig(
                    payload=messaging.APNSPayload(aps=messaging.Aps(sound="default"))
                ),
            )
            for token in fcm_tokens
        ]

        try:
            response = await asyncio.to_thread(messaging.send_each, messages)
        except Exception:
            logger.exception("FCM send_multicast failed for %d tokens", len(fcm_tokens))
            return 0, []

        failed_tokens: list[str] = []
        for i, send_response in enumerate(response.responses):
            if not send_response.success:
                error = send_response.exception
                error_code = getattr(error, "code", "unknown") if error else "unknown"
                logger.warning(
                    "FCM multicast failed: token=%s error=%s",
                    fcm_tokens[i][:8],
                    error_code,
                )
                if error_code in _INVALID_TOKEN_ERROR_CODES:
                    failed_tokens.append(fcm_tokens[i])

        return response.success_count, failed_tokens

    async def unregister_token(self, fcm_token: str) -> None:
        """Firebase SDK는 토큰 무효화 API를 직접 제공하지 않음.
        토큰 정리는 PushService에서 client_repo.clear_fcm_token_by_value() 호출로 처리."""
        pass

    # ── 하위 호환 메서드 (v1-21) ─────────────────────────────────────────────

    async def send_price_alert(
        self,
        fcm_token: str,
        coin_symbol: str,
        condition: str,
        target_price: Decimal,
        current_price: Decimal,
    ) -> bool:
        """v1-21 하위 호환. send_notification()으로 위임."""
        condition_kr = "이상" if condition == "above" else "이하"
        title = f"{coin_symbol} 목표가 도달"
        body = f"{target_price}원 {condition_kr} | 현재: {current_price}원"
        data = {
            "type": "price_alert",
            "coin_symbol": coin_symbol,
            "condition": condition,
            "target_price": str(target_price),
            "current_price": str(current_price),
        }
        return await self.send_notification(fcm_token, title, body, data)

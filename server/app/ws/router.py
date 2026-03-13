"""WebSocket 메시지 라우터 — action 기반 핸들러 디스패치."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from pydantic import TypeAdapter, ValidationError

from app.schemas.ws import WSInboundMessage
from app.ws.errors import WSErrors
from app.ws.handlers import PingHandler, SubscribeHandler, UnsubscribeHandler

if TYPE_CHECKING:
    from app.ws.bridge import ExchangeStreamBridge
    from app.ws.hub import WSHub
    from app.ws.subscribers import PubSubSubscriber

logger = logging.getLogger(__name__)

# TypeAdapter 모듈 수준 1회 생성 (성능 최적화)
_adapter: TypeAdapter[WSInboundMessage] = TypeAdapter(WSInboundMessage)


class MessageRouter:
    """수신 메시지를 action 필드로 분기하여 핸들러에 위임."""

    def __init__(
        self,
        hub: WSHub,
        subscriber: PubSubSubscriber,
        bridge: ExchangeStreamBridge,
    ) -> None:
        self._hub = hub
        self._subscribe_handler = SubscribeHandler(hub, subscriber, bridge)
        self._unsubscribe_handler = UnsubscribeHandler(hub, subscriber, bridge)
        self._ping_handler = PingHandler(hub)

    async def route(self, conn_id: str, raw: dict) -> None:
        """수신 메시지 파싱 + action 기반 핸들러 디스패치."""
        try:
            msg = _adapter.validate_python(raw)
        except ValidationError as exc:
            logger.warning(
                "invalid WS message conn_id=%s action=%s",
                conn_id,
                raw.get("action"),
            )
            await self._send_error(conn_id, WSErrors.invalid_message(str(exc)))
            return
        except Exception:
            await self._send_error(
                conn_id, WSErrors.invalid_message("Malformed message")
            )
            return

        match msg.action:
            case "subscribe":
                await self._subscribe_handler.handle(conn_id, msg)
            case "unsubscribe":
                await self._unsubscribe_handler.handle(conn_id, msg)
            case "ping":
                await self._ping_handler.handle(conn_id, msg)
            case _:
                # 도달 불가 — Pydantic discriminated union이 미지원 action을
                # ValidationError로 먼저 처리하므로 여기까지 오지 않음
                logger.warning(
                    "unknown WS action conn_id=%s action=%s", conn_id, msg.action
                )
                await self._send_error(
                    conn_id, WSErrors.unknown_action(msg.action)
                )

    async def _send_error(self, conn_id: str, error: dict) -> None:
        await self._hub.send_to_connection(conn_id, error)

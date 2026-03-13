"""WebSocket 엔드포인트 — /ws/v1."""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.schemas.ws import WSConnectedMessage
from app.ws.auth import authenticate_ws
from app.ws.bridge import ExchangeStreamBridge
from app.ws.errors import WSCloseCode, WSErrors
from app.ws.hub import WSHub
from app.ws.router import MessageRouter  # noqa: F401 — app.state type hint용
from app.ws.subscribers import PubSubSubscriber

logger = logging.getLogger(__name__)

router = APIRouter()


@router.websocket("/ws/v1")
async def websocket_endpoint(
    websocket: WebSocket,
    token: str = Query(...),
) -> None:
    """단일 WebSocket 연결 진입점.

    흐름:
        1. JWT 검증 (인증 실패 → close 4001)
        2. 연결 수락 + WSHub 등록 (한계 초과 → close 4003)
        3. connected 메시지 전송
        4. 메시지 수신 루프 → MessageRouter 디스패치
        5. 정리: WSHub.disconnect()

    Raises:
        WebSocketDisconnect: 클라이언트가 연결 종료 시 (정상)
    """
    # 1. JWT 검증 (accept 전)
    user = await authenticate_ws(token)
    if user is None:
        await websocket.close(code=WSCloseCode.UNAUTHORIZED, reason="Unauthorized")
        return

    # 2. app.state에서 싱글턴 획득
    hub: WSHub = websocket.app.state.ws_hub
    bridge: ExchangeStreamBridge = websocket.app.state.ws_bridge
    message_router: MessageRouter = websocket.app.state.ws_router

    # 3. 연결 수락 + Hub 등록
    await websocket.accept()
    conn_id = await hub.connect(websocket, str(user.id))
    if conn_id is None:
        await websocket.close(
            code=WSCloseCode.FORBIDDEN, reason="Connection limit exceeded"
        )
        return

    try:
        # 4. 연결 성공 메시지
        connected_msg = WSConnectedMessage(conn_id=conn_id)
        await websocket.send_text(connected_msg.model_dump_json())

        # 5. 메시지 수신 루프
        while True:
            try:
                text = await websocket.receive_text()
            except WebSocketDisconnect:
                break

            try:
                raw = json.loads(text)
            except json.JSONDecodeError:
                await hub.send_to_connection(
                    conn_id, WSErrors.invalid_message("Invalid JSON")
                )
                continue

            if not isinstance(raw, dict):
                await hub.send_to_connection(
                    conn_id, WSErrors.invalid_message("Expected JSON object")
                )
                continue

            await message_router.route(conn_id, raw)

    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("WS error conn_id=%s", conn_id)
        try:
            await websocket.close(code=WSCloseCode.INTERNAL_ERROR)
        except Exception:
            pass
    finally:
        # 6. 정리 — 시장 채널 bridge 참조 해제 후 Hub 연결 해제
        subscribed_channels = hub.get_subscriptions(conn_id)
        for channel in subscribed_channels:
            # ch:ticker:{exchange}:{market} 패턴 파싱
            parts = channel.split(":")
            if len(parts) == 4 and parts[0] == "ch" and parts[1] in ("ticker", "orderbook", "trades"):
                _, channel_type, exchange, market = parts
                try:
                    await bridge.release_stream(exchange, market, channel_type)
                except Exception:
                    logger.exception(
                        "release_stream failed on disconnect conn_id=%s channel=%s",
                        conn_id, channel,
                    )
        await hub.disconnect(conn_id)

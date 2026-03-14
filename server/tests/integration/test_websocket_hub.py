"""WebSocket Hub 통합 테스트 — /ws/v1 엔드포인트 시나리오 검증.

설계서 §12.6 테스트 패턴 준수.
MockWSHub 대신 실제 WSHub + Mock bridge/subscriber를 사용하여
Hub 상태 검증도 함께 수행한다.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from app.middleware.error_handler import register_error_handlers
from app.ws.hub import WSHub
from app.ws.router import MessageRouter


# ── 헬퍼 ─────────────────────────────────────────────────────────────────────


def _make_user(user_id: str | None = None) -> MagicMock:
    """인증 성공 시 반환할 User 모킹."""
    user = MagicMock()
    user.id = uuid.UUID(user_id) if user_id else uuid.uuid4()
    user.soft_deleted_at = None
    return user


def _make_mock_bridge() -> MagicMock:
    bridge = MagicMock()
    bridge.ensure_stream = AsyncMock()
    bridge.release_stream = AsyncMock()
    return bridge


def _make_mock_subscriber() -> MagicMock:
    sub = MagicMock()
    sub.subscribe_ticker = AsyncMock()
    sub.subscribe_orderbook = AsyncMock()
    sub.subscribe_trades = AsyncMock()
    sub.subscribe_my_orders = AsyncMock()
    sub.subscribe_user_channels = AsyncMock()
    sub.subscribe_system = AsyncMock()
    return sub


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def ws_hub() -> WSHub:
    return WSHub()


@pytest.fixture
def mock_bridge() -> MagicMock:
    return _make_mock_bridge()


@pytest.fixture
def mock_subscriber() -> MagicMock:
    return _make_mock_subscriber()


@pytest.fixture
def test_app(
    ws_hub: WSHub,
    mock_bridge: MagicMock,
    mock_subscriber: MagicMock,
) -> FastAPI:
    """WS 엔드포인트 통합 테스트용 앱 — app.state에 Mock 주입.

    설계서 §12.6: "app.state.*에 Mock 주입으로 대체"
    """
    from app.api.v1.ws import router as ws_router_module

    app = FastAPI()
    register_error_handlers(app)
    app.include_router(ws_router_module)

    # MessageRouter 싱글턴 (lifespan 대체)
    ws_router = MessageRouter(ws_hub, mock_subscriber, mock_bridge)
    app.state.ws_hub = ws_hub
    app.state.ws_bridge = mock_bridge
    app.state.ws_subscriber = mock_subscriber
    app.state.ws_router = ws_router
    return app


# ── 시나리오 1: 유효한 토큰으로 연결 → connected 메시지 수신 ──────────────────


def test_ws_connect_receives_connected_message(test_app: FastAPI, ws_hub: WSHub):
    """유효한 토큰 → WebSocket accept + connected 메시지 수신."""
    mock_user = _make_user()

    with patch("app.api.v1.ws.authenticate_ws", AsyncMock(return_value=mock_user)):
        with TestClient(test_app).websocket_connect("/ws/v1?token=valid-token") as ws:
            msg = ws.receive_json()

            assert msg["action"] == "connected"
            assert "conn_id" in msg
            assert len(msg["conn_id"]) == 36  # UUID4 형식
            assert "timestamp" in msg
            # Hub에 연결 등록 확인
            assert ws_hub.get_connection_count() == 1

    # 연결 종료 후 Hub에서 제거 확인
    assert ws_hub.get_connection_count() == 0


# ── 시나리오 2: ticker 구독 → subscribed 응답 ─────────────────────────────────


def test_ws_subscribe_ticker(
    test_app: FastAPI,
    ws_hub: WSHub,
    mock_bridge: MagicMock,
    mock_subscriber: MagicMock,
):
    """ticker 구독 요청 → subscribed 응답 + Redis/bridge 호출."""
    mock_user = _make_user()

    with patch("app.api.v1.ws.authenticate_ws", AsyncMock(return_value=mock_user)):
        with TestClient(test_app).websocket_connect("/ws/v1?token=valid-token") as ws:
            ws.receive_json()  # connected

            ws.send_json({
                "action": "subscribe",
                "channel": "ticker",
                "exchange": "upbit",
                "market": "KRW-BTC",
            })
            msg = ws.receive_json()

    assert msg["action"] == "subscribed"
    assert msg["channel"] == "ticker"
    assert msg["exchange"] == "upbit"
    assert msg["market"] == "KRW-BTC"
    assert "timestamp" in msg
    mock_subscriber.subscribe_ticker.assert_called_once_with("upbit", "KRW-BTC")
    mock_bridge.ensure_stream.assert_called_once_with("upbit", "KRW-BTC", "ticker")


# ── 시나리오 3: 구독 해제 → unsubscribed 응답 ────────────────────────────────


def test_ws_unsubscribe_ticker(
    test_app: FastAPI,
    mock_bridge: MagicMock,
    mock_subscriber: MagicMock,
):
    """ticker 구독 후 해제 → unsubscribed 응답 + bridge.release_stream 호출."""
    mock_user = _make_user()

    with patch("app.api.v1.ws.authenticate_ws", AsyncMock(return_value=mock_user)):
        with TestClient(test_app).websocket_connect("/ws/v1?token=valid-token") as ws:
            ws.receive_json()  # connected

            ws.send_json({
                "action": "subscribe",
                "channel": "ticker",
                "exchange": "upbit",
                "market": "KRW-BTC",
            })
            ws.receive_json()  # subscribed

            ws.send_json({
                "action": "unsubscribe",
                "channel": "ticker",
                "exchange": "upbit",
                "market": "KRW-BTC",
            })
            msg = ws.receive_json()

    assert msg["action"] == "unsubscribed"
    assert msg["channel"] == "ticker"
    assert msg["exchange"] == "upbit"
    assert msg["market"] == "KRW-BTC"
    mock_bridge.release_stream.assert_called_once_with("upbit", "KRW-BTC", "ticker")


# ── 시나리오 4: 잘못된 메시지 → error 응답 (연결 유지) ───────────────────────


def test_ws_invalid_message_sends_error_and_keeps_connection(test_app: FastAPI):
    """action 없는 JSON → INVALID_MESSAGE 에러 + 연결 유지 확인."""
    mock_user = _make_user()

    with patch("app.api.v1.ws.authenticate_ws", AsyncMock(return_value=mock_user)):
        with TestClient(test_app).websocket_connect("/ws/v1?token=valid-token") as ws:
            ws.receive_json()  # connected

            # action 없음
            ws.send_json({"foo": "bar"})
            error_msg = ws.receive_json()

            assert error_msg["action"] == "error"
            assert error_msg["code"] == "INVALID_MESSAGE"

            # 연결 유지 확인 — ping 가능
            ws.send_json({"action": "ping"})
            pong = ws.receive_json()
            assert pong["action"] == "pong"


def test_ws_invalid_json_string_sends_error(test_app: FastAPI):
    """JSON 파싱 불가 문자열 → INVALID_MESSAGE 에러."""
    mock_user = _make_user()

    with patch("app.api.v1.ws.authenticate_ws", AsyncMock(return_value=mock_user)):
        with TestClient(test_app).websocket_connect("/ws/v1?token=valid-token") as ws:
            ws.receive_json()  # connected

            ws.send_text("not-valid-json{{{")
            error_msg = ws.receive_json()

            assert error_msg["action"] == "error"
            assert error_msg["code"] == "INVALID_MESSAGE"


# ── 시나리오 5: 구독 한계 초과 → error 메시지 (연결 유지) ───────────────────


def test_ws_subscription_limit_exceeded_keeps_connection(test_app: FastAPI):
    """연결당 구독 한계 초과 → SUBSCRIPTION_LIMIT_EXCEEDED + 연결 유지."""
    mock_user = _make_user()

    with patch("app.api.v1.ws.authenticate_ws", AsyncMock(return_value=mock_user)):
        with patch("app.ws.handlers.settings") as mock_settings:
            mock_settings.WS_MAX_SUBSCRIPTIONS_PER_CONN = 2

            with TestClient(test_app).websocket_connect("/ws/v1?token=valid-token") as ws:
                ws.receive_json()  # connected

                # 개인 채널 2개로 한계 채우기 (bridge 불필요)
                ws.send_json({"action": "subscribe", "channel": "my-orders"})
                ws.receive_json()  # subscribed

                ws.send_json({"action": "subscribe", "channel": "notification"})
                ws.receive_json()  # subscribed

                # 3번째 → 한계 초과
                ws.send_json({"action": "subscribe", "channel": "system"})
                error_msg = ws.receive_json()

                assert error_msg["action"] == "error"
                assert error_msg["code"] == "SUBSCRIPTION_LIMIT_EXCEEDED"
                assert "Maximum" in error_msg["message"]

                # 연결 유지 확인
                ws.send_json({"action": "ping"})
                pong = ws.receive_json()
                assert pong["action"] == "pong"


# ── 시나리오 6: 토큰 없이/만료된 토큰 → close code 4001 ─────────────────────


def test_ws_unauthorized_rejected(test_app: FastAPI, ws_hub: WSHub):
    """인증 실패(토큰 없음/만료) → WS 연결 거부."""
    with patch("app.api.v1.ws.authenticate_ws", AsyncMock(return_value=None)):
        with pytest.raises(Exception):
            with TestClient(test_app).websocket_connect("/ws/v1?token=bad-token") as ws:
                ws.receive_json()  # 여기까지 도달하면 안 됨

    # Hub에 연결이 등록되지 않음
    assert ws_hub.get_connection_count() == 0


# ── 시나리오 7: ping → pong 응답 ──────────────────────────────────────────────


def test_ws_ping_pong_response(test_app: FastAPI, ws_hub: WSHub):
    """ping 메시지 → pong 응답 + timestamp 포함 + last_ping 갱신."""
    mock_user = _make_user()

    with patch("app.api.v1.ws.authenticate_ws", AsyncMock(return_value=mock_user)):
        with TestClient(test_app).websocket_connect("/ws/v1?token=valid-token") as ws:
            connected = ws.receive_json()
            conn_id = connected["conn_id"]

            conn_before = ws_hub.get_connection(conn_id)
            assert conn_before is not None
            ping_before = conn_before.last_ping

            ws.send_json({"action": "ping"})
            msg = ws.receive_json()

            assert msg["action"] == "pong"
            assert "timestamp" in msg

            # last_ping 갱신 확인
            assert conn_before.last_ping >= ping_before


# ── 추가 시나리오: 개인 채널 구독 (bridge 미호출) ──────────────────────────


def test_ws_subscribe_personal_channel_no_bridge(
    test_app: FastAPI,
    mock_bridge: MagicMock,
    mock_subscriber: MagicMock,
):
    """개인 채널(my-orders) 구독 → bridge.ensure_stream 미호출."""
    mock_user = _make_user()

    with patch("app.api.v1.ws.authenticate_ws", AsyncMock(return_value=mock_user)):
        with TestClient(test_app).websocket_connect("/ws/v1?token=valid-token") as ws:
            ws.receive_json()  # connected

            ws.send_json({"action": "subscribe", "channel": "my-orders"})
            msg = ws.receive_json()

    assert msg["action"] == "subscribed"
    assert msg["channel"] == "my-orders"
    mock_subscriber.subscribe_my_orders.assert_called_once()
    mock_bridge.ensure_stream.assert_not_called()


# ── 추가 시나리오: 연결 종료 시 bridge 참조 해제 (CRITICAL 수정 검증) ────────


def test_ws_disconnect_releases_bridge_streams(
    test_app: FastAPI,
    ws_hub: WSHub,
    mock_bridge: MagicMock,
):
    """연결 종료 시 시장 채널 bridge.release_stream 호출 — CRITICAL 버그 수정 검증."""
    mock_user = _make_user()

    with patch("app.api.v1.ws.authenticate_ws", AsyncMock(return_value=mock_user)):
        with TestClient(test_app).websocket_connect("/ws/v1?token=valid-token") as ws:
            ws.receive_json()  # connected

            ws.send_json({
                "action": "subscribe",
                "channel": "ticker",
                "exchange": "upbit",
                "market": "KRW-BTC",
            })
            ws.receive_json()  # subscribed

        # 연결 종료 후
        mock_bridge.release_stream.assert_called_with("upbit", "KRW-BTC", "ticker")
        assert ws_hub.get_connection_count() == 0


def test_ws_disconnect_personal_channel_does_not_call_release_stream(
    test_app: FastAPI,
    mock_bridge: MagicMock,
):
    """연결 종료 시 개인 채널은 bridge.release_stream 미호출."""
    mock_user = _make_user()

    with patch("app.api.v1.ws.authenticate_ws", AsyncMock(return_value=mock_user)):
        with TestClient(test_app).websocket_connect("/ws/v1?token=valid-token") as ws:
            ws.receive_json()  # connected

            ws.send_json({"action": "subscribe", "channel": "my-orders"})
            ws.receive_json()  # subscribed

    # 개인 채널은 bridge 참조 없으므로 release 미호출
    mock_bridge.release_stream.assert_not_called()


# ── 추가 시나리오: 중복 구독 시 ref_count 이중 증가 방지 ─────────────────────


def test_ws_duplicate_subscribe_does_not_double_ref_count(
    test_app: FastAPI,
    mock_bridge: MagicMock,
    mock_subscriber: MagicMock,
):
    """동일 채널 중복 구독 → ensure_stream 1회만 호출 (ref_count 이중 방지)."""
    mock_user = _make_user()

    with patch("app.api.v1.ws.authenticate_ws", AsyncMock(return_value=mock_user)):
        with TestClient(test_app).websocket_connect("/ws/v1?token=valid-token") as ws:
            ws.receive_json()  # connected

            # 동일 채널 2회 구독
            ws.send_json({
                "action": "subscribe",
                "channel": "ticker",
                "exchange": "upbit",
                "market": "KRW-BTC",
            })
            ws.receive_json()  # subscribed (1st)

            ws.send_json({
                "action": "subscribe",
                "channel": "ticker",
                "exchange": "upbit",
                "market": "KRW-BTC",
            })
            ws.receive_json()  # subscribed (2nd — hub에선 중복 무시)

    # ensure_stream은 is_new=True 일 때만 → 1회만 호출
    assert mock_bridge.ensure_stream.call_count == 1

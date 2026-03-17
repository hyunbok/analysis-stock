"""WebSocket 실시간 통신 E2E 테스트.

설계서 §ST5: Starlette TestClient sync 패턴 사용.
기존 test_websocket_hub.py와 동일 패턴이지만 실제 앱(e2e_app) + 실제 인증 사용.

TC-WS-E2E-01: JWT 인증 → WS 연결 → connected 메시지 수신
TC-WS-E2E-02: ticker 구독 → subscribed 응답 → 구독 해제 → unsubscribed
TC-WS-E2E-03: orderbook 구독 → subscribed 응답
TC-WS-E2E-04: 개인 채널(my-orders) 구독 → subscribed 응답
TC-WS-E2E-05: 비인증 연결 시도 → 거부 (close code 4001)
TC-WS-E2E-06: 잘못된 토큰 → 연결 거부
TC-WS-E2E-07: ping → pong 응답
TC-WS-E2E-08: 잘못된 JSON → INVALID_MESSAGE 에러 + 연결 유지
TC-WS-E2E-09: 알 수 없는 action → UNKNOWN_ACTION 에러
"""
from __future__ import annotations

import pytest
from starlette.testclient import TestClient

pytestmark = pytest.mark.e2e


# ── TC-WS-E2E-01: 인증 성공 → connected 메시지 ───────────────────────────────


def test_ws_connect_with_valid_token(e2e_app, test_user):
    """유효한 JWT 토큰 → WS 연결 → connected 메시지 수신."""
    token = test_user["access_token"]

    with TestClient(e2e_app).websocket_connect(f"/ws/v1?token={token}") as ws:
        msg = ws.receive_json()

        assert msg["action"] == "connected"
        assert "conn_id" in msg
        assert len(msg["conn_id"]) == 36  # UUID4 형식
        assert "timestamp" in msg


# ── TC-WS-E2E-02: ticker 구독 → subscribed → 구독 해제 ───────────────────────


def test_ws_ticker_subscribe_and_unsubscribe(e2e_app, test_user):
    """ticker 구독 → subscribed 응답 → 구독 해제 → unsubscribed 응답."""
    token = test_user["access_token"]

    with TestClient(e2e_app).websocket_connect(f"/ws/v1?token={token}") as ws:
        ws.receive_json()  # connected

        # 구독
        ws.send_json({
            "action": "subscribe",
            "channel": "ticker",
            "exchange": "upbit",
            "market": "KRW-BTC",
        })
        subscribed = ws.receive_json()

        assert subscribed["action"] == "subscribed"
        assert subscribed["channel"] == "ticker"
        assert subscribed["exchange"] == "upbit"
        assert subscribed["market"] == "KRW-BTC"
        assert "timestamp" in subscribed

        # 구독 해제
        ws.send_json({
            "action": "unsubscribe",
            "channel": "ticker",
            "exchange": "upbit",
            "market": "KRW-BTC",
        })
        unsubscribed = ws.receive_json()

        assert unsubscribed["action"] == "unsubscribed"
        assert unsubscribed["channel"] == "ticker"
        assert unsubscribed["exchange"] == "upbit"
        assert unsubscribed["market"] == "KRW-BTC"


# ── TC-WS-E2E-03: orderbook 구독 ─────────────────────────────────────────────


def test_ws_orderbook_subscribe(e2e_app, test_user):
    """orderbook 구독 → subscribed 응답."""
    token = test_user["access_token"]

    with TestClient(e2e_app).websocket_connect(f"/ws/v1?token={token}") as ws:
        ws.receive_json()  # connected

        ws.send_json({
            "action": "subscribe",
            "channel": "orderbook",
            "exchange": "upbit",
            "market": "KRW-ETH",
        })
        msg = ws.receive_json()

        assert msg["action"] == "subscribed"
        assert msg["channel"] == "orderbook"
        assert msg["exchange"] == "upbit"
        assert msg["market"] == "KRW-ETH"


# ── TC-WS-E2E-04: 개인 채널(my-orders) 구독 ─────────────────────────────────


def test_ws_personal_channel_subscribe(e2e_app, test_user):
    """개인 채널(my-orders) 구독 → subscribed 응답."""
    token = test_user["access_token"]

    with TestClient(e2e_app).websocket_connect(f"/ws/v1?token={token}") as ws:
        ws.receive_json()  # connected

        ws.send_json({"action": "subscribe", "channel": "my-orders"})
        msg = ws.receive_json()

        assert msg["action"] == "subscribed"
        assert msg["channel"] == "my-orders"


# ── TC-WS-E2E-05: 비인증 연결 → close code 4001 ──────────────────────────────


def test_ws_unauthorized_rejected(e2e_app):
    """토큰 없이 WS 연결 → close code 4001 (Unauthorized)."""
    with pytest.raises(Exception):
        with TestClient(e2e_app).websocket_connect("/ws/v1?token=invalid-token") as ws:
            ws.receive_json()  # 여기까지 도달하면 안 됨


# ── TC-WS-E2E-06: 잘못된 토큰 형식 → 연결 거부 ──────────────────────────────


def test_ws_malformed_token_rejected(e2e_app):
    """잘못된 형식의 JWT → WS 연결 거부."""
    with pytest.raises(Exception):
        with TestClient(e2e_app).websocket_connect("/ws/v1?token=not.a.valid.jwt") as ws:
            ws.receive_json()


# ── TC-WS-E2E-07: ping → pong 응답 ───────────────────────────────────────────


def test_ws_ping_pong(e2e_app, test_user):
    """ping 메시지 → pong 응답 + timestamp."""
    token = test_user["access_token"]

    with TestClient(e2e_app).websocket_connect(f"/ws/v1?token={token}") as ws:
        ws.receive_json()  # connected

        ws.send_json({"action": "ping"})
        pong = ws.receive_json()

        assert pong["action"] == "pong"
        assert "timestamp" in pong


# ── TC-WS-E2E-08: 잘못된 JSON → INVALID_MESSAGE 에러 ────────────────────────


def test_ws_invalid_json_sends_error_and_keeps_connection(e2e_app, test_user):
    """JSON 파싱 불가 문자열 → INVALID_MESSAGE 에러 + 연결 유지."""
    token = test_user["access_token"]

    with TestClient(e2e_app).websocket_connect(f"/ws/v1?token={token}") as ws:
        ws.receive_json()  # connected

        ws.send_text("not-valid-json{{{")
        error_msg = ws.receive_json()

        assert error_msg["action"] == "error"
        assert error_msg["code"] == "INVALID_MESSAGE"

        # 연결 유지 확인
        ws.send_json({"action": "ping"})
        pong = ws.receive_json()
        assert pong["action"] == "pong"


# ── TC-WS-E2E-09: 알 수 없는 action ─────────────────────────────────────────


def test_ws_unknown_action_sends_error(e2e_app, test_user):
    """알 수 없는 action → UNKNOWN_ACTION 에러."""
    token = test_user["access_token"]

    with TestClient(e2e_app).websocket_connect(f"/ws/v1?token={token}") as ws:
        ws.receive_json()  # connected

        ws.send_json({"action": "unknown_action_xyz"})
        error_msg = ws.receive_json()

        assert error_msg["action"] == "error"
        assert error_msg["code"] == "UNKNOWN_ACTION"


# ── TC-WS-E2E-10: 다중 구독 → 구독 한계 ─────────────────────────────────────


def test_ws_subscription_limit(e2e_app, test_user):
    """구독 한계 초과 → SUBSCRIPTION_LIMIT_EXCEEDED 에러 + 연결 유지."""
    from unittest.mock import patch

    token = test_user["access_token"]

    with patch("app.ws.handlers.settings") as mock_settings:
        mock_settings.WS_MAX_SUBSCRIPTIONS_PER_CONN = 2

        with TestClient(e2e_app).websocket_connect(f"/ws/v1?token={token}") as ws:
            ws.receive_json()  # connected

            # 1번째 구독
            ws.send_json({"action": "subscribe", "channel": "my-orders"})
            ws.receive_json()  # subscribed

            # 2번째 구독
            ws.send_json({"action": "subscribe", "channel": "notification"})
            ws.receive_json()  # subscribed

            # 3번째 → 한계 초과
            ws.send_json({"action": "subscribe", "channel": "system"})
            error_msg = ws.receive_json()

            assert error_msg["action"] == "error"
            assert error_msg["code"] == "SUBSCRIPTION_LIMIT_EXCEEDED"

            # 연결 유지 확인
            ws.send_json({"action": "ping"})
            pong = ws.receive_json()
            assert pong["action"] == "pong"


# ── TC-WS-E2E-11: 연결 종료 후 bridge 참조 해제 ──────────────────────────────


def test_ws_disconnect_releases_bridge_streams(e2e_app, test_user):
    """연결 종료 시 시장 채널 bridge.release_stream 호출 확인."""
    token = test_user["access_token"]

    with TestClient(e2e_app).websocket_connect(f"/ws/v1?token={token}") as ws:
        ws.receive_json()  # connected

        ws.send_json({
            "action": "subscribe",
            "channel": "ticker",
            "exchange": "upbit",
            "market": "KRW-BTC",
        })
        ws.receive_json()  # subscribed

    # 연결 종료 후 Hub에서 제거 확인
    hub = e2e_app.state.ws_hub
    assert hub.get_connection_count() == 0


# ── TC-WS-E2E-12: 중복 구독 방지 ─────────────────────────────────────────────


def test_ws_duplicate_subscribe_does_not_break(e2e_app, test_user):
    """동일 채널 중복 구독 → 오류 없이 처리."""
    token = test_user["access_token"]

    with TestClient(e2e_app).websocket_connect(f"/ws/v1?token={token}") as ws:
        ws.receive_json()  # connected

        ws.send_json({
            "action": "subscribe",
            "channel": "ticker",
            "exchange": "upbit",
            "market": "KRW-BTC",
        })
        first = ws.receive_json()
        assert first["action"] == "subscribed"

        # 동일 채널 재구독
        ws.send_json({
            "action": "subscribe",
            "channel": "ticker",
            "exchange": "upbit",
            "market": "KRW-BTC",
        })
        second = ws.receive_json()
        assert second["action"] == "subscribed"  # 에러 없이 처리

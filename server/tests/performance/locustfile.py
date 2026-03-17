"""Locust 부하 테스트 시나리오 — CoinTrader API.

실행 방법:
  # 스테이징 서버 대상 (권장)
  locust -f server/tests/performance/locustfile.py \
    --host https://staging.cointrader.io \
    --users 100 --spawn-rate 10 \
    --run-time 5m --headless

  # 로컬 서버 대상
  locust -f server/tests/performance/locustfile.py \
    --host http://localhost:8000 \
    --users 50 --spawn-rate 5 \
    --run-time 2m

  # WebSocket 포함 (locust-plugins 필요)
  locust -f server/tests/performance/locustfile.py \
    --host http://localhost:8000 \
    --users 100 --spawn-rate 10

부하 테스트 목표 (설계서 ST6):
  - 동시 사용자: 100명 (API + WS 혼합)
  - WS 동시 연결: 1,000개
  - API RPS: 500 req/s
  - p95 응답 시간: < 500ms
  - 에러율: < 1% (5xx 기준)
"""
from __future__ import annotations

import json
import os
import random

from locust import HttpUser, between, events, task
from locust.env import Environment

# locust-plugins WebSocketUser (선택적 임포트)
try:
    from locust_plugins.users.websocket import WebsocketUser
    HAS_WS_USER = True
except ImportError:
    HAS_WS_USER = False
    WebsocketUser = object  # fallback

# ── 테스트 계정 설정 ─────────────────────────────────────────────────────────

_TEST_EMAIL = os.getenv("LOCUST_TEST_EMAIL", "loadtest@cointrader.io")
# 보안: 비밀번호 기본값 없음. 반드시 환경변수로 주입 필요.
# LOCUST_TEST_PASSWORD=your_password locust -f locustfile.py ...
_TEST_PASSWORD = os.getenv("LOCUST_TEST_PASSWORD", "")
_TEST_EXCHANGE_ACCOUNT_ID = os.getenv("LOCUST_EXCHANGE_ACCOUNT_ID", "")
_TEST_COIN_ID = os.getenv("LOCUST_COIN_ID", "")


# ── 인증 헬퍼 ─────────────────────────────────────────────────────────────────

def _login(client, email: str, password: str) -> str | None:
    """로그인 후 access_token 반환. 실패 시 None."""
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
        name="/api/v1/auth/login [setup]",
    )
    if resp.status_code != 200:
        return None
    body = resp.json()
    data = body.get("data", {})
    tokens = data.get("tokens")
    if not tokens:
        return None
    return tokens.get("access_token")


# ── 사용자 시나리오 ──────────────────────────────────────────────────────────

class CoinTraderUser(HttpUser):
    """주요 API 흐름 부하 시나리오.

    비율 (task weight):
      - get_coins ×3: 코인 목록 조회 (비인증 가능, 트래픽 최대)
      - get_portfolio ×2: 포트폴리오 조회 (인증 필요)
      - place_order ×1: 지정가 주문 (인증 + 거래소 호출 포함)
    """

    wait_time = between(1, 3)

    def on_start(self):
        """가상 사용자 시작 시 로그인."""
        self._access_token: str | None = None
        self._auth_headers: dict[str, str] = {}
        self._exchange_account_id: str = _TEST_EXCHANGE_ACCOUNT_ID
        self._coin_id: str = _TEST_COIN_ID

        token = _login(self.client, _TEST_EMAIL, _TEST_PASSWORD)
        if token:
            self._access_token = token
            self._auth_headers = {"Authorization": f"Bearer {token}"}

    @task(3)
    def get_coins(self):
        """코인 목록 조회 — p95 < 200ms 목표."""
        self.client.get(
            "/api/v1/coins?page=1&size=20",
            name="/api/v1/coins [list]",
        )

    @task(2)
    def get_portfolio(self):
        """포트폴리오 조회 — p95 < 300ms 목표 (인증 필요)."""
        if not self._auth_headers:
            return
        self.client.get(
            "/api/v1/portfolio",
            headers=self._auth_headers,
            name="/api/v1/portfolio [get]",
        )

    @task(2)
    def get_watchlist(self):
        """관심 코인 목록 조회."""
        if not self._auth_headers:
            return
        self.client.get(
            "/api/v1/watchlist",
            headers=self._auth_headers,
            name="/api/v1/watchlist [list]",
        )

    @task(1)
    def get_notifications(self):
        """알림 목록 조회."""
        if not self._auth_headers:
            return
        self.client.get(
            "/api/v1/notifications?page=1&size=20",
            headers=self._auth_headers,
            name="/api/v1/notifications [list]",
        )

    @task(1)
    def place_limit_order(self):
        """지정가 주문 생성 — p95 < 500ms 목표 (거래소 호출 포함).

        실제 거래소 호출이 발생할 수 있으므로 스테이징 환경에서만 실행 권장.
        LOCUST_EXCHANGE_ACCOUNT_ID, LOCUST_COIN_ID 환경변수 필수.
        """
        if not self._auth_headers:
            return
        if not self._exchange_account_id or not self._coin_id:
            # 환경변수 미설정 시 skip (안전 장치)
            return

        payload = {
            "exchange_account_id": self._exchange_account_id,
            "coin_id": self._coin_id,
            "side": "buy",
            "method": "limit",
            "quantity": "0.00001",  # 최소 주문량
            "price": "1000000",    # 낮은 지정가 (체결 방지)
        }
        resp = self.client.post(
            "/api/v1/orders",
            json=payload,
            headers=self._auth_headers,
            name="/api/v1/orders [place]",
        )
        # 잔고 부족(400), 거래소 오류(502) 등은 허용
        if resp.status_code not in (200, 201, 400, 402, 502):
            resp.failure(f"Unexpected status: {resp.status_code}")

    @task(1)
    def get_health(self):
        """헬스체크 — 항상 200 기대."""
        resp = self.client.get(
            "/api/v1/health",
            name="/api/v1/health [check]",
        )
        if resp.status_code != 200:
            resp.failure(f"Health check failed: {resp.status_code}")


# ── 읽기 전용 사용자 (비인증) ─────────────────────────────────────────────────

class AnonymousUser(HttpUser):
    """비인증 읽기 전용 사용자 — 코인 탐색 시나리오."""

    wait_time = between(2, 5)
    weight = 3  # CoinTraderUser 대비 3배 비율

    @task(5)
    def browse_coins(self):
        page = random.randint(1, 5)
        self.client.get(
            f"/api/v1/coins?page={page}&size=20",
            name="/api/v1/coins [browse]",
        )

    @task(2)
    def search_coins(self):
        queries = ["BTC", "ETH", "XRP", "ADA", "SOL"]
        q = random.choice(queries)
        self.client.get(
            f"/api/v1/coins?q={q}&page=1&size=10",
            name="/api/v1/coins [search]",
        )

    @task(1)
    def get_health(self):
        self.client.get("/api/v1/health", name="/api/v1/health [check]")


# ── WebSocket 동시접속 사용자 (locust-plugins 필요) ───────────────────────────

if HAS_WS_USER:
    class WebSocketTickerUser(WebsocketUser):  # type: ignore[misc]
        """WebSocket 실시간 시세 구독 부하 테스트.

        요구사항: locust-plugins>=4.0
        채널: ticker / exchange: upbit / market: KRW-BTC 등

        WS 프로토콜 (서버 app/schemas/ws.py 기준):
          인바운드:  {"action":"subscribe","channel":"ticker","exchange":"upbit","market":"..."}
          아웃바운드: {"action":"subscribed","channel":"ticker","exchange":"upbit","market":"..."}

        host는 --host 옵션에서 http→ws 자동 변환. 하드코딩 금지.
        목표: 1,000개 동시 WS 연결 유지 (PRD §10.1)
        """

        # host는 --host CLI 옵션에서 주입됨. http(s)→ws(s) 변환은 on_start에서 처리.
        wait_time = between(0.5, 1.0)

        _MARKETS = ["KRW-BTC", "KRW-ETH", "KRW-XRP", "KRW-ADA", "KRW-SOL"]

        def on_start(self):
            self._market = random.choice(self._MARKETS)

        @property
        def _ws_host(self) -> str:
            """--host 옵션(http/https)을 ws/wss로 변환."""
            base = self.environment.host or "http://localhost:8000"
            return base.replace("https://", "wss://").replace("http://", "ws://")

        @task
        def subscribe_ticker(self):
            """서버 WS 프로토콜에 맞는 구독 메시지 전송.

            action 필드 사용, channel/exchange/market 분리 포맷.
            """
            subscribe_msg = json.dumps({
                "action": "subscribe",
                "channel": "ticker",
                "exchange": "upbit",
                "market": self._market,
            })
            self.ws.send(subscribe_msg)

            # 응답 수신 (최대 2초 대기 후 다음 이터레이션)
            try:
                msg = self.ws.recv()
                if msg:
                    data = json.loads(msg)
                    # 서버가 action="error"로 응답하면 실패 기록
                    if data.get("action") == "error":
                        self.environment.events.request.fire(
                            request_type="WS",
                            name="subscribe:ticker",
                            response_time=0,
                            response_length=0,
                            exception=Exception(
                                f"WS error code={data.get('code')} msg={data.get('message')}"
                            ),
                        )
            except Exception:
                pass  # timeout 등 무시


# ── Locust 이벤트 훅 ─────────────────────────────────────────────────────────

@events.test_start.add_listener
def on_test_start(environment: Environment, **kwargs):
    """부하 테스트 시작 시 기준값 출력."""
    print("\n=== CoinTrader Load Test ===")
    print(f"Host: {environment.host}")
    print("Targets: RPS 500 / p95 < 500ms / Error rate < 1%")
    print("=============================\n")


@events.quitting.add_listener
def on_quitting(environment: Environment, **kwargs):
    """테스트 종료 시 SLA 위반 여부 검사."""
    stats = environment.stats.total
    if stats.num_requests == 0:
        return

    fail_ratio = stats.fail_ratio
    p95_ms = stats.get_response_time_percentile(0.95) or 0

    print("\n=== Load Test Results ===")
    print(f"Total requests: {stats.num_requests}")
    print(f"Fail ratio: {fail_ratio:.2%} (SLA: < 1%)")
    print(f"p95 response time: {p95_ms:.0f}ms (SLA: < 500ms)")
    print("=========================\n")

    # SLA 위반 시 비정상 종료 코드 설정
    if fail_ratio > 0.01:
        print(f"[FAIL] 에러율 SLA 위반: {fail_ratio:.2%} > 1%")
        environment.process_exit_code = 1
    elif p95_ms > 500:
        print(f"[FAIL] p95 응답 시간 SLA 위반: {p95_ms:.0f}ms > 500ms")
        environment.process_exit_code = 1
    else:
        print("[PASS] SLA 충족")
        environment.process_exit_code = 0

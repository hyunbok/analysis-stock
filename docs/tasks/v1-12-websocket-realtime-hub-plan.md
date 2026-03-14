# v1-12 WebSocket 실시간 시세 허브 — 설계서

> **작성**: project-architect (시스템 아키텍처/흐름/동시성/에러), code-architect (파일 구조/메시지 스키마/코드 패턴)
> **대상 태스크**: v1-12 — WebSocket 실시간 시세 허브 구현
> **현재 상태**: 구현 완료 — ST1~ST10 전체 완료, 코드 리뷰 통과, 테스트 66/66 통과

---

## 1. 개요

단일 WebSocket 연결(`ws://server/ws/v1?token={access_token}`)을 통해 클라이언트가 여러 채널(ticker, orderbook, trades, my-orders 등)을 구독하고, 거래소 실시간 데이터를 수신하는 허브 시스템을 구현한다.

**의존성**: v1-8 (Exchange Abstraction Layer), v1-9 (Upbit), v1-10 (CoinOne), v1-11 (Exchange Account)

**핵심 요구사항**:
- 단일 WS 연결 + JSON 메시지 기반 구독/해제
- Exchange Provider WS → Redis Pub/Sub → WS Hub → Client 브로드캐스트
- 동시 연결 1,000개 지원
- JWT 토큰 인증 (query param)
- 채널: ticker, orderbook, trades, my-orders, ai-signal, notification, price-alert, system
- 에러 처리: 토큰 만료, 구독 한계, 거래소 끊김

**기존 구현 활용**:
- `ws/subscribers.py`: PubSubSubscriber (Redis → WS Hub 브리지) — 이미 구현 완료
- `core/redis_keys.py`: PubSubChannel (채널명 패턴) — 이미 정의 완료
- `core/pubsub.py`: RedisPublisher (채널별 publish) — 이미 구현 완료
- `core/redis.py`: 일반 풀(50) + Pub/Sub 전용 풀(20, timeout=None) — 이미 분리 완료

---

## 2. 시스템 아키텍처

### 2.1 전체 구조도

```
┌──────────────────────────────────────────────────────────────────┐
│                       Flutter Client                              │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐               │
│  │  WS Client  │  │  WS Client  │  │  WS Client  │  ... (N)      │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘               │
└─────────┼────────────────┼────────────────┼──────────────────────┘
          │ ws://server/ws/v1?token=JWT     │
          │         (단일 연결)               │
┌─────────▼────────────────▼────────────────▼──────────────────────┐
│                     FastAPI Server                                 │
│                                                                    │
│  ┌────────────────────────────────────────────────────────────┐   │
│  │                    WS Endpoint (api/v1/ws.py)               │   │
│  │  - JWT 검증 (query param token)                             │   │
│  │  - WebSocket accept/reject                                  │   │
│  │  - 메시지 수신 루프 → MessageRouter                          │   │
│  └────────────────────────┬───────────────────────────────────┘   │
│                           │                                        │
│  ┌────────────────────────▼───────────────────────────────────┐   │
│  │                    WSHub (ws/hub.py)                         │   │
│  │                                                              │   │
│  │  ┌──────────────────┐  ┌──────────────────┐                 │   │
│  │  │ ConnectionManager │  │ ChannelManager   │                 │   │
│  │  │                   │  │                   │                 │   │
│  │  │ - connections:    │  │ - channel_subs:   │                 │   │
│  │  │   dict[str,       │  │   dict[str,       │                 │   │
│  │  │     Connection]   │  │     set[str]]     │                 │   │
│  │  │ - user_index:     │  │ - conn_channels:  │                 │   │
│  │  │   dict[str,       │  │   dict[str,       │                 │   │
│  │  │     set[str]]     │  │     set[str]]     │                 │   │
│  │  └──────────────────┘  └──────────────────┘                 │   │
│  │                                                              │   │
│  │  broadcast_to_channel(channel, message) ←── PubSubSubscriber │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                           ▲                                        │
│  ┌────────────────────────┤                                        │
│  │                        │                                        │
│  │  PubSubSubscriber      │  (ws/subscribers.py — 기존 구현)        │
│  │  Redis listen() loop   │                                        │
│  │  → _dispatch()         │                                        │
│  │  → hub.broadcast_to_channel()                                   │
│  └────────────────────────┘                                        │
│                           ▲                                        │
│  ┌────────────────────────┘                                        │
│  │  Redis Pub/Sub                                                  │
│  │  ┌─────────────────────────────────────────────┐               │
│  │  │ ch:ticker:{exchange}:{market}                │               │
│  │  │ ch:orderbook:{exchange}:{market}             │               │
│  │  │ ch:trades:{exchange}:{market}                │               │
│  │  │ ch:my_orders:{user_id}                       │               │
│  │  │ ch:ai_signal:{user_id}                       │               │
│  │  │ ch:notification:{user_id}                    │               │
│  │  │ ch:price_alert:{user_id}                     │               │
│  │  │ ch:system                                    │               │
│  │  └──────────────────────▲──────────────────────┘               │
│  └─────────────────────────┤                                       │
│                            │ RedisPublisher.publish_*()             │
│  ┌─────────────────────────┤                                       │
│  │  ExchangeStreamBridge (ws/bridge.py)                            │
│  │  - 거래소별 ExchangeStreamProvider.subscribe_*()                 │
│  │  - callback → RedisPublisher.publish_*()                        │
│  └─────────────────────────┘                                       │
│                            ▲                                        │
│  ┌─────────────────────────┤                                       │
│  │  Exchange Stream Providers                                      │
│  │  ┌──────────┐  ┌──────────┐                                    │
│  │  │  Upbit   │  │ CoinOne  │  ... (향후 확장)                    │
│  │  │  WS      │  │  WS      │                                    │
│  │  └──────────┘  └──────────┘                                    │
│  └─────────────────────────┘                                       │
└────────────────────────────────────────────────────────────────────┘
```

### 2.2 핵심 컴포넌트 요약

| 컴포넌트 | 위치 | 역할 |
|---------|------|------|
| **WS Endpoint** | `api/v1/ws.py` | JWT 인증, WebSocket accept, 메시지 수신 루프 |
| **WSHub** | `ws/hub.py` | 연결 관리 + 채널 구독 관리 + 브로드캐스트 |
| **MessageRouter** | `ws/router.py` | 수신 메시지 파싱 → action별 핸들러 디스패치 |
| **PubSubSubscriber** | `ws/subscribers.py` | Redis Pub/Sub → WSHub 브리지 (기존 구현) |
| **ExchangeStreamBridge** | `ws/bridge.py` | 거래소 WS → Redis Pub/Sub 브리지 |
| **RedisPublisher** | `core/pubsub.py` | 채널별 Redis publish (기존 구현) |

---

## 3. 데이터 흐름

### 3.1 실시간 시세 (Exchange → Client)

```
Exchange WS Server
    │
    │ (websockets, 거래소별 프로토콜)
    ▼
ExchangeStreamProvider (providers/upbit/stream.py 등)
    │
    │ callback(Ticker/OrderBook)
    ▼
ExchangeStreamBridge (ws/bridge.py)
    │
    │ RedisPublisher.publish_ticker(exchange, market, data)
    ▼
Redis Pub/Sub  ──  ch:ticker:upbit:KRW-BTC
    │
    │ PubSubSubscriber.listen() → _dispatch()
    ▼
WSHub.broadcast_to_channel("ch:ticker:upbit:KRW-BTC", message)
    │
    │ channel_subs["ch:ticker:upbit:KRW-BTC"] → {conn_id_1, conn_id_2, ...}
    │ 각 connection에 websocket.send_json()
    ▼
Flutter Client (N개 동시 수신)
```

### 3.2 클라이언트 구독 요청 흐름

```
Flutter Client
    │
    │ send: {"action":"subscribe","channel":"ticker","exchange":"upbit","market":"BTC/KRW"}
    ▼
WS Endpoint (메시지 수신 루프)
    │
    │ MessageRouter.route(message)
    ▼
SubscribeHandler
    │
    ├─ 1. 구독 한계 확인 (conn당 최대 50채널)
    ├─ 2. 채널명 조립: PubSubChannel.ticker("upbit","KRW-BTC")
    │     → SymbolMapper로 market 변환 (BTC/KRW → KRW-BTC)
    ├─ 3. WSHub.subscribe(conn_id, channel)
    ├─ 4. PubSubSubscriber.subscribe_ticker("upbit","KRW-BTC")
    │     → Redis SUBSCRIBE (이미 구독 중이면 무시)
    ├─ 5. ExchangeStreamBridge.ensure_stream("upbit","KRW-BTC","ticker")
    │     → 해당 거래소 WS 스트림이 없으면 시작
    └─ 6. 응답: {"action":"subscribed","channel":"ticker","exchange":"upbit","market":"BTC/KRW"}
```

### 3.3 사용자별 개인 채널 흐름

```
Flutter Client
    │
    │ send: {"action":"subscribe","channel":"my-orders"}
    ▼
SubscribeHandler
    │
    ├─ 1. user_id 기반 채널: PubSubChannel.my_orders(user_id)
    ├─ 2. WSHub.subscribe(conn_id, "ch:my_orders:{user_id}")
    ├─ 3. PubSubSubscriber.subscribe_user_channels(user_id)  (기존 메서드)
    └─ 4. 응답: {"action":"subscribed","channel":"my-orders"}

--- 주문 체결 시 ---

Trading Service (주문 처리)
    │
    │ RedisPublisher.publish_my_orders(user_id, order_data)
    ▼
Redis Pub/Sub → PubSubSubscriber → WSHub → 해당 user_id의 연결에만 전달
```

---

## 4. 컴포넌트 상세 설계

### 4.1 WSHub (ws/hub.py)

WSHub는 v1-12의 핵심 컴포넌트로, 연결 관리와 채널 구독을 모두 담당한다.

**설계 결정**: ConnectionManager와 ChannelManager를 별도 클래스로 분리하지 않고 **WSHub 단일 클래스**로 통합한다. 이유:
- 연결 추가/제거 시 채널 구독도 함께 정리해야 하므로 강한 결합
- 1,000 연결 규모에서 클래스 분리의 이점이 미미
- 기존 `PubSubSubscriber`가 이미 `WSHub.broadcast_to_channel()`을 호출하는 인터페이스 확정

```
WSHub
├── 상태 (인메모리)
│   ├── _connections: dict[str, Connection]          # conn_id → Connection 객체
│   ├── _user_connections: dict[str, set[str]]       # user_id → conn_id 집합
│   ├── _channel_subscribers: dict[str, set[str]]    # channel → conn_id 집합
│   └── _conn_channels: dict[str, set[str]]          # conn_id → channel 집합
│
├── 연결 관리
│   ├── connect(websocket, user_id, client_id) → conn_id
│   ├── disconnect(conn_id) → None
│   └── get_connection_count() → int
│
├── 구독 관리
│   ├── subscribe(conn_id, channel) → bool
│   ├── unsubscribe(conn_id, channel) → bool
│   ├── get_subscriptions(conn_id) → set[str]
│   └── get_channel_subscriber_count(channel) → int
│
└── 브로드캐스트
    ├── broadcast_to_channel(channel, message) → int   # 전송 성공 수 반환
    ├── send_to_user(user_id, message) → int           # 특정 사용자 전체 연결
    └── send_to_connection(conn_id, message) → bool    # 특정 연결
```

**Connection 데이터 클래스**:
```python
@dataclass
class Connection:
    conn_id: str               # UUID4
    websocket: WebSocket
    user_id: str
    client_id: str | None
    connected_at: datetime
    last_ping: datetime
    subscriptions: set[str]    # 구독 중인 채널 집합
```

**동시성 보호**: asyncio.Lock은 사용하지 않는다.
- asyncio는 단일 스레드 이벤트 루프이므로, `await` 없는 dict/set 조작은 원자적
- `broadcast_to_channel()`의 `send_json()`만 `await`이지만, 반복 중 구독 목록 변경은 `set.copy()`로 방어
- Lock을 걸면 1,000 연결 브로드캐스트 시 불필요한 경합 발생

### 4.2 ExchangeStreamBridge (ws/bridge.py)

거래소 WebSocket 스트림을 관리하고 수신 데이터를 Redis Pub/Sub로 발행하는 브리지.

**핵심 역할**:
- 구독 요청 집계: 같은 거래소+마켓에 대해 중복 스트림 방지 (참조 카운팅)
- 거래소 Provider의 `subscribe_ticker()`/`subscribe_orderbook()` 콜백 등록
- 콜백에서 `RedisPublisher.publish_*()`로 Redis에 발행

```
ExchangeStreamBridge
├── _streams: dict[str, StreamState]   # "upbit:ticker:KRW-BTC" → StreamState
│
├── ensure_stream(exchange, market, channel_type)
│   → 참조 카운트 증가, 신규면 Provider.subscribe_*() + asyncio.Task 시작
│
├── release_stream(exchange, market, channel_type)
│   → 참조 카운트 감소, 0이면 Provider.unsubscribe() + Task 취소
│
└── close_all() → 전체 스트림 정리 (lifespan shutdown)
```

**StreamState**:
```python
@dataclass
class StreamState:
    exchange: str
    market: str
    channel_type: str          # "ticker" | "orderbook" | "trades"
    ref_count: int = 0
    task: asyncio.Task | None = None
```

**참조 카운팅**: 클라이언트 1,000개가 같은 `upbit:BTC/KRW` ticker를 구독해도 거래소 WS 연결은 1개만 유지. 마지막 구독자가 해제하면 스트림 종료.

### 4.3 WS Endpoint (api/v1/ws.py)

```python
# 개략적 흐름 (의사코드)
@router.websocket("/ws/v1")
async def websocket_endpoint(
    websocket: WebSocket,
    token: str = Query(...),
):
    # 1. JWT 검증
    user = await authenticate_ws(token)
    if not user:
        await websocket.close(code=4001, reason="Unauthorized")
        return

    # 2. 연결 수락 + Hub 등록
    await websocket.accept()
    conn_id = await hub.connect(websocket, str(user.id), client_id)

    try:
        # 3. 연결 성공 메시지
        await websocket.send_json({"action": "connected", "conn_id": conn_id})

        # 4. 메시지 수신 루프
        async for raw in websocket.iter_json():
            await message_router.route(conn_id, raw)

    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("WS error conn_id=%s", conn_id)
    finally:
        # 5. 정리: Hub 연결 해제 + 구독 해제 + 스트림 참조 감소
        await hub.disconnect(conn_id)
```

**JWT 인증 — WS 전용 함수**:
- REST의 `get_current_user()`는 `Depends()`기반이라 WS에서 직접 사용 불가
- `authenticate_ws(token: str) → User | None` 전용 함수를 `ws/auth.py`에 작성
- 내부 로직은 `decode_access_token()` + `UserRepository.get_by_id()` 동일
- DB 세션은 `async_session_factory()`에서 직접 획득 (FastAPI DI 밖)

### 4.4 MessageRouter (ws/router.py)

수신 메시지의 `action` 필드로 핸들러를 디스패치한다.

```
지원 action:
├── subscribe    → SubscribeHandler
├── unsubscribe  → UnsubscribeHandler
├── ping         → PongHandler (클라이언트 heartbeat)
└── (미지원)     → ErrorResponse(UNKNOWN_ACTION)
```

---

## 5. 동시성 모델

### 5.1 asyncio 기반 아키텍처

```
uvicorn (1 프로세스, 1 이벤트 루프)
│
├── WS Endpoint Task × N (최대 1,000)
│   각 클라이언트 연결마다 1개 코루틴
│   websocket.iter_json()에서 대기 (I/O bound)
│
├── PubSubSubscriber.listen() Task × 1
│   Redis SUBSCRIBE → async for 루프
│   메시지 수신 → hub.broadcast_to_channel()
│
├── ExchangeStreamBridge Task × M (활성 스트림 수)
│   거래소 WS 연결마다 1개 코루틴
│   수신 → RedisPublisher.publish_*()
│
└── Heartbeat Task × 1
    30초 간격으로 모든 연결의 last_ping 확인
    타임아웃(60초) 연결 강제 종료
```

### 5.2 메모리 모델

1,000 연결 기준 예상 메모리:
- Connection 객체: ~1KB × 1,000 = ~1MB
- 채널 구독 인덱스: ~50 채널/연결 × 1,000 = ~2MB (set 오버헤드 포함)
- WebSocket 버퍼: ~16KB × 1,000 = ~16MB (uvicorn 기본)
- **총 예상**: ~20MB (서버 메모리의 극히 일부)

### 5.3 브로드캐스트 최적화

```python
async def broadcast_to_channel(self, channel: str, message: dict) -> int:
    """채널의 모든 구독자에게 전송. 실패한 연결은 건너뛴다."""
    subscriber_ids = self._channel_subscribers.get(channel)
    if not subscriber_ids:
        return 0

    # JSON 직렬화 1회 (N번 반복 아님)
    payload = json.dumps(message, ensure_ascii=False)

    # asyncio.gather로 병렬 전송
    tasks = []
    for conn_id in subscriber_ids.copy():  # copy()로 반복 중 변경 방어
        conn = self._connections.get(conn_id)
        if conn:
            tasks.append(self._safe_send(conn, payload))

    results = await asyncio.gather(*tasks, return_exceptions=True)
    return sum(1 for r in results if r is True)
```

**최적화 포인트**:
1. **JSON 직렬화 1회**: `json.dumps()` 한 번 → `send_text(payload)` (send_json이 아닌 send_text로 재직렬화 방지)
2. **asyncio.gather 병렬 전송**: 1,000개 연결에 순차 전송하면 지연 누적, gather로 I/O 대기 병렬화
3. **실패 연결 정리**: `_safe_send()`에서 전송 실패 시 해당 연결 disconnect 예약 (루프 안에서 직접 제거하지 않음)

### 5.4 연결 한계 관리

| 제한 | 값 | 근거 |
|------|-----|------|
| 최대 동시 연결 | 1,000 | 요구사항, uvicorn 단일 프로세스 기준 |
| 사용자당 최대 연결 | 5 | 모바일+데스크톱+웹+여유 |
| 연결당 최대 구독 | 50 | 과도한 채널 구독 방지 |
| Heartbeat 간격 | 30초 | 클라이언트 ping 요구 주기 |
| Heartbeat 타임아웃 | 60초 | 2회 연속 실패 시 죽은 연결 제거 |

설정 가능하도록 `config.py`에 추가:
```python
# WebSocket Hub
WS_MAX_CONNECTIONS: int = 1000
WS_MAX_CONNECTIONS_PER_USER: int = 5
WS_MAX_SUBSCRIPTIONS_PER_CONN: int = 50
WS_HEARTBEAT_INTERVAL: int = 30       # 초
WS_HEARTBEAT_TIMEOUT: int = 60        # 초
```

---

## 6. 에러 처리 전략

### 6.1 WS 에러 분류

| 에러 유형 | 원인 | WS Close Code | 처리 |
|-----------|------|---------------|------|
| 인증 실패 | JWT 없음/만료/변조 | 4001 | 즉시 close, 재연결 시 새 토큰 필요 |
| 인증 만료 | Access Token 만료 (30분) | 4001 | close, 클라이언트가 refresh 후 재연결 |
| 연결 한계 초과 | 서버 1000개/사용자 5개 | 4003 | 즉시 close |
| 구독 한계 초과 | 연결당 50채널 | — | error 메시지 전송 (연결 유지) |
| 잘못된 메시지 | JSON 파싱 실패/미지원 action | — | error 메시지 전송 (연결 유지) |
| 거래소 끊김 | ExchangeStreamProvider 연결 실패 | — | 시스템 메시지 전송, 자동 재연결 |
| 서버 내부 오류 | 예상치 못한 예외 | 1011 | close, 클라이언트 자동 재연결 |

### 6.2 WS Close Code 정의

```python
class WSCloseCode:
    UNAUTHORIZED = 4001          # JWT 인증 실패/만료
    FORBIDDEN = 4003             # 연결 한계 초과
    INTERNAL_ERROR = 1011        # 서버 내부 오류
    GOING_AWAY = 1001            # 서버 셧다운
```

표준 1000번대 + 커스텀 4000번대 (RFC 6455 §7.4.2 허용 범위: 4000-4999).

### 6.3 에러 메시지 형식

연결을 끊지 않는 에러는 JSON 메시지로 전송:
```json
{
  "action": "error",
  "code": "SUBSCRIPTION_LIMIT_EXCEEDED",
  "message": "Maximum 50 subscriptions per connection",
  "timestamp": "2026-03-14T12:00:00.000Z"
}
```

### 6.4 거래소 스트림 장애 처리

```
거래소 WS 끊김 감지
    │
    ├─ ExchangeStreamBridge: 자동 재연결 (Exponential Backoff, 최대 5회)
    │   → 재연결 성공: 기존 구독 복구, 정상 운영
    │   → 재연결 실패: 스트림 상태를 "disconnected"로 전환
    │
    ├─ RedisPublisher.publish_system(): 거래소 상태 변경 메시지 발행
    │   → {"type":"exchange_status","data":{"exchange":"upbit","status":"disconnected"}}
    │
    └─ 클라이언트: ch:system 구독으로 거래소 상태 변경 수신
        → UI에 "업비트 연결 끊김" 표시
        → 자동으로 재연결 시도하지 않음 (서버가 관리)
```

### 6.5 WS 에러 코드 (메시지용)

```python
class WSErrors:
    """WS 에러 팩토리 — AppError와 별개, JSON 메시지로 전송"""

    @staticmethod
    def unknown_action(action: str) -> dict:
        return {"action": "error", "code": "UNKNOWN_ACTION", "message": f"Unknown action: {action}"}

    @staticmethod
    def subscription_limit() -> dict:
        return {"action": "error", "code": "SUBSCRIPTION_LIMIT_EXCEEDED", "message": "Maximum 50 subscriptions per connection"}

    @staticmethod
    def invalid_message(detail: str) -> dict:
        return {"action": "error", "code": "INVALID_MESSAGE", "message": detail}

    @staticmethod
    def invalid_channel(channel: str) -> dict:
        return {"action": "error", "code": "INVALID_CHANNEL", "message": f"Unknown channel: {channel}"}

    @staticmethod
    def exchange_unavailable(exchange: str) -> dict:
        return {"action": "error", "code": "EXCHANGE_UNAVAILABLE", "message": f"Exchange stream unavailable: {exchange}"}
```

---

## 7. 성능 요구사항 및 최적화 전략

### 7.1 성능 목표

| 지표 | 목표 | 비고 |
|------|------|------|
| 동시 연결 | 1,000 | uvicorn 단일 프로세스 |
| 브로드캐스트 지연 | < 50ms | Redis Pub/Sub 수신 → 클라이언트 전송 |
| 메시지 처리량 | 10,000 msg/s | 1,000 연결 × 10 채널 × 1 msg/s |
| 메모리 사용 | < 100MB | WS 허브 전체 |
| 연결 수립 시간 | < 200ms | JWT 검증 + DB 조회 포함 |

### 7.2 최적화 전략

1. **JSON 직렬화 캐싱**: 같은 메시지를 N개 연결에 전송 시 1회만 직렬화
2. **asyncio.gather 병렬 전송**: 순차 전송 대신 병렬 I/O
3. **Redis Pub/Sub 전용 풀**: 블로킹 listen()이 일반 Redis 풀을 점유하지 않도록 분리 (기존 구현)
4. **참조 카운팅 스트림**: 거래소 WS 연결 최소화 (같은 마켓은 1개 연결 공유)
5. **죽은 연결 정리**: Heartbeat 기반 타임아웃으로 리소스 누수 방지
6. **구독 한계**: 연결당 50채널로 메모리/CPU 상한 제어

### 7.3 확장 전략 (향후)

현재는 단일 uvicorn 프로세스로 1,000 연결을 처리. 확장 필요 시:

```
현재: 단일 프로세스
uvicorn → WSHub (인메모리) → 1,000 연결

향후: 다중 프로세스 (필요 시)
Nginx (sticky session) → uvicorn ×N → WSHub ×N (각 인메모리)
                          └── Redis Pub/Sub (공유)
```

Redis Pub/Sub가 이미 프로세스 간 메시지 브로커 역할을 하므로, 다중 프로세스 확장 시에도 구조 변경 최소화. 단, `WSHub`의 연결 목록은 프로세스 로컬이므로 채널 구독 집계는 프로세스별 독립.

---

## 8. Lifespan 통합

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # ... 기존 초기화 ...

    # WSHub 싱글턴 초기화
    from app.ws.hub import WSHub
    ws_hub = WSHub()

    # PubSubSubscriber 시작 (기존 구현 활용)
    from app.ws.subscribers import PubSubSubscriber
    pubsub_redis = get_pubsub_redis()
    subscriber = PubSubSubscriber(pubsub_redis, ws_hub)

    # ExchangeStreamBridge 초기화
    from app.ws.bridge import ExchangeStreamBridge
    publisher = RedisPublisher(get_redis())
    bridge = ExchangeStreamBridge(factory, publisher)

    # 시스템 채널 구독 (항상 활성)
    await subscriber.subscribe_ticker("system", "")  # ch:system은 별도 처리 필요
    listen_task = asyncio.create_task(subscriber.listen())

    # Heartbeat 태스크 시작
    heartbeat_task = asyncio.create_task(ws_hub.heartbeat_loop())

    # 앱 상태에 저장 (DI 대체)
    app.state.ws_hub = ws_hub
    app.state.ws_subscriber = subscriber
    app.state.ws_bridge = bridge

    yield

    # Shutdown
    heartbeat_task.cancel()
    listen_task.cancel()
    await bridge.close_all()
    await subscriber.close()

    # ... 기존 정리 ...
```

**DI 전략**: WSHub, ExchangeStreamBridge는 lifespan에서 생성하여 `app.state`에 저장. WS 엔드포인트에서 `request.app.state.ws_hub`로 접근. FastAPI의 `Depends()`는 HTTP 전용이므로 WS에서는 직접 참조.

---

## 9. 서브태스크별 구현 범위

| ST | 이름 | 담당 | 구현 대상 |
|----|------|------|----------|
| ST1 | WebSocket 연결 관리자 | python-backend-expert | `ws/hub.py` — WSHub 클래스 (연결 관리 부분) |
| ST2 | 채널 구독 관리 시스템 | python-backend-expert | `ws/hub.py` — WSHub 클래스 (구독 관리 부분) |
| ST3 | WS 엔드포인트 및 JWT 인증 | python-backend-expert | `api/v1/ws.py`, `ws/auth.py` |
| ST4 | 메시지 스키마 및 검증 | code-architect | `schemas/ws.py` — Pydantic 모델 |
| ST5 | 구독 메시지 핸들러 | python-backend-expert | `ws/router.py`, `ws/handlers.py` |
| ST6 | Redis Pub/Sub 통합 | python-backend-expert | `ws/bridge.py` — ExchangeStreamBridge |
| ST7 | 연결 상태 메시지 시스템 | python-backend-expert | heartbeat, exchange status 메시지 |
| ST8 | 에러 처리 및 재연결 로직 | python-backend-expert | `ws/errors.py`, 에러 핸들링 전반 |
| ST9 | 성능 최적화 및 부하 테스트 | e2e-test-expert | 부하 테스트 스크립트, 메트릭 수집 |
| ST10 | 통합 테스트 및 문서화 | code-review-expert | 통합 테스트, 코드 리뷰 |

---

## 10. 파일 구조 및 모듈 의존성

### 10.1 신규 생성 파일

| 파일 경로 | 역할 | 담당 ST |
|----------|------|---------|
| `server/app/ws/hub.py` | WSHub 클래스 (연결 + 구독 + 브로드캐스트) | ST1, ST2 |
| `server/app/ws/bridge.py` | ExchangeStreamBridge (거래소 WS → Redis) | ST6 |
| `server/app/ws/router.py` | MessageRouter (action → 핸들러 디스패치) | ST5 |
| `server/app/ws/handlers.py` | SubscribeHandler, UnsubscribeHandler, PingHandler | ST5 |
| `server/app/ws/auth.py` | `authenticate_ws(token)` WS 전용 인증 함수 | ST3 |
| `server/app/ws/errors.py` | WSErrors 팩토리, WSCloseCode 상수 | ST8 |
| `server/app/api/v1/ws.py` | WebSocket 엔드포인트 (`/ws/v1`) | ST3 |
| `server/app/schemas/ws.py` | WS 메시지 Pydantic 스키마 | ST4 |

### 10.2 기존 파일 변경 사항

| 파일 경로 | 변경 내용 |
|----------|----------|
| `server/app/main.py` | lifespan에 WSHub, PubSubSubscriber, ExchangeStreamBridge, Heartbeat 태스크 초기화 추가 (§8 참조) |
| `server/app/core/config.py` | WS 설정 5개 추가: `WS_MAX_CONNECTIONS`, `WS_MAX_CONNECTIONS_PER_USER`, `WS_MAX_SUBSCRIPTIONS_PER_CONN`, `WS_HEARTBEAT_INTERVAL`, `WS_HEARTBEAT_TIMEOUT` (§5.4 참조) |
| `server/app/api/v1/__init__.py` | ws 라우터 등록 추가 |
| `server/app/ws/__init__.py` | public API 노출 (`WSHub`, `PubSubSubscriber`) |

> **변경 없음**: `ws/subscribers.py`, `core/pubsub.py`, `core/redis_keys.py` — 기존 구현 그대로 활용.

### 10.3 모듈 의존성 다이어그램

```
[외부]
  pydantic, fastapi, redis.asyncio, jose

[schemas/ws.py]              ← pydantic only (내부 의존 없음)

[ws/errors.py]               ← 내부 의존 없음

[ws/auth.py]
  └─ core/security.py        (decode_access_token)
  └─ core/database.py        (async_session_factory)
  └─ repositories/user_repository.py

[ws/hub.py]
  └─ schemas/ws.py           (WSConnectedMessage 등 outbound 타입)
  └─ ws/errors.py            (WSCloseCode)

[ws/bridge.py]
  └─ core/pubsub.py          (RedisPublisher)
  └─ core/redis_keys.py      (PubSubChannel)
  └─ providers/factory.py    (ExchangeProviderFactory — ABC 기반)

[ws/handlers.py]
  └─ ws/hub.py               (WSHub.subscribe/unsubscribe)
  └─ ws/bridge.py            (ExchangeStreamBridge.ensure_stream/release_stream)
  └─ ws/errors.py            (WSErrors 팩토리)
  └─ schemas/ws.py           (WSSubscribeRequest, WSUnsubscribeRequest)
  └─ core/redis_keys.py      (PubSubChannel — 채널명 조립)

[ws/router.py]
  └─ ws/handlers.py
  └─ ws/errors.py            (WSErrors.unknown_action, invalid_message)
  └─ schemas/ws.py           (WSInboundMessage 판별 유니온 파싱)

[ws/subscribers.py]          ← 기존 구현
  └─ core/redis_keys.py
  └─ ws/hub.py               (TYPE_CHECKING 참조)

[api/v1/ws.py]
  └─ ws/hub.py               (app.state.ws_hub)
  └─ ws/auth.py              (authenticate_ws)
  └─ ws/router.py            (MessageRouter)

[main.py lifespan]
  └─ ws/hub.py
  └─ ws/bridge.py
  └─ ws/subscribers.py
```

**의존 방향 원칙**:
- `api/v1/ws.py` → `ws/*` → `schemas/ws.py` / `core/*` (단방향)
- `ws/hub.py`는 `ws/bridge.py`에 의존하지 않음 — bridge는 handlers에서만 접근
- `ws/subscribers.py`의 `WSHub` 참조는 `TYPE_CHECKING`으로 순환 방지 (기존 유지)

### 10.4 `ws/__init__.py` public API

```python
"""WebSocket 모듈 공개 인터페이스."""
from app.ws.hub import WSHub
from app.ws.subscribers import PubSubSubscriber

__all__ = ["WSHub", "PubSubSubscriber"]
```

---

## 11. WS 메시지 스키마 상세

### 11.1 설계 원칙

- **인바운드**: Pydantic 판별 유니온으로 파싱 + 검증 → 잘못된 메시지 즉시 에러 응답
- **아웃바운드 제어 메시지**: Pydantic 모델 `.model_dump()` → `send_json()`
- **아웃바운드 데이터 메시지**: Redis 엔벨로프(pre-serialized JSON string) → `send_text()` (재직렬화 방지, §5.3 최적화)
- **action vs type 구분**: 제어 메시지는 `action` 필드, Redis 데이터 브로드캐스트는 `type` 필드 사용

### 11.2 `schemas/ws.py` Pydantic 모델 정의

```python
"""WebSocket 메시지 스키마 — 클라이언트↔서버 메시지 타입 정의."""
from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, model_validator


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


# ── 채널 타입 열거형 ──────────────────────────────────────────────────────────

class WSChannel(StrEnum):
    """구독 가능한 채널 타입."""

    TICKER = "ticker"
    ORDERBOOK = "orderbook"
    TRADES = "trades"
    MY_ORDERS = "my-orders"
    AI_SIGNAL = "ai-signal"
    NOTIFICATION = "notification"
    PRICE_ALERT = "price-alert"
    SYSTEM = "system"


# exchange + market 필수인 공개 시장 채널
MARKET_CHANNELS: frozenset[WSChannel] = frozenset({
    WSChannel.TICKER,
    WSChannel.ORDERBOOK,
    WSChannel.TRADES,
})

# user_id 기반 개인 채널 (exchange/market 불필요)
PERSONAL_CHANNELS: frozenset[WSChannel] = frozenset({
    WSChannel.MY_ORDERS,
    WSChannel.AI_SIGNAL,
    WSChannel.NOTIFICATION,
    WSChannel.PRICE_ALERT,
})


# ── Client → Server ───────────────────────────────────────────────────────────

class WSSubscribeRequest(BaseModel):
    """채널 구독 요청.

    Examples:
        시장 채널: {"action":"subscribe","channel":"ticker","exchange":"upbit","market":"KRW-BTC"}
        개인 채널: {"action":"subscribe","channel":"my-orders"}
    """

    action: Literal["subscribe"]
    channel: WSChannel
    exchange: str | None = Field(default=None, min_length=1, max_length=20)
    market: str | None = Field(default=None, min_length=1, max_length=20)

    @model_validator(mode="after")
    def _require_market_params(self) -> "WSSubscribeRequest":
        if self.channel in MARKET_CHANNELS and (not self.exchange or not self.market):
            raise ValueError(
                f"channel '{self.channel}' requires 'exchange' and 'market'"
            )
        return self


class WSUnsubscribeRequest(BaseModel):
    """채널 구독 해제 요청.

    Examples:
        {"action":"unsubscribe","channel":"ticker","exchange":"upbit","market":"KRW-BTC"}
        {"action":"unsubscribe","channel":"my-orders"}
    """

    action: Literal["unsubscribe"]
    channel: WSChannel
    exchange: str | None = Field(default=None, min_length=1, max_length=20)
    market: str | None = Field(default=None, min_length=1, max_length=20)

    @model_validator(mode="after")
    def _require_market_params(self) -> "WSUnsubscribeRequest":
        if self.channel in MARKET_CHANNELS and (not self.exchange or not self.market):
            raise ValueError(
                f"channel '{self.channel}' requires 'exchange' and 'market'"
            )
        return self


class WSPingRequest(BaseModel):
    """클라이언트 Heartbeat 요청.

    Examples:
        {"action":"ping"}
    """

    action: Literal["ping"]


# 인바운드 메시지 — Literal["action"] 기반 판별 유니온
WSInboundMessage = Annotated[
    WSSubscribeRequest | WSUnsubscribeRequest | WSPingRequest,
    Field(discriminator="action"),
]
```

### 11.3 Server → Client 제어 메시지

```python
# ── Server → Client (제어 메시지) ─────────────────────────────────────────────

class WSConnectedMessage(BaseModel):
    """연결 수락 직후 전송 — 클라이언트가 conn_id를 로깅/디버깅에 활용."""

    action: Literal["connected"] = "connected"
    conn_id: str
    timestamp: str = Field(default_factory=_now_iso)


class WSSubscribedMessage(BaseModel):
    """구독 성공 응답."""

    action: Literal["subscribed"] = "subscribed"
    channel: str          # WSChannel 값 그대로 ("ticker", "my-orders" 등)
    exchange: str | None = None
    market: str | None = None
    timestamp: str = Field(default_factory=_now_iso)


class WSUnsubscribedMessage(BaseModel):
    """구독 해제 성공 응답."""

    action: Literal["unsubscribed"] = "unsubscribed"
    channel: str
    exchange: str | None = None
    market: str | None = None
    timestamp: str = Field(default_factory=_now_iso)


class WSPongMessage(BaseModel):
    """Heartbeat 응답 — last_ping 갱신과 함께 전송."""

    action: Literal["pong"] = "pong"
    timestamp: str = Field(default_factory=_now_iso)


class WSErrorMessage(BaseModel):
    """에러 메시지 — 연결 유지, 해당 요청만 실패 처리."""

    action: Literal["error"] = "error"
    code: str       # WSErrors 코드 문자열 (§6.5 참조)
    message: str
    timestamp: str = Field(default_factory=_now_iso)


class WSSystemMessage(BaseModel):
    """시스템/거래소 상태 변경 알림 — system 채널 구독자에게 브로드캐스트."""

    action: Literal["system"] = "system"
    type: str           # "exchange_status" | "server_maintenance" | ...
    data: dict[str, Any]
    timestamp: str = Field(default_factory=_now_iso)
```

### 11.4 Server → Client 데이터 브로드캐스트 형식

데이터 메시지(ticker/orderbook/trades/my-orders 등)는 Redis 엔벨로프를 그대로 클라이언트에 전달한다. Pydantic 모델 정의 없음 — `send_text(raw_json_string)` 방식으로 재직렬화 없이 전송.

```json
// ticker 브로드캐스트 예시
{
  "type": "ticker",
  "channel": "ch:ticker:upbit:KRW-BTC",
  "timestamp": "2026-03-14T12:00:00.000Z",
  "data": {
    "symbol": "KRW-BTC",
    "price": 45000000,
    "change_24h": 0.023,
    "volume_24h": 1234.56
  }
}

// orderbook 브로드캐스트 예시
{
  "type": "orderbook",
  "channel": "ch:orderbook:upbit:KRW-BTC",
  "timestamp": "2026-03-14T12:00:00.000Z",
  "data": {
    "symbol": "KRW-BTC",
    "asks": [{"price": 45100000, "quantity": 0.5}],
    "bids": [{"price": 44900000, "quantity": 1.2}]
  }
}

// my-orders 브로드캐스트 예시
{
  "type": "my_orders",
  "channel": "ch:my_orders:{user_id}",
  "timestamp": "2026-03-14T12:00:00.000Z",
  "data": {
    "order_id": "...",
    "status": "filled",
    "symbol": "KRW-BTC",
    "side": "buy",
    "quantity": 0.001,
    "price": 45000000
  }
}
```

> **참조**: 데이터 필드 상세 스펙은 `shared/ws-spec/events.yaml` 기준.

### 11.5 메시지 파싱 흐름 (`ws/router.py` 내부)

```python
from pydantic import TypeAdapter, ValidationError
from app.schemas.ws import WSInboundMessage

_adapter = TypeAdapter(WSInboundMessage)   # 모듈 수준 1회 생성

async def route(self, conn_id: str, raw: dict) -> None:
    try:
        msg = _adapter.validate_python(raw)
    except ValidationError as exc:
        await self._send_error(conn_id, WSErrors.invalid_message(str(exc)))
        return
    except Exception:
        await self._send_error(conn_id, WSErrors.invalid_message("Malformed JSON"))
        return

    match msg.action:
        case "subscribe":   await self._subscribe_handler.handle(conn_id, msg)
        case "unsubscribe": await self._unsubscribe_handler.handle(conn_id, msg)
        case "ping":        await self._ping_handler.handle(conn_id, msg)
        case _:             await self._send_error(conn_id, WSErrors.unknown_action(msg.action))
```

---

## 12. 코드 컨벤션 및 패턴

### 12.1 네이밍 규칙

| 대상 | 규칙 | 예시 |
|------|------|------|
| WS 모듈 파일 | `snake_case.py`, `ws/` 하위 | `ws/hub.py`, `ws/bridge.py` |
| action 필드값 | 소문자 단어 / kebab-case | `subscribe`, `my-orders` |
| WS 에러 코드 | `SCREAMING_SNAKE_CASE` | `SUBSCRIPTION_LIMIT_EXCEEDED` |
| Redis 채널명 | `ch:{type}:{exchange}:{market}` 또는 `ch:{type}:{user_id}` | `PubSubChannel.*()` 헬퍼 사용 |
| conn_id | UUID4 문자열 | `str(uuid.uuid4())` |
| WS Close Code | 4자리 정수 상수 | `WSCloseCode.UNAUTHORIZED = 4001` |
| 핸들러 클래스 | `{Action}Handler` | `SubscribeHandler`, `PingHandler` |

### 12.2 에러 처리 패턴 — HTTP vs WS 분리

```
HTTP REST 엔드포인트
  └─ raise AppError(...)        → middleware/error_handler.py → JSON HTTP 응답

WS 엔드포인트 — 두 가지 경우 구분:

  [연결 거부 (accept 전)]
    await websocket.close(code=WSCloseCode.UNAUTHORIZED, reason="Unauthorized")
    return  # WS 핸드셰이크 단계, 연결 맺지 않음

  [메시지 에러 (연결 유지)]
    await websocket.send_json(WSErrors.subscription_limit())
    # 연결 유지, 해당 요청만 실패

  [서버 내부 오류 (연결 종료)]
    logger.exception("WS error conn_id=%s", conn_id)
    await websocket.close(code=WSCloseCode.INTERNAL_ERROR)
    # finally 블록에서 hub.disconnect() 보장
```

**규칙**: WS 핸들러에서 절대 `raise AppError()` 사용 금지. 에러는 `send_json()` 또는 `close()`로만 전달.

### 12.3 로깅 패턴

```python
# 모듈 상단 (모든 ws/ 파일 동일)
logger = logging.getLogger(__name__)
# → 로그 네임: "app.ws.hub", "app.ws.bridge", "app.ws.router" 등

# 연결 이벤트 — INFO
logger.info("WS connected conn_id=%s user_id=%s", conn_id, user_id)
logger.info("WS disconnected conn_id=%s duration=%.1fs", conn_id, duration)

# 구독 이벤트 — DEBUG (운영 로그 과다 방지)
logger.debug("subscribe conn_id=%s channel=%s", conn_id, channel)

# 클라이언트 오류 — WARNING (서버 잘못 아님)
logger.warning("invalid WS message conn_id=%s action=%s", conn_id, raw.get("action"))

# 서버/거래소 오류 — ERROR + exception
logger.exception("WS broadcast failed channel=%s", channel)
logger.error("Exchange stream down exchange=%s market=%s", exchange, market)
```

### 12.4 `app.state` 접근 패턴

```python
# WS 엔드포인트에서 싱글턴 접근
from fastapi import WebSocket

@router.websocket("/ws/v1")
async def websocket_endpoint(websocket: WebSocket, token: str = Query(...)):
    hub: WSHub = websocket.app.state.ws_hub
    bridge: ExchangeStreamBridge = websocket.app.state.ws_bridge
    ...
```

`Depends()`는 HTTP 전용. WS 엔드포인트에서는 `websocket.app.state.*`로 직접 접근. 테스트 시 `app.state.*`에 Mock 주입으로 대체.

### 12.5 구현 우선순위 (서브태스크 의존성 그래프)

```
Phase 1 — 병렬 시작 (의존성 없음)
  ├─ ST4: schemas/ws.py          (code-architect — 즉시 구현)
  └─ ST1: ws/hub.py 연결 관리    (python-backend-expert)

Phase 2 — ST1 완료 후 병렬
  ├─ ST2: ws/hub.py 구독 관리    (ST1 필요)
  └─ ST6: ws/bridge.py           (ST1 필요, RedisPublisher + ExchangeProvider)

Phase 3 — ST2 + ST4 완료 후 순차
  ST3: api/v1/ws.py + ws/auth.py  (ST1, ST2, ST4 필요)
    └─ ST5: ws/router.py + ws/handlers.py  (ST3, ST4 필요)
         └─ ST7: heartbeat + system 메시지  (ST5 필요)
              └─ ST8: ws/errors.py 통합    (ST7 필요)

Phase 4 — 전체 구현 완료 후 병렬
  ├─ ST9: 부하 테스트  (e2e-test-expert)
  └─ ST10: 통합 테스트 + 문서화  (code-review-expert)
```

**의존성 요약**:

| ST | 선행 필요 |
|----|---------|
| ST1 | 없음 |
| ST2 | ST1 |
| ST3 | ST1, ST2, ST4 |
| ST4 | 없음 |
| ST5 | ST3, ST4 |
| ST6 | ST1 |
| ST7 | ST5, ST6 |
| ST8 | ST5, ST7 |
| ST9 | ST1~ST8 |
| ST10 | ST1~ST8 |

### 12.6 테스트 패턴

```python
# WS 통합 테스트 — starlette.testclient
from starlette.testclient import TestClient

def test_ws_subscribe_ticker(test_app, auth_token):
    with TestClient(test_app).websocket_connect(
        f"/ws/v1?token={auth_token}"
    ) as ws:
        # 연결 확인
        connected = ws.receive_json()
        assert connected["action"] == "connected"

        # 구독 요청
        ws.send_json({"action": "subscribe", "channel": "ticker",
                      "exchange": "upbit", "market": "KRW-BTC"})
        subscribed = ws.receive_json()
        assert subscribed["action"] == "subscribed"
        assert subscribed["channel"] == "ticker"

# Mock 주입 패턴 — app.state 교체
@pytest.fixture
def test_app(app):
    app.state.ws_hub = MockWSHub()
    app.state.ws_bridge = MockExchangeStreamBridge()
    return app
```

**테스트 원칙**:
- WS 통합 테스트는 실제 FastAPI 앱 사용 (MockWSHub로 거래소 연동만 격리)
- 인증 실패 케이스: close code 4001 수신 확인
- 구독 한계 케이스: error 메시지 수신 확인 (연결 유지 검증)

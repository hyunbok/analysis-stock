# v1-3 Redis 캐시 및 Pub/Sub 구성 - 설계서

## 1. 개요

Redis 7을 활용한 캐시, Pub/Sub, Rate Limiting 시스템을 구성한다. JWT refresh token 저장, 실시간 시세/AI 신호 브로드캐스트, 거래소 API Rate Limiting, 기술적 지표/장세 분석 결과 캐싱을 포함한다.

**의존성**: v1:1(프로젝트 인프라) 완료 — `redis.py`(클라이언트), `config.py`(REDIS_URL), `deps.py`(RedisClient), Docker Compose(Redis 7) 준비됨.

**현재 상태**: 구현 완료. `redis.py`(일반풀+Pub/Sub 전용풀 분리), `redis_keys.py`(키 상수/TTL/채널), `rate_limiter.py`+`token_bucket.lua`(Token Bucket), `pubsub.py`(Publisher), `subscribers.py`(Subscriber), `rate_limit.py`(미들웨어), 캐시 서비스 3종(`auth`/`market`/`ai`), 통합 테스트 3종(38케이스) 구현됨.

## 2. 시스템 아키텍처 — Redis 역할

```
┌─────────────────────────────────────────────────────────────────┐
│                      FastAPI Server                             │
│                                                                 │
│  ┌──────────┐  ┌──────────────┐  ┌────────────┐  ┌──────────┐ │
│  │ API      │  │ Rate Limiter │  │ Cache      │  │ WS Hub   │ │
│  │ Routes   │──│ Middleware   │  │ Service    │  │          │ │
│  └────┬─────┘  └──────┬───────┘  └─────┬──────┘  └────┬─────┘ │
│       │               │                │               │       │
│  ┌────▼───────────────▼────────────────▼───────────────▼─────┐ │
│  │                    Redis 7                                 │ │
│  │  ┌─────────┐  ┌──────────┐  ┌──────────┐  ┌───────────┐  │ │
│  │  │  Cache  │  │Rate Limit│  │ Pub/Sub  │  │  Auth     │  │ │
│  │  │(String/ │  │(String + │  │(Channels)│  │(Refresh   │  │ │
│  │  │ Hash)   │  │ Lua)     │  │          │  │ Tokens)   │  │ │
│  │  └─────────┘  └──────────┘  └──────────┘  └───────────┘  │ │
│  └────────────────────────────────────────────────────────────┘ │
│       │                                        │               │
│  ┌────▼─────┐                            ┌─────▼─────┐        │
│  │ Exchange │                            │ Celery    │        │
│  │ Provider │                            │ Worker    │        │
│  └──────────┘                            └───────────┘        │
└─────────────────────────────────────────────────────────────────┘
```

### Redis 4대 역할

| 역할 | 용도 | 데이터 특성 |
|------|------|-------------|
| **Cache** | 시세, 지표, 장세, AI 결정, 캔들, 뉴스 감성 | 단기 TTL (30s~30min), 손실 허용 |
| **Auth Store** | JWT refresh token | 중기 TTL (14일), AOF 영속화 필수 |
| **Pub/Sub** | 실시간 시세, AI 신호 브로드캐스트 | Fire-and-forget, 구독자 없으면 유실 |
| **Rate Limiter** | API/거래소 요청 제한 | Token Bucket (Lua 스크립트), 초~분 단위 |

## 3. Redis 키 패턴 및 TTL 정책

### 3-1. 키 카테고리별 상세표

#### 인증 (Auth)

| 키 패턴 | 파라미터 | TTL | Redis 타입 | 설명 |
|---------|----------|-----|-----------|------|
| `auth:refresh:{user_id}:{client_id}` | user_id(UUID), client_id(UUID) | 14일 | String | JWT refresh token 해시값 저장 |
| `auth:refresh_index:{user_id}` | user_id(UUID) | 14일 | Set | 사용자의 모든 활성 client_id 집합 (세션 관리용) |
| `auth:email_verify:{email}` | email | 10분 | String | 이메일 인증 코드 (6자리) |
| `auth:password_reset:{token}` | token(UUID) | 1시간 | String | 비밀번호 재설정 토큰 → user_id |

#### Rate Limiting

| 키 패턴 | 파라미터 | TTL | Redis 타입 | 설명 |
|---------|----------|-----|-----------|------|
| `rate:api:{ip}` | IP 주소 | 60초 | String | API 전역 Rate Limit (Token Bucket 상태) |
| `rate:api:{user_id}` | user_id(UUID) | 60초 | String | 인증 사용자 Rate Limit |
| `rate:exchange:{exchange}:{user_id}` | exchange(enum), user_id | 60초 | String | 거래소별 Rate Limit (Lua JSON) |
| `rate:login:{ip}` | IP 주소 | 15분 | String | 로그인 시도 횟수 (brute-force 방지) |

#### 실시간 시세 캐시

| 키 패턴 | 파라미터 | TTL | Redis 타입 | 설명 |
|---------|----------|-----|-----------|------|
| `ticker:{exchange}:{market}` | exchange, market(KRW-BTC 등) | 10초 | String(JSON) | 최신 시세 스냅샷 |
| `candles:{exchange}:{market}:{timeframe}:{count}` | exchange, market, timeframe(1m/5m/..), count | 30초 | String(JSON) | 캔들 데이터 캐시 |
| `orderbook:{exchange}:{market}` | exchange, market | 5초 | String(JSON) | 호가창 스냅샷 |

#### AI/분석 캐시

| 키 패턴 | 파라미터 | TTL | Redis 타입 | 설명 |
|---------|----------|-----|-----------|------|
| `indicators:{exchange}:{market}:{timeframe}` | exchange, market, timeframe | 60~600초 | String(JSON) | 기술적 지표 스냅샷 (14종) |
| `regime:{exchange}:{market}` | exchange, market | 300초 | String(JSON) | 장세 분석 결과 |
| `ai_decision:{user_id}:{market}:latest` | user_id, market | 300초 | String(JSON) | AI 최신 매매 결정 |
| `ai:news_sentiment:{coin}` | coin(BTC 등) | 30분 | String(JSON) | 뉴스 감성 분석 결과 |
| `ai:last_run:{user_id}:{coin}` | user_id, coin | 10분 | String(ISO) | 마지막 AI 분석 실행 시각 |

#### 알림

| 키 패턴 | 파라미터 | TTL | Redis 타입 | 설명 |
|---------|----------|-----|-----------|------|
| `notifications:unread_count:{user_id}` | user_id(UUID) | 1시간 | String(int) | 미읽 알림 수 (DB 조회 캐시) |

### 3-2. TTL 상수 정의

```python
# server/app/core/redis_keys.py

class RedisTTL:
    """Redis TTL 상수 (초 단위)"""
    # Auth
    REFRESH_TOKEN = 14 * 24 * 3600      # 14일
    EMAIL_VERIFY = 10 * 60              # 10분
    PASSWORD_RESET = 3600               # 1시간

    # Rate Limiting
    RATE_WINDOW = 60                    # 1분
    LOGIN_RATE = 15 * 60                # 15분

    # Market Data
    TICKER = 10                         # 10초
    CANDLES = 30                        # 30초
    ORDERBOOK = 5                       # 5초

    # AI/Analysis
    INDICATORS_SHORT = 60               # 1분 (1m 타임프레임)
    INDICATORS_LONG = 600               # 10분 (1h+ 타임프레임)
    REGIME = 300                        # 5분
    AI_DECISION = 300                   # 5분
    NEWS_SENTIMENT = 30 * 60            # 30분
    AI_LAST_RUN = 10 * 60              # 10분

    # Notifications
    UNREAD_COUNT = 3600                 # 1시간
```

### 3-3. 키 빌더 함수

```python
# server/app/core/redis_keys.py

class RedisKey:
    """Redis 키 생성 헬퍼 — 타입 안전 키 생성"""

    # Auth
    @staticmethod
    def refresh_token(user_id: str, client_id: str) -> str: ...

    @staticmethod
    def refresh_index(user_id: str) -> str: ...

    @staticmethod
    def email_verify(email: str) -> str: ...

    @staticmethod
    def password_reset(token: str) -> str: ...

    # Rate Limiting
    @staticmethod
    def rate_api_ip(ip: str) -> str: ...

    @staticmethod
    def rate_api_user(user_id: str) -> str: ...

    @staticmethod
    def rate_exchange(exchange: str, user_id: str) -> str: ...

    @staticmethod
    def rate_login(ip: str) -> str: ...

    # Market Data
    @staticmethod
    def ticker(exchange: str, market: str) -> str: ...

    @staticmethod
    def candles(exchange: str, market: str, timeframe: str, count: int) -> str: ...

    @staticmethod
    def orderbook(exchange: str, market: str) -> str: ...

    # AI/Analysis
    @staticmethod
    def indicators(exchange: str, market: str, timeframe: str) -> str: ...

    @staticmethod
    def regime(exchange: str, market: str) -> str: ...

    @staticmethod
    def ai_decision(user_id: str, market: str) -> str: ...

    @staticmethod
    def news_sentiment(coin: str) -> str: ...

    @staticmethod
    def ai_last_run(user_id: str, coin: str) -> str: ...

    # Notifications
    @staticmethod
    def unread_count(user_id: str) -> str: ...
```

## 4. Pub/Sub 채널 구조 및 메시지 포맷

### 4-1. WS 채널 ↔ Redis Pub/Sub 채널 매핑

> api-spec.md §5.2 WS 채널 기준

| WS 채널 (클라이언트) | Redis Pub/Sub 채널 | 구독 범위 | 발행자 |
|-----------------|-----------------|---------|--------|
| `ticker` | `ch:ticker:{exchange}:{market}` | 공개 (exchange+market 지정) | Exchange WS Adapter |
| `orderbook` | `ch:orderbook:{exchange}:{market}` | 공개 (exchange+market 지정) | Exchange WS Adapter |
| `trades` | `ch:trades:{exchange}:{market}` | 공개 (exchange+market 지정) | Exchange WS Adapter |
| `my-orders` | `ch:my_orders:{user_id}` | 개인 (JWT 인증 필수) | Order Service |
| `auto-trading` | `ch:ai_signal:{user_id}` | 개인 (JWT 인증 필수) | Celery AI Worker |
| (서버 푸시) | `ch:notification:{user_id}` | 개인 (JWT 인증 필수) | Service Layer |
| (서버 푸시) | `ch:price_alert:{user_id}` | 개인 (JWT 인증 필수) | Price Monitor |
| (서버 푸시) | `ch:system` | 전체 브로드캐스트 | Admin/System |

### 4-2. 채널 상세 목록

| 채널 패턴 | 파라미터 | 발행자 | 구독자 | 설명 |
|-----------|----------|--------|--------|------|
| `ch:ticker:{exchange}:{market}` | exchange, market | Exchange WS Adapter | WS Hub | 실시간 시세 |
| `ch:orderbook:{exchange}:{market}` | exchange, market | Exchange WS Adapter | WS Hub | 호가창 업데이트 |
| `ch:trades:{exchange}:{market}` | exchange, market | Exchange WS Adapter | WS Hub | 실시간 체결 내역 |
| `ch:my_orders:{user_id}` | user_id | Order Service | WS Hub | 사용자 주문 상태 변경 |
| `ch:ai_signal:{user_id}` | user_id | Celery AI Worker | WS Hub | AI 매매 신호 |
| `ch:notification:{user_id}` | user_id | Service Layer | WS Hub | 개인 알림 |
| `ch:price_alert:{user_id}` | user_id | Price Monitor | WS Hub | 가격 알림 트리거 |
| `ch:system` | (없음) | Admin/System | WS Hub(전체) | 시스템 공지 |

### 4-3. 메시지 포맷

모든 Pub/Sub 메시지는 공통 엔벨로프로 감싼다:

```json
{
  "type": "ticker",
  "channel": "ch:ticker:upbit:KRW-BTC",
  "timestamp": "2026-03-06T10:30:00.123Z",
  "data": { ... }
}
```

### 4-4. 채널별 메시지 스키마

#### 시세 메시지 (`ticker`)

```json
{
  "type": "ticker",
  "channel": "ch:ticker:upbit:KRW-BTC",
  "timestamp": "2026-03-06T10:30:00.123Z",
  "data": {
    "exchange": "upbit",
    "market": "KRW-BTC",
    "price": 95000000,
    "change_rate": 0.0235,
    "change_price": 2180000,
    "volume_24h": 1234.5678,
    "high_24h": 96000000,
    "low_24h": 93000000,
    "timestamp": "2026-03-06T10:30:00.123Z"
  }
}
```

#### 호가창 메시지 (`orderbook`)

```json
{
  "type": "orderbook",
  "channel": "ch:orderbook:upbit:KRW-BTC",
  "timestamp": "2026-03-06T10:30:00.123Z",
  "data": {
    "exchange": "upbit",
    "market": "KRW-BTC",
    "total_ask_size": "1.234",
    "total_bid_size": "5.678",
    "asks": [
      {"price": 95100000, "size": "0.123"},
      {"price": 95200000, "size": "0.456"}
    ],
    "bids": [
      {"price": 94900000, "size": "0.789"},
      {"price": 94800000, "size": "0.321"}
    ]
  }
}
```

#### 체결 메시지 (`trades`)

```json
{
  "type": "trades",
  "channel": "ch:trades:upbit:KRW-BTC",
  "timestamp": "2026-03-06T10:30:00.123Z",
  "data": {
    "exchange": "upbit",
    "market": "KRW-BTC",
    "price": 95000000,
    "volume": "0.001",
    "side": "bid",
    "change": "RISE",
    "change_price": 1000000,
    "sequential_id": 1234567890123456
  }
}
```

#### 내 주문 상태 메시지 (`my_orders`)

```json
{
  "type": "my_orders",
  "channel": "ch:my_orders:{user_id}",
  "timestamp": "2026-03-06T10:30:00.123Z",
  "data": {
    "order_id": "uuid",
    "exchange_order_id": "upbit-order-id",
    "exchange": "upbit",
    "market": "KRW-BTC",
    "order_type": "limit",
    "side": "buy",
    "price": 95000000,
    "quantity": "0.001",
    "executed_quantity": "0.001",
    "status": "filled",
    "is_ai_order": false
  }
}
```

> `status` 값: `pending` | `open` | `partially_filled` | `filled` | `cancelled` | `failed`

#### AI 신호 메시지 (`ai_signal`)

```json
{
  "type": "ai_signal",
  "channel": "ch:ai_signal:{user_id}",
  "timestamp": "2026-03-06T10:30:00Z",
  "data": {
    "user_id": "uuid",
    "market": "KRW-BTC",
    "exchange": "upbit",
    "action": "buy",
    "confidence": 0.85,
    "regime": "bullish",
    "strategy": "trend_following",
    "reason": "RSI 과매도 + MACD 골든크로스",
    "indicators_summary": {
      "rsi": 28.5,
      "macd_signal": "golden_cross"
    }
  }
}
```

#### 알림 메시지 (`notification`)

```json
{
  "type": "notification",
  "channel": "ch:notification:{user_id}",
  "timestamp": "2026-03-06T10:30:00Z",
  "data": {
    "notification_id": "mongo_object_id",
    "notification_type": "trade_executed",
    "title": "매매 체결",
    "body": "KRW-BTC 0.01 BTC 매수 완료",
    "unread_count": 5,
    "data": { "order_id": "uuid" }
  }
}
```

#### 가격 알림 메시지 (`price_alert`)

```json
{
  "type": "price_alert",
  "channel": "ch:price_alert:{user_id}",
  "timestamp": "2026-03-06T10:30:00Z",
  "data": {
    "alert_id": "uuid",
    "coin": "BTC",
    "market": "KRW-BTC",
    "condition": "above",
    "target_price": 95000000,
    "current_price": 95100000
  }
}
```

#### 시스템 메시지 (`system`)

```json
{
  "type": "system",
  "channel": "ch:system",
  "timestamp": "2026-03-06T10:30:00Z",
  "data": {
    "event": "maintenance",
    "message": "서버 점검 예정: 2026-03-07 02:00~04:00 KST",
    "severity": "info"
  }
}
```

## 5. Rate Limiting 설계

### 5-1. Token Bucket 알고리즘

Lua 스크립트 기반 원자적 Token Bucket 구현. Redis String에 JSON 상태 저장.

```
상태: { tokens: float, last_refill: float(timestamp) }
요청 시: refill → consume → allow/deny
```

### 5-2. Rate Limit 정책

| 대상 | 윈도우 | 한도 | 키 패턴 | 비고 |
|------|--------|------|---------|------|
| API 전역 (비인증) | 1분 | 60회 | `rate:api:{ip}` | IP 기반 |
| API 전역 (인증) | 1분 | 120회 | `rate:api:{user_id}` | 사용자 기반 |
| 로그인 시도 | 15분 | 5회 | `rate:login:{ip}` | brute-force 방지 |
| Upbit API | 1초/1분 | 10회/600회 | `rate:exchange:upbit:{user_id}` | 이중 버킷 |
| CoinOne API | 1초/1분 | 10회/300회 | `rate:exchange:coinone:{user_id}` | 이중 버킷 |
| Coinbase API | 1초/1분 | 10회/300회 | `rate:exchange:coinbase:{user_id}` | 이중 버킷 |
| Binance API | 1초/1분 | 20회/1200회 | `rate:exchange:binance:{user_id}` | 이중 버킷 |

### 5-3. Token Bucket Lua 스크립트

```lua
-- token_bucket.lua
-- KEYS[1]: rate limit key
-- ARGV[1]: max_tokens (bucket capacity)
-- ARGV[2]: refill_rate (tokens per second)
-- ARGV[3]: now (current timestamp as float)
-- ARGV[4]: tokens_to_consume (default 1)
-- ARGV[5]: ttl (key expiry in seconds)
-- Returns: {allowed(0/1), remaining_tokens, retry_after_ms}

local key = KEYS[1]
local max_tokens = tonumber(ARGV[1])
local refill_rate = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local consume = tonumber(ARGV[4])
local ttl = tonumber(ARGV[5])

local data = redis.call('GET', key)
local tokens, last_refill

if data then
    local t = cjson.decode(data)
    tokens = t.tokens
    last_refill = t.last_refill
else
    tokens = max_tokens
    last_refill = now
end

-- Refill
local elapsed = now - last_refill
local new_tokens = elapsed * refill_rate
tokens = math.min(max_tokens, tokens + new_tokens)
last_refill = now

-- Consume
if tokens >= consume then
    tokens = tokens - consume
    redis.call('SET', key, cjson.encode({tokens=tokens, last_refill=last_refill}), 'EX', ttl)
    return {1, math.floor(tokens * 1000) / 1000, 0}
else
    local wait = (consume - tokens) / refill_rate
    redis.call('SET', key, cjson.encode({tokens=tokens, last_refill=last_refill}), 'EX', ttl)
    return {0, math.floor(tokens * 1000) / 1000, math.ceil(wait * 1000)}
end
```

### 5-4. 거래소 이중 버킷

거래소 Rate Limit은 초당 + 분당 두 버킷을 동시에 검사:

```python
class ExchangeRateLimiter:
    """거래소별 이중 Token Bucket Rate Limiter"""

    async def acquire(self, exchange: str, user_id: str) -> RateLimitResult:
        """초당/분당 두 버킷 모두 통과해야 허용"""
        ...

    async def get_status(self, exchange: str, user_id: str) -> RateLimitStatus:
        """현재 남은 토큰 수 조회"""
        ...
```

## 6. 구현 파일 목록 (서브태스크별)

| ST# | 에이전트 | 생성/수정 파일 | 역할 |
|-----|----------|---------------|------|
| 1 | code-architect | `docs/tasks/v1-3-redis-cache-pubsub-plan.md` (본 문서) | 키 패턴, TTL 정책, 채널 구조 설계 |
| 2 | python-backend-expert | `server/app/core/redis_keys.py` | RedisKey, RedisTTL, PubSubChannel 상수 및 헬퍼 |
| 3 | python-backend-expert | `server/app/core/rate_limiter.py` | TokenBucket, ExchangeRateLimiter 클래스 |
| 3 | python-backend-expert | `server/app/core/lua/token_bucket.lua` | Lua 스크립트 파일 |
| 4 | python-backend-expert | `server/app/middleware/rate_limit.py` | RateLimitMiddleware (FastAPI) |
| 4 | python-backend-expert | `server/app/core/deps.py` (수정) | RateLimiter 의존성 추가 |
| 5 | code-architect | `docs/tasks/v1-3-redis-cache-pubsub-plan.md` (본 문서) | Pub/Sub 메시지 포맷 설계 |
| 6 | python-backend-expert | `server/app/core/pubsub.py` | RedisPublisher 클래스 |
| 7 | python-backend-expert | `server/app/ws/subscribers.py` | WS-Redis Pub/Sub 브리지 |
| 7 | python-backend-expert | `server/app/ws/hub.py` (수정) | Pub/Sub 구독 통합 |
| 8 | python-backend-expert | `server/app/services/auth_cache_service.py` | RefreshToken CRUD, 세션 관리 |
| 9 | python-backend-expert | `server/app/services/market_cache_service.py` | 시세/캔들/지표/장세 캐시 |
| 10 | python-backend-expert | `server/app/services/ai_cache_service.py` | AI 결정/뉴스감성/알림 캐시 |
| 10 | python-backend-expert | `server/tests/integration/test_redis_cache.py` | 통합 테스트 |
| 10 | python-backend-expert | `server/tests/integration/test_rate_limiter.py` | Rate Limiter 테스트 |
| 10 | python-backend-expert | `server/tests/integration/test_pubsub.py` | Pub/Sub 테스트 |

## 7. 모듈 의존 관계

```
app/core/redis_keys.py      ← (의존 없음, 순수 상수/함수)
app/core/redis.py            ← app/core/config.py (기존, 변경 없음)
app/core/rate_limiter.py     ← app/core/redis.py + redis_keys.py
app/core/pubsub.py           ← app/core/redis.py + redis_keys.py
app/middleware/rate_limit.py  ← app/core/rate_limiter.py + redis_keys.py
app/core/deps.py             ← app/core/rate_limiter.py (RateLimiter 추가)

app/services/auth_cache_service.py    ← app/core/redis.py + redis_keys.py
app/services/market_cache_service.py  ← app/core/redis.py + redis_keys.py
app/services/ai_cache_service.py      ← app/core/redis.py + redis_keys.py + pubsub.py

app/ws/subscribers.py ← app/core/pubsub.py + redis_keys.py
app/ws/hub.py         ← app/ws/subscribers.py (수정)

app/main.py → 변경 없음 (init_redis 이미 lifespan에 포함)
```

## 8. 인터페이스 정의

### 8-1. Publisher

```python
# server/app/core/pubsub.py

class RedisPublisher:
    def __init__(self, redis: Redis) -> None: ...

    async def publish_ticker(
        self, exchange: str, market: str, data: dict
    ) -> int: ...

    async def publish_orderbook(
        self, exchange: str, market: str, data: dict
    ) -> int: ...

    async def publish_trades(
        self, exchange: str, market: str, data: dict
    ) -> int: ...

    async def publish_my_order(
        self, user_id: str, data: dict
    ) -> int: ...

    async def publish_ai_signal(
        self, user_id: str, data: dict
    ) -> int: ...

    async def publish_notification(
        self, user_id: str, data: dict
    ) -> int: ...

    async def publish_price_alert(
        self, user_id: str, data: dict
    ) -> int: ...

    async def publish_system(self, data: dict) -> int: ...

    async def _publish(
        self, channel: str, msg_type: str, data: dict
    ) -> int:
        """공통 엔벨로프 래핑 후 발행"""
        ...
```

### 8-2. Subscriber (WS Bridge)

```python
# server/app/ws/subscribers.py

class PubSubSubscriber:
    """Redis Pub/Sub → WebSocket 브리지"""

    def __init__(self, redis: Redis, ws_hub: "WSHub") -> None: ...

    async def subscribe_ticker(
        self, exchange: str, market: str
    ) -> None: ...

    async def subscribe_user_channels(
        self, user_id: str
    ) -> None: ...

    async def unsubscribe_ticker(
        self, exchange: str, market: str
    ) -> None: ...

    async def unsubscribe_user_channels(
        self, user_id: str
    ) -> None: ...

    async def listen(self) -> None:
        """메시지 수신 루프 — WS Hub로 전달"""
        ...

    async def close(self) -> None: ...
```

### 8-3. Rate Limiter

```python
# server/app/core/rate_limiter.py

@dataclass
class RateLimitResult:
    allowed: bool
    remaining: float
    retry_after_ms: int

@dataclass
class RateLimitConfig:
    max_tokens: int
    refill_rate: float  # tokens/second
    window_ttl: int     # seconds

class TokenBucketRateLimiter:
    """단일 Token Bucket"""

    def __init__(self, redis: Redis) -> None: ...

    async def acquire(
        self, key: str, config: RateLimitConfig
    ) -> RateLimitResult: ...

class ExchangeRateLimiter:
    """거래소별 이중 버킷 (초당+분당)"""

    EXCHANGE_LIMITS: dict[str, tuple[RateLimitConfig, RateLimitConfig]]

    def __init__(self, redis: Redis) -> None: ...

    async def acquire(
        self, exchange: str, user_id: str
    ) -> RateLimitResult: ...

class APIRateLimiter:
    """API 전역 Rate Limiter"""

    def __init__(self, redis: Redis) -> None: ...

    async def check(
        self, identifier: str, authenticated: bool
    ) -> RateLimitResult: ...
```

### 8-4. 캐시 서비스

```python
# server/app/services/auth_cache_service.py

class AuthCacheService:
    def __init__(self, redis: Redis) -> None: ...

    async def store_refresh_token(
        self, user_id: str, client_id: str, token_hash: str
    ) -> None: ...

    async def get_refresh_token(
        self, user_id: str, client_id: str
    ) -> str | None: ...

    async def revoke_refresh_token(
        self, user_id: str, client_id: str
    ) -> None: ...

    async def revoke_all_sessions(self, user_id: str) -> int: ...

    async def list_sessions(self, user_id: str) -> list[str]: ...

    async def store_email_verify_code(
        self, email: str, code: str
    ) -> None: ...

    async def verify_email_code(
        self, email: str, code: str
    ) -> bool: ...
```

```python
# server/app/services/market_cache_service.py

class MarketCacheService:
    def __init__(self, redis: Redis) -> None: ...

    async def set_ticker(
        self, exchange: str, market: str, data: dict
    ) -> None: ...

    async def get_ticker(
        self, exchange: str, market: str
    ) -> dict | None: ...

    async def set_candles(
        self, exchange: str, market: str,
        timeframe: str, count: int, data: list[dict]
    ) -> None: ...

    async def get_candles(
        self, exchange: str, market: str,
        timeframe: str, count: int
    ) -> list[dict] | None: ...

    async def set_indicators(
        self, exchange: str, market: str,
        timeframe: str, data: dict
    ) -> None: ...

    async def get_indicators(
        self, exchange: str, market: str, timeframe: str
    ) -> dict | None: ...

    async def set_regime(
        self, exchange: str, market: str, data: dict
    ) -> None: ...

    async def get_regime(
        self, exchange: str, market: str
    ) -> dict | None: ...
```

```python
# server/app/services/ai_cache_service.py

class AICacheService:
    def __init__(self, redis: Redis, publisher: RedisPublisher) -> None: ...

    async def set_ai_decision(
        self, user_id: str, market: str, data: dict
    ) -> None:
        """캐시 저장 + ai_signal Pub/Sub 발행"""
        ...

    async def get_ai_decision(
        self, user_id: str, market: str
    ) -> dict | None: ...

    async def set_news_sentiment(
        self, coin: str, data: dict
    ) -> None: ...

    async def get_news_sentiment(self, coin: str) -> dict | None: ...

    async def set_last_run(
        self, user_id: str, coin: str
    ) -> None: ...

    async def get_last_run(
        self, user_id: str, coin: str
    ) -> str | None: ...

    async def update_unread_count(
        self, user_id: str, count: int
    ) -> None: ...

    async def get_unread_count(self, user_id: str) -> int: ...

    async def increment_unread_count(self, user_id: str) -> int: ...
```

## 9. Config 확장

```python
# server/app/core/config.py 에 추가할 설정

# Rate Limiting
RATE_LIMIT_API_ANON: int = 60           # 비인증 분당 요청 수
RATE_LIMIT_API_AUTH: int = 120          # 인증 사용자 분당 요청 수
RATE_LIMIT_LOGIN_MAX: int = 5           # 로그인 시도 최대 횟수
RATE_LIMIT_LOGIN_WINDOW: int = 900      # 로그인 제한 윈도우 (초)

# Redis Pub/Sub
REDIS_PUBSUB_URL: str = ""             # 별도 URL (비어있으면 REDIS_URL 사용)
```

## 10. 주요 결정사항

| 결정 | 선택 | 근거 |
|------|------|------|
| Rate Limiter 알고리즘 | Token Bucket (Lua) | 버스트 허용, 원자적 연산, 거래소 API 패턴 적합 |
| 키 구분자 | 콜론(`:`) | Redis 관례, Redis Insight 등 GUI 도구 호환 |
| Pub/Sub 채널 접두사 | `ch:` | 캐시 키와 네임스페이스 분리 |
| 메시지 포맷 | JSON 엔벨로프 | `{type, channel, timestamp, data}` 통일 |
| Lua 스크립트 관리 | 파일 기반 + `EVALSHA` | 성능(SHA 캐시), 유지보수성 |
| 캐시 직렬화 | JSON String (`decode_responses=True`) | 기존 클라이언트 설정과 일치, 디버깅 용이 |
| Refresh Token 저장 | String + Set (인덱스) | 개별 삭제 + 전체 세션 조회 모두 지원 |
| 거래소 Rate Limit | 이중 버킷 (초+분) | 거래소 실제 정책 반영 (초당+분당 별도 제한) |
| 미들웨어 위치 | FastAPI Middleware | 전역 적용, 라우터 단위 override 가능 |
| Redis DB 분리 | 단일 DB (db=0) | 소규모, 네임스페이스로 충분히 분리 |
| AOF 영속화 | Auth 키 보호 목적 | docker-compose에서 `appendonly yes` 설정 (v1-1에서 이미 구성) |
| WS my-orders 채널 | 별도 `ch:my_orders:{user_id}` | `ch:notification`과 분리 — 주문 상태는 실시간성, 알림과 관심사 다름 |
| WS trades 채널 | `ch:trades:{exchange}:{market}` 추가 | api-spec.md §5.2 trades WS 채널 요구사항 반영 |

## 11. 빌드 시퀀스

```
Phase A (병렬 시작):
  ┌─ ST1: Redis 키 패턴 및 TTL 정책 정의 (설계 — 본 문서)
  └─ ST5: Pub/Sub 채널 구조 및 메시지 포맷 정의 (설계 — 본 문서)

Phase B (ST1 완료 후):
  ┌─ ST2: redis_keys.py — 키 상수 + 헬퍼 함수 구현
  │
  └─ (ST5 완료 후 대기 없이 ST2와 병렬 가능)

Phase C (ST2 완료 후, 4-way 병렬):
  ┌─ ST3: rate_limiter.py — Token Bucket + Lua 스크립트
  ├─ ST8: auth_cache_service.py — 인증 캐시
  ├─ ST9: market_cache_service.py — 시세/지표 캐시
  └─ ST6: pubsub.py — Publisher 클래스 (ST5도 완료 필요)

Phase D (ST3 완료 후):
  └─ ST4: rate_limit middleware + deps.py 수정

Phase E (ST6 완료 후):
  └─ ST7: ws/subscribers.py — WS-Pub/Sub 브리지

Phase F (ST6+ST7+ST8+ST9 완료 후):
  └─ ST10: ai_cache_service.py + 통합 테스트
```

**최대 병렬도**: Phase C에서 4-way (ST3 + ST6 + ST8 + ST9)
**크리티컬 패스**: ST1 → ST2 → ST3 → ST4 (Rate Limiter 전체 경로)

---

## 12. Pub/Sub vs Redis Streams 비교 및 권장 (DB Architect)

### 12-1. 비교 분석

| 항목 | Pub/Sub | Redis Streams |
|------|---------|--------------|
| 메시지 지속성 | 없음 (연결 중만 수신) | 있음 (consumer group 재처리 가능) |
| 오프라인 구독자 | 메시지 유실 | 오프라인 복귀 후 미처리 메시지 수신 가능 |
| 메모리 사용 | 낮음 (채널당 수KB) | 높음 (MAXLEN 관리 필요) |
| 구현 복잡도 | 낮음 (SUBSCRIBE/PUBLISH) | 높음 (XADD/XREAD/XACK, consumer group 관리) |
| 실시간성 | push 즉시 | poll 기반 (XREAD BLOCK) |
| 메시지 순서 보장 | 없음 | 보장 (ID 단조 증가) |
| 최적 용도 | 최신 상태 브로드캐스트, Fire-and-forget | 이벤트 소싱, 재처리 필요 |

### 12-2. 채널별 권장 결정

| 채널 | 방식 | 근거 |
|------|------|------|
| `ch:ticker:{exchange}:{market}` | **Pub/Sub** | 최신 시세만 의미 있음, 유실 시 다음 메시지로 보완 |
| `ch:orderbook:{exchange}:{market}` | **Pub/Sub** | 전체 스냅샷 업데이트, 중간값 무의미 |
| `ch:ai_signal:{user_id}` | **Pub/Sub** | WS 연결 중 전달. 오프라인 시 DB 폴링으로 보완 |
| `ch:notification:{user_id}` | **Pub/Sub** | FCM push로 오프라인 보완 |
| `ch:price_alert:{user_id}` | **Pub/Sub** | 단발성 이벤트, 트리거 후 DB 기록 |
| 주문 체결 이벤트 (향후 M6+) | **Redis Streams 검토** | 미처리 이벤트 복구 필요 시 전환 권장 |

**결론**: 현 단계(M1~M4)는 Pub/Sub으로 충분. WebSocket 연결 해제 시 REST API 폴링으로 보완. Redis Streams는 M6 이후 주문 체결 파이프라인에서 단계적 도입.

---

## 13. 메모리 사용량 추정 및 maxmemory 설정 (DB Architect)

### 13-1. 키별 메모리 추정

| 키 패턴 | 값 크기 | 예상 키 수 | 소계 |
|---------|--------|-----------|------|
| `auth:refresh:{user_id}:{client_id}` | ~200B | 10,000 | ~2MB |
| `auth:refresh_index:{user_id}` | ~100B | 5,000 | ~0.5MB |
| `rate:api / rate:exchange` | ~80~160B | 7,000 | ~0.7MB |
| `ticker / orderbook` | ~500B~5KB | 300 | ~0.6MB |
| `candles:{exchange}:{market}:{tf}:{count}` | ~10KB | 500 | ~5MB |
| `indicators:{exchange}:{market}:{tf}` | ~2KB | 500 | ~1MB |
| `regime / ai_decision` | ~500B~1KB | 5,100 | ~5.1MB |
| `ai:news_sentiment / ai:last_run` | ~2KB~50B | 10,200 | ~0.9MB |
| `notifications:unread_count` | ~20B | 10,000 | ~0.2MB |
| **캐시 소계** | | | **~16MB** |
| Celery 브로커 버퍼 | | | ~50MB (여유) |
| Pub/Sub 구독자 출력 버퍼 | 100 구독자 | | ~32MB (설정값) |
| **총 예상 사용량** | | | **~100MB** |

### 13-2. maxmemory 권장 설정

```yaml
# docker-compose.yml Redis 서비스 (v1-1 기존 설정에 추가)
redis:
  image: redis:7-alpine
  command: >
    redis-server
    --maxmemory 256mb
    --maxmemory-policy allkeys-lru
    --client-output-buffer-limit pubsub 32mb 8mb 60
    --save ""
    --appendonly yes
    --appendfsync everysec
```

| 설정 | 값 | 근거 |
|------|-----|------|
| `maxmemory` | 256mb | 예상 ~100MB의 2.5배 여유 |
| `maxmemory-policy` | `allkeys-lru` | TTL 없는 키(Celery)도 LRU 퇴거 |
| `pubsub buffer` | 32mb/8mb/60s | 느린 WS 구독자 메모리 폭증 방지 |
| `appendonly yes` | everysec | refresh token 영속화 (재로그인 방지) |
| `save ""` | 비활성화 | AOF로만 영속화 |

---

## 14. Redis 연결 풀 설정 최적화 (DB Architect)

### 14-1. 현재 문제점

기존 `redis.from_url()`: 타임아웃 미설정(행잉 연결 위험), Pub/Sub 연결이 일반 캐시 풀과 혼재(연결 독점 위험).

### 14-2. 권장 연결 풀 설정

```python
# server/app/core/redis.py (개선)
from redis.asyncio.connection import ConnectionPool
from redis.backoff import ExponentialBackoff
from redis.retry import Retry

_redis_client: Redis | None = None
_pubsub_client: Redis | None = None


async def init_redis(redis_url: str) -> None:
    global _redis_client, _pubsub_client

    retry = Retry(ExponentialBackoff(cap=10.0, base=0.5), retries=3)

    # 일반 캐시/Rate Limiter 풀
    pool = ConnectionPool.from_url(
        redis_url,
        encoding="utf-8",
        decode_responses=True,
        max_connections=50,
        socket_connect_timeout=5.0,
        socket_timeout=5.0,
        retry=retry,
        retry_on_timeout=True,
        health_check_interval=30,
    )
    _redis_client = Redis(connection_pool=pool)
    await _redis_client.ping()

    # Pub/Sub 전용 풀 (연결 독점 → 분리)
    pubsub_pool = ConnectionPool.from_url(
        redis_url,
        encoding="utf-8",
        decode_responses=True,
        max_connections=20,
        socket_connect_timeout=5.0,
        socket_timeout=None,    # BLOCK 대기 허용
        retry=retry,
        retry_on_timeout=False,
        health_check_interval=60,
    )
    _pubsub_client = Redis(connection_pool=pubsub_pool)


def get_redis() -> Redis:
    if _redis_client is None:
        raise RuntimeError("Redis client not initialized. Call init_redis first.")
    return _redis_client


def get_pubsub_redis() -> Redis:
    """Pub/Sub 전용 클라이언트"""
    if _pubsub_client is None:
        raise RuntimeError("Redis pubsub client not initialized.")
    return _pubsub_client


async def close_redis() -> None:
    global _redis_client, _pubsub_client
    if _redis_client is not None:
        await _redis_client.aclose()
        _redis_client = None
    if _pubsub_client is not None:
        await _pubsub_client.aclose()
        _pubsub_client = None
```

### 14-3. 연결 풀 크기 산정

| 클라이언트 | max_connections | 산정 근거 |
|-----------|----------------|---------|
| 일반 (캐시/Rate Limiter) | 50 | FastAPI 동시 처리 × 안전 마진 |
| Pub/Sub 전용 | 20 | 동시 구독 채널 수 (ticker ~10 + user 채널 ~10) |
| Celery 워커 | Celery 별도 관리 | `CELERY_REDIS_MAX_CONNECTIONS` 설정 |

### 14-4. Retry 전략

| 상황 | 동작 |
|------|------|
| 연결 실패 | Exponential Backoff (0.5s → 1s → 2s, cap 10s), 3회 재시도 |
| 소켓 타임아웃 (일반) | 재시도 O |
| 소켓 타임아웃 (Pub/Sub) | 재시도 X (BLOCK 정상 상황) |
| Redis 서버 다운 | 3회 재시도 후 `ConnectionError` → 앱 레벨 503 응답 |

---

## 15. 모니터링 지표 (DB Architect)

### 15-1. Redis INFO 핵심 지표

```bash
# 메모리
redis-cli INFO memory | grep -E "used_memory_human|mem_fragmentation_ratio|maxmemory_human"

# 캐시 히트율
redis-cli INFO stats | grep -E "keyspace_hits|keyspace_misses|evicted_keys"
# hit_rate = keyspace_hits / (keyspace_hits + keyspace_misses)  목표: > 90%

# 연결
redis-cli INFO clients | grep -E "connected_clients|blocked_clients"

# 슬로우 쿼리
redis-cli SLOWLOG GET 10
```

### 15-2. 알림 임계값

| 지표 | Warning | Critical | 권장 액션 |
|------|---------|---------|---------|
| `used_memory` | > 200MB | > 240MB | maxmemory 증설, 대형 키 점검 |
| `mem_fragmentation_ratio` | > 1.5 | > 2.0 | `MEMORY PURGE` 또는 Redis 재시작 |
| Cache hit rate | < 80% | < 60% | TTL 정책 검토, 캐시 워밍 |
| `evicted_keys` 증가 추세 | Warning | 급증 | maxmemory 증설 |
| `connected_clients` | > 60 | > 80 | 연결 풀 크기 증설 |
| `blocked_clients` | > 10 | > 20 | Pub/Sub 구독자 상태 확인 |

### 15-3. 슬로우 쿼리 설정 및 금지 패턴

```
slowlog-log-slower-than 10000   # 10ms 이상 기록 (microseconds 단위)
slowlog-max-len 128
```

- **`KEYS *` 절대 금지** → `SCAN` 사용 필수 (운영 중 전체 응답 차단 위험)
- Lua 스크립트 시간 초과 → 스크립트 최적화
- 대형 JSON 값 → 키당 최대 1MB 제한 권장

### 15-4. 운영 명령어

```bash
# 메모리 단편화 해소
redis-cli MEMORY PURGE

# 가장 큰 키 확인
redis-cli --bigkeys

# 특정 패턴 키 개수 (SCAN 사용)
redis-cli --scan --pattern "ai_decision:*" | wc -l

# 구독 채널 목록 및 구독자 수
redis-cli PUBSUB CHANNELS "ch:*"
redis-cli PUBSUB NUMSUB ch:ticker:upbit:KRW-BTC

# Lua 스크립트 SHA 목록
redis-cli SCRIPT LIST
```

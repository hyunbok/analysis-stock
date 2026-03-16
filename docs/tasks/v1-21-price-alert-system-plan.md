# v1-21: 가격 알림 시스템 구현 설계서

> **태스크**: v1:21 (M9)
> **브랜치**: `feature/v1-21_price-alert-system`
> **작성**: project-architect + code-architect + db-architect
> **최종 갱신**: 2026-03-16

---

## 1. 현재 상태 (프로젝트 컨텍스트)

### 활용 가능한 기존 인프라

| 컴포넌트 | 위치 | 역할 |
|----------|------|------|
| PriceAlert 모델 | `models/trading.py:219-274` | PG 테이블 정의 완료 (인덱스 4개 + CHECK) |
| Notification 도큐먼트 | `documents/notifications.py` | MongoDB 알림 기록 (TTL 90일, 인덱스 4개) |
| RedisPublisher.publish_price_alert() | `core/pubsub.py:41-43` | 가격 알림 Pub/Sub 발행 |
| RedisPublisher.publish_notification() | `core/pubsub.py:37-39` | 범용 알림 Pub/Sub 발행 |
| PubSubChannel.price_alert() | `core/redis_keys.py:244-246` | `ch:price_alert:{user_id}` |
| PubSubChannel.ticker() | `core/redis_keys.py:228-230` | `ch:ticker:{exchange}:{market}` |
| RedisKey.unread_count() | `core/redis_keys.py:208-210` | `notifications:unread_count:{user_id}` |
| RedisTTL.UNREAD_COUNT | `core/redis_keys.py:52` | 1시간 |
| MarketCacheService | `services/market_cache_service.py` | Redis 캐시 시세 조회 |
| Client 모델 (fcm_token) | `models/user.py` | 기기별 FCM 토큰 |

### 기존 모델 상세 (PriceAlert — 이미 구현 완료)

```python
# server/app/models/trading.py:219-274
class PriceAlert(Base):
    __tablename__ = "price_alerts"
    # CHECK: condition IN ('above', 'below')
    # Indexes: user_id, is_active, coin_id, active_untriggered (partial)

    id: UUID PK (gen_random_uuid)
    user_id: UUID FK → users.id (CASCADE)
    coin_id: UUID FK → coins.id (CASCADE)
    exchange_account_id: UUID FK nullable → user_exchange_accounts.id (SET NULL)
    condition: String(10) — 'above' | 'below'
    target_price: Numeric(20, 8)
    is_triggered: bool (default false)
    is_active: bool (default true)
    triggered_at: DateTime(tz) nullable
    created_at: DateTime(tz) server_default=now()
    # ⚠️ updated_at 없음 → migration 007에서 추가
```

### 기존 인덱스 (price_alerts)

```sql
ix_price_alerts_user_id                  -- 사용자별 조회
ix_price_alerts_is_active                -- 활성화 필터
ix_price_alerts_coin_id                  -- 코인별 조회
ix_price_alerts_active_untriggered       -- PARTIAL(user_id, coin_id): is_active=true AND is_triggered=false
ck_price_alerts_condition                -- CHECK: 'above' | 'below'
```

---

## 2. 아키텍처 결정 사항

### ADR-021-1: 알림 감지 방식 — PriceAlertMonitor (Redis Pub/Sub 구독)

**상태**: 승인됨
**맥락**: 실시간 시세 수신 시 활성 알림 조건 판단 방법
**선택지**:
1. WS Hub 내 인라인 감지 (시세 수신 시 즉시 체크)
2. Celery Beat 주기적 폴링 (30초마다 전체 활성 알림 체크)
3. **별도 PriceAlertMonitor가 Redis Pub/Sub ticker 구독하여 이벤트 드리븐 감지**

**결정**: **PriceAlertMonitor (Redis Pub/Sub ticker 구독)**
**근거**:
- 이벤트 드리븐 → 시세 변동 즉시 감지 (폴링 대비 sub-second 레이턴시)
- `ch:ticker:{exchange}:{market}` 패턴 구독으로 가격 변경 시에만 DB 조회
- WS Hub hot path와 분리 (별도 모듈, SRP 유지)
- 가격 변동 없는 코인에 대한 불필요한 DB 조회 제거
- `ix_price_alerts_coin_active_untriggered` 신규 partial index로 coin_id 기준 고속 조회

**영향**: `ws/price_alert_monitor.py` 신규, `main.py` lifespan 연동

### ADR-021-2: 활성 알림 로딩 전략 — DB 직접 조회

**상태**: 승인됨
**맥락**: 가격 변동 시 활성 알림을 어디서 로드할지
**선택지**:
1. Redis Set 캐싱 (생성/수정/삭제 시 동기화)
2. DB 직접 조회 (partial index 활용)

**결정**: **DB 직접 조회**
**근거**:
- 사용자당 최대 50개, 전체 수천~수만개 → `ix_price_alerts_coin_active_untriggered` partial index로 index-only scan
- Redis Set 관리 시 생성/수정/삭제/트리거 동기화 복잡도 증가
- 이벤트 드리븐 방식이므로 ticker 수신 시에만 DB 조회 (폴링처럼 주기적 부하 아님)
- 초당 수천 건 ticker 처리 시 Redis 캐시 도입 재검토 (향후)

### ADR-021-3: 트리거 후 자동 비활성화

**상태**: 승인됨
**결정**: **1회 트리거 → 자동 비활성화** (`is_triggered=True`, `is_active=False`)
**근거**: PRD 명세 준수. 재활성화는 사용자 PUT으로 수동 처리.

### ADR-021-4: 삭제 방식 — Hard Delete

**상태**: 승인됨
**결정**: **Hard Delete** — 모델에 soft_deleted_at 없음, 트리거 이력은 MongoDB Notification에 보존 (90일 TTL)

### ADR-021-5: 알림 기록 — 기존 Notification Document 재사용

**상태**: 승인됨
**결정**: **기존 Notification Document 재사용** (`type="price_alert"`)
- `data` dict에 `alert_id`, `coin_symbol`, `exchange_type`, `condition`, `target_price`, `current_price` 저장
- 별도 필드/컬렉션 추가 불필요

### ADR-021-6: FCM 푸시 — 인터페이스 정의 + 스텁

**상태**: 승인됨
**결정**: **FCMService에 send_price_alert() 정의, 내부는 fire-and-forget 로깅 스텁**
- Client 모델의 `fcm_token` 필드 활용 (복수 기기 지원)
- Firebase Admin SDK / 서버키 설정은 v1-21 범위 밖
- Settings에 `FCM_SERVER_KEY: str | None = None` 추가

### ADR-021-7: 트리거 중복 방지 — DB + Redis 이중 보호

**상태**: 승인됨
**결정**:
- **1차 방어 (DB)**: `UPDATE price_alerts SET is_triggered=true WHERE id=:id AND is_triggered=false` — affected_rows=0이면 이미 트리거됨
- **2차 방어 (Redis)**: `SETNX price_alert:triggering:{alert_id} 1 EX 30` — 30초 TTL, 멀티 인스턴스 중복 방지

### ADR-021-8: 미읽 카운트 — 두 개 별도 카운터

**상태**: 승인됨
**결정**:
- `notifications:unread_count:{user_id}` (TTL 1시간) — 전체 알림 미읽 (WS 배지)
- `price_alert:unread:{user_id}` (TTL 30일) — 가격 알림 전용 미읽 (앱 재시작 후 유지)

### ADR-021-9: Notification 페이지네이션 — 커서 기반

**상태**: 승인됨
**결정**: **커서 기반** (`cursor=created_at ISO datetime`, `limit=20`)
**근거**: MongoDB 시계열 데이터, 무한 스크롤 UI에 적합, 오프셋 기반 대비 성능 우수

### ADR-021-10: 읽음 처리 HTTP 메서드 — PATCH

**상태**: 승인됨
**결정**: `PATCH` (PUT 아님) — 부분 업데이트 의미상 정확

---

## 3. 시스템 아키텍처

### 3.1 전체 흐름도

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          Flutter Client                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────────────┐  │
│  │ 알림 설정 UI │  │ 알림 목록 UI │  │ WS 구독 (price_alert/notif) │  │
│  └──────┬───────┘  └──────┬───────┘  └──────────────┬───────────────┘  │
└─────────┼──────────────────┼────────────────────────┼──────────────────┘
          │ REST API         │ REST API               │ WebSocket
┌─────────▼──────────────────▼────────────────────────▼──────────────────┐
│                          FastAPI Server                                  │
│  ┌──────────────────┐  ┌───────────────────┐  ┌──────────────────┐     │
│  │ price_alerts.py  │  │ notifications.py  │  │ WS Hub           │     │
│  │ (CRUD API)       │  │ (조회/읽음 PATCH) │  │ (Pub/Sub→Client) │     │
│  └────────┬─────────┘  └────────┬──────────┘  └────────┬─────────┘     │
│           │                      │                       │              │
│  ┌────────▼─────────┐  ┌────────▼──────────┐            │              │
│  │PriceAlertService │→→│NotificationService│            │              │
│  └────────┬─────────┘  └────────┬──────────┘            │              │
│           │                      │                       │              │
│  ┌────────▼─────────┐  ┌────────▼──────────┐            │              │
│  │PriceAlertRepo    │  │NotificationRepo   │            │              │
│  │(PostgreSQL)      │  │(MongoDB/Beanie)   │            │              │
│  └──────────────────┘  └───────────────────┘            │              │
│                                                          │              │
│  ┌──────────────────────────────────────────────────────┤              │
│  │          PriceAlertMonitor (lifespan)                 │              │
│  │  Redis Pub/Sub 구독: ch:ticker:{exchange}:{market}   │              │
│  │  → DB 활성 알림 조회 → 조건 비교 → 트리거            │              │
│  │  → PG UPDATE + MongoDB INSERT + Redis INCR           ├──────────────┘
│  │  → Pub/Sub publish_price_alert (→ WS Hub → Client)   │ Redis Pub/Sub
│  │  → FCM 스텁                                          │
│  └──────────────────────────────────────────────────────┘
└─────────────────────────────────────────────────────────────────────────┘
          │              │              │
  ┌───────▼──────┐ ┌────▼─────┐ ┌─────▼─────┐
  │ PostgreSQL   │ │ MongoDB  │ │  Redis    │
  │ price_alerts │ │ notifs   │ │ cache/pub │
  └──────────────┘ └──────────┘ └───────────┘
```

### 3.2 데이터 흐름

```
알림 생성:   Client → POST /price-alerts → PriceAlertService.create() → PG INSERT
알림 수정:   Client → PUT /price-alerts/{id} → PriceAlertService.update() → PG UPDATE
알림 삭제:   Client → DELETE /price-alerts/{id} → PG DELETE (hard)
알림 감지:   Redis ticker Pub/Sub → PriceAlertMonitor._on_ticker()
              → PriceAlertRepo.get_active_untriggered_by_market() → 조건 비교
트리거:      Redis SETNX(중복방지) → PG UPDATE(is_triggered, is_active=false)
              → MongoDB INSERT(Notification) → Redis INCR(unread)
              → Pub/Sub publish(price_alert + notification) → FCM 스텁
읽음 처리:   Client → PATCH /notifications/{id}/mark-read → MongoDB UPDATE → Redis DECR
전체 읽음:   Client → PATCH /notifications/mark-all-read → MongoDB bulk UPDATE → Redis DEL
```

### 3.3 시퀀스 다이어그램 — 알림 트리거

```
Exchange WS  →  WS Hub  →  Redis Pub/Sub
                               │
                    PriceAlertMonitor (subscriber)
                               │
                    ┌──────────▼──────────┐
                    │ _on_ticker()        │
                    │ parse: exchange,    │
                    │   market, price     │
                    └──────────┬──────────┘
                               │
                    ┌──────────▼──────────┐
                    │ PriceAlertRepo      │
                    │ .get_active_        │
                    │  untriggered_by_    │
                    │  market()           │
                    │ (partial index)     │
                    └──────────┬──────────┘
                               │ alerts[]
                    ┌──────────▼──────────┐
                    │ for alert in alerts │
                    │ if condition_met:   │
                    └──────────┬──────────┘
                               │
              ┌────────────────┼────────────────┐
              │                │                 │
    ┌─────────▼────┐  ┌───────▼─────┐  ┌───────▼──────┐
    │ Redis SETNX  │  │ PG UPDATE   │  │ MongoDB      │
    │ triggering   │  │ is_triggered│  │ Notification │
    │ lock(30s)    │  │ is_active=F │  │ INSERT       │
    └──────────────┘  └─────────────┘  └──────────────┘
              │                                  │
    ┌─────────▼──────────────────────────────────▼────┐
    │ Redis INCR(unread) + Pub/Sub publish + FCM stub │
    └─────────────────────────────────────────────────┘
```

---

## 4. API 엔드포인트 상세 규격

### 4.1 가격 알림 CRUD — `api/v1/price_alerts.py`

라우터 등록:
```python
# api/v1/__init__.py
router.include_router(price_alerts_router, prefix="/price-alerts", tags=["price-alerts"])
router.include_router(notifications_router, prefix="/notifications", tags=["notifications"])
```

#### POST /api/v1/price-alerts — 알림 생성

```
Headers: Authorization: Bearer {access_token}
Body:
{
  "coin_id": "uuid",
  "exchange_account_id": "uuid | null",
  "condition": "above" | "below",
  "target_price": "85000000.00"
}

Response 201: ApiResponse[PriceAlertResponse]
{
  "data": {
    "id": "uuid",
    "coin_id": "uuid",
    "coin_symbol": "BTC/KRW",
    "coin_name_ko": "비트코인",
    "exchange_account_id": "uuid | null",
    "condition": "above",
    "target_price": "85000000.00000000",
    "is_triggered": false,
    "is_active": true,
    "triggered_at": null,
    "created_at": "2026-03-16T10:00:00Z"
  },
  "error": null,
  "meta": {"timestamp": "..."}
}

Errors:
  404 PRICE_ALERT_COIN_NOT_FOUND — coin_id 존재하지 않음
  403 PRICE_ALERT_ACCOUNT_NOT_OWNED — 본인 소유 아닌 거래소 계정
  400 PRICE_ALERT_MAX_EXCEEDED — 사용자당 최대 50개 초과
```

#### GET /api/v1/price-alerts — 목록 조회

```
Headers: Authorization: Bearer {access_token}
Query: ?active=true&coin_id={uuid}&page=1&size=20

Response 200: ApiResponse[PriceAlertListResponse]
{
  "data": {
    "alerts": [PriceAlertResponse, ...],
    "unread_count": 3
  }
}
```

#### PUT /api/v1/price-alerts/{alert_id} — 수정

```
Headers: Authorization: Bearer {access_token}
Body:
{
  "condition": "below",        // optional
  "target_price": "80000000",  // optional
  "is_active": true            // optional
}

Response 200: ApiResponse[PriceAlertResponse]

Errors:
  404 PRICE_ALERT_NOT_FOUND
  403 PRICE_ALERT_ACCESS_DENIED
  409 PRICE_ALERT_ALREADY_TRIGGERED — is_triggered=True인 알림은 재활성화 불가
```

#### DELETE /api/v1/price-alerts/{alert_id} — 삭제

```
Headers: Authorization: Bearer {access_token}

Response 200: ApiResponse[None]

Errors:
  404 PRICE_ALERT_NOT_FOUND
  403 PRICE_ALERT_ACCESS_DENIED
```

### 4.2 알림 기록 — `api/v1/notifications.py`

**경로 등록 순서 중요** (FastAPI 경로 충돌 방지):
```python
@router.get("/unread-count", ...)         # 정적 경로 먼저
@router.patch("/mark-all-read", ...)      # 정적 경로 먼저
@router.get("", ...)                      # 목록
@router.patch("/{notification_id}/mark-read", ...)  # 동적 경로 나중
```

#### GET /api/v1/notifications — 알림 목록 (커서 기반)

```
Headers: Authorization: Bearer {access_token}
Query: ?type=price_alert&limit=20&cursor={iso_datetime}

Response 200: ApiResponse[NotificationListResponse]
{
  "data": {
    "notifications": [
      {
        "notification_id": "mongo_object_id_str",
        "type": "price_alert",
        "title": "BTC/KRW 목표가 도달",
        "body": "BTC/KRW이(가) 85,000,000원에 도달했습니다.",
        "data": {
          "alert_id": "pg_uuid_str",
          "coin_symbol": "BTC/KRW",
          "exchange_type": "upbit",
          "condition": "above",
          "target_price": "85000000",
          "current_price": "85100000"
        },
        "is_read": false,
        "created_at": "2026-03-16T10:00:30Z"
      }
    ],
    "next_cursor": "2026-03-16T09:55:00Z",
    "unread_count": 3
  }
}
```

#### GET /api/v1/notifications/unread-count — 미읽 카운트

```
Response 200: ApiResponse[UnreadCountResponse]
{
  "data": {"unread_count": 3}
}

Cache: Redis GET → 있으면 반환, 없으면 MongoDB count → Redis SETEX (TTL 1시간)
```

#### PATCH /api/v1/notifications/{notification_id}/mark-read — 읽음 처리

```
Headers: Authorization: Bearer {access_token}

Response 200: ApiResponse[None]

Side effects:
  - MongoDB: is_read = True
  - Redis: unread_count DECR (max(0, count-1))
```

#### PATCH /api/v1/notifications/mark-all-read — 전체 읽음

```
Headers: Authorization: Bearer {access_token}

Response 200: ApiResponse[MarkAllReadResponse]
{
  "data": {"marked": 5}
}

Side effects:
  - MongoDB: bulk update is_read=False → True (user_id 기준)
  - Redis: unread_count DEL (또는 SET 0)
```

---

## 5. 데이터 모델 변경

### 5.1 PostgreSQL — PriceAlert 수정 (migration 007)

**변경 사항**:
1. `updated_at` 컬럼 추가
2. `ix_price_alerts_coin_active_untriggered` partial 인덱스 추가 (백그라운드 감지 최적화)

```python
# server/app/models/trading.py — PriceAlert 클래스에 추가
updated_at: Mapped[datetime] = mapped_column(
    DateTime(timezone=True),
    server_default=func.now(),
    onupdate=func.now(),
)

# __table_args__에 인덱스 추가
Index(
    "ix_price_alerts_coin_active_untriggered",
    "coin_id",
    postgresql_where=text("is_active = true AND is_triggered = false"),
),
```

**Alembic 마이그레이션**: `007_v1_21_price_alert_extension.py`
- revision: `g7h8i9j0k1l2`
- down_revision: `f6a7b8c9d0e5`

```sql
-- upgrade
ALTER TABLE price_alerts ADD COLUMN updated_at TIMESTAMPTZ DEFAULT now();
UPDATE price_alerts SET updated_at = created_at WHERE updated_at IS NULL;
ALTER TABLE price_alerts ALTER COLUMN updated_at SET NOT NULL;

CREATE INDEX ix_price_alerts_coin_active_untriggered
ON price_alerts (coin_id)
WHERE is_active = true AND is_triggered = false;

-- downgrade
DROP INDEX ix_price_alerts_coin_active_untriggered;
ALTER TABLE price_alerts DROP COLUMN updated_at;
```

### 5.2 MongoDB — Notification (기존, 변경 없음)

`data` dict 페이로드 (type="price_alert"):
```json
{
  "alert_id": "<PriceAlert UUID>",
  "coin_symbol": "BTC/KRW",
  "exchange_type": "upbit",
  "condition": "below",
  "target_price": "90000000",
  "current_price": "89500000"
}
```

### 5.3 Redis 키 패턴

| 키 | 용도 | TTL |
|----|------|-----|
| `notifications:unread_count:{user_id}` | 전체 알림 미읽 카운트 (기존) | 1시간 |
| `price_alert:unread:{user_id}` | 가격 알림 전용 미읽 카운트 (**신규**) | 30일 |
| `price_alert:triggering:{alert_id}` | 트리거 중복 방지 Lock (**신규**) | 30초 |

**`core/redis_keys.py` 변경** (db-architect 구현 완료):

```python
class RedisTTL:
    PRICE_ALERT_UNREAD_COUNT = 30 * 24 * 3600  # 30일
    PRICE_ALERT_TRIGGERING = 30                 # 30초

class RedisKey:
    @staticmethod
    def price_alert_unread_count(user_id: str) -> str:
        return f"price_alert:unread:{user_id}"

    @staticmethod
    def price_alert_triggering(alert_id: str) -> str:
        """트리거 중복 방지 (SETNX, 멀티 인스턴스 보호)."""
        return f"price_alert:triggering:{alert_id}"
```

---

## 6. 스키마 정의

### 6.1 `schemas/price_alert.py`

```python
from __future__ import annotations
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal
from pydantic import BaseModel, Field

# ── 요청 ──────────────────────────────────────────────────────────────────

class CreatePriceAlertRequest(BaseModel):
    coin_id: uuid.UUID
    exchange_account_id: uuid.UUID | None = None
    condition: Literal["above", "below"]
    target_price: Decimal = Field(gt=0, decimal_places=8)

class UpdatePriceAlertRequest(BaseModel):
    condition: Literal["above", "below"] | None = None
    target_price: Decimal | None = Field(default=None, gt=0, decimal_places=8)
    is_active: bool | None = None

# ── 응답 ──────────────────────────────────────────────────────────────────

class PriceAlertResponse(BaseModel):
    id: uuid.UUID
    coin_id: uuid.UUID
    coin_symbol: str               # Coin.symbol (JOIN)
    coin_name_ko: str | None       # Coin.name_ko (JOIN)
    exchange_account_id: uuid.UUID | None
    condition: str
    target_price: Decimal
    is_triggered: bool
    is_active: bool
    triggered_at: datetime | None
    created_at: datetime

class PriceAlertListResponse(BaseModel):
    """GET /price-alerts 응답 — 알림 목록 + 미읽 카운트 통합."""
    alerts: list[PriceAlertResponse]
    unread_count: int

class MarkAllReadResponse(BaseModel):
    marked: int
```

### 6.2 `schemas/notification.py`

```python
from datetime import datetime
from pydantic import BaseModel

class NotificationResponse(BaseModel):
    notification_id: str       # MongoDB ObjectId as string
    type: str                  # "price_alert" | "ai_trading" | "order_execution"
    title: str
    body: str
    data: dict | None
    is_read: bool
    created_at: datetime

class NotificationListResponse(BaseModel):
    notifications: list[NotificationResponse]
    next_cursor: str | None    # ISO datetime string, None = 마지막 페이지
    unread_count: int

class UnreadCountResponse(BaseModel):
    unread_count: int
```

---

## 7. 에러 팩토리

```python
# server/app/core/exceptions.py — 추가

class PriceAlertErrors:
    """가격 알림 도메인 에러 팩토리."""

    @staticmethod
    def not_found() -> AppError:
        return AppError("PRICE_ALERT_NOT_FOUND", "가격 알림을 찾을 수 없습니다.", 404)

    @staticmethod
    def access_denied() -> AppError:
        return AppError("PRICE_ALERT_ACCESS_DENIED", "접근 권한이 없습니다.", 403)

    @staticmethod
    def coin_not_found() -> AppError:
        return AppError("PRICE_ALERT_COIN_NOT_FOUND", "등록된 코인을 찾을 수 없습니다.", 404)

    @staticmethod
    def exchange_account_not_owned() -> AppError:
        return AppError("PRICE_ALERT_ACCOUNT_NOT_OWNED", "본인 소유 거래소 계정이 아닙니다.", 403)

    @staticmethod
    def already_triggered() -> AppError:
        """이미 트리거된 알림은 재활성화 불가."""
        return AppError("PRICE_ALERT_ALREADY_TRIGGERED", "이미 발동된 알림은 재활성화할 수 없습니다.", 409)

    @staticmethod
    def max_exceeded() -> AppError:
        return AppError("PRICE_ALERT_MAX_EXCEEDED", "사용자당 최대 50개의 가격 알림만 생성 가능합니다.", 400)


class NotificationErrors:
    """알림 도메인 에러 팩토리."""

    @staticmethod
    def not_found() -> AppError:
        return AppError("NOTIFICATION_NOT_FOUND", "알림을 찾을 수 없습니다.", 404)

    @staticmethod
    def access_denied() -> AppError:
        return AppError("NOTIFICATION_ACCESS_DENIED", "접근 권한이 없습니다.", 403)
```

---

## 8. 리포지토리 설계

### 8.1 `repositories/price_alert_repository.py` (PG/AsyncSession)

```python
class PriceAlertRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def create(
        self, *, user_id, coin_id, exchange_account_id, condition, target_price
    ) -> PriceAlert:
        """INSERT + flush + refresh. Coin eager load 포함."""

    async def get_by_id(self, alert_id: UUID) -> PriceAlert | None:
        """selectinload(coin) 포함."""

    async def get_by_user_and_id(
        self, user_id: UUID, alert_id: UUID
    ) -> PriceAlert | None:
        """소유권 검증용. selectinload(coin) 포함."""

    async def get_by_user(
        self, user_id: UUID, *, active: bool | None = None
    ) -> list[PriceAlert]:
        """ORDER BY created_at DESC. selectinload(coin) 포함.
        active=None: 전체, True: 활성만, False: 비활성만."""

    async def count_by_user(self, user_id: UUID) -> int:
        """사용자 활성 알림 수 (max 50 체크용)."""

    async def get_active_untriggered_by_market(
        self, exchange_type: str, market_code: str
    ) -> list[PriceAlert]:
        """ix_price_alerts_coin_active_untriggered partial index 활용.
        PriceAlertMonitor에서 호출.
        JOIN Coin → exchange_type + market_code 필터.
        WHERE is_active=True AND is_triggered=False AND coin.market_code=:market"""

    async def mark_triggered(
        self, alert_id: UUID
    ) -> bool:
        """UPDATE ... SET is_triggered=True, is_active=False, triggered_at=now()
        WHERE id=:id AND is_triggered=False.
        Returns: affected_rows > 0 (중복 트리거 방지 1차 방어)."""

    async def update(self, alert: PriceAlert, **kwargs) -> PriceAlert:
        """동적 UPDATE."""

    async def delete(self, alert_id: UUID) -> None:
        """Hard DELETE."""
```

### 8.2 `repositories/notification_repository.py` (MongoDB/Beanie)

```python
class NotificationRepository:
    """Beanie Document 직접 호출을 서비스에서 분리 (일관성 패턴)."""

    async def create(
        self, *, user_id, type, title, body, data
    ) -> Notification:
        """Notification INSERT."""

    async def get_by_id(self, notification_id: str) -> Notification | None:
        """ObjectId 문자열 → Notification 조회."""

    async def list_by_user(
        self, user_id: UUID, *, type_filter: str | None = None,
        cursor: datetime | None = None, limit: int = 20
    ) -> list[Notification]:
        """커서 기반 페이지네이션. created_at DESC.
        cursor 있으면: created_at < cursor."""

    async def mark_read(self, notification_id: str) -> bool:
        """is_read = True. Returns: modified."""

    async def mark_all_read(self, user_id: UUID) -> int:
        """user_id + is_read=False → True. Returns: modified_count."""

    async def count_unread(self, user_id: UUID) -> int:
        """user_id + is_read=False 카운트."""
```

---

## 9. 서비스 레이어 설계

### 9.1 PriceAlertService

```python
class PriceAlertService:
    def __init__(
        self,
        alert_repo: PriceAlertRepository,
        coin_repo: CoinRepository,
        exchange_account_repo: ExchangeAccountRepository,
        notification_service: NotificationService,  # 단방향 의존
        fcm_service: FCMService,
        client_repo: ClientRepository,               # FCM 토큰 조회
        redis: Redis,
    ) -> None: ...

    async def create_alert(user_id, body: CreatePriceAlertRequest) -> PriceAlertResponse:
        1. coin_id 존재 확인 → PriceAlertErrors.coin_not_found()
        2. exchange_account_id 있으면 소유권 확인 → PriceAlertErrors.exchange_account_not_owned()
        3. count_by_user >= 50 → PriceAlertErrors.max_exceeded()
        4. PG INSERT
        5. PriceAlertResponse 반환 (coin.symbol, coin.name_ko JOIN)

    async def get_alerts(user_id, active: bool | None) -> PriceAlertListResponse:
        1. PG 목록 조회 (active 필터)
        2. Redis unread_count GET (없으면 MongoDB count → SETEX)
        3. PriceAlertListResponse 반환

    async def update_alert(user_id, alert_id, body: UpdatePriceAlertRequest) -> PriceAlertResponse:
        1. get_by_user_and_id 소유권 확인 → 404/403
        2. is_active=True 요청 AND is_triggered=True → PriceAlertErrors.already_triggered()
        3. PG UPDATE

    async def delete_alert(user_id, alert_id) -> None:
        1. 소유권 확인
        2. PG DELETE (hard)

    async def process_ticker(exchange_type, market_code, current_price: Decimal) -> None:
        """PriceAlertMonitor에서 호출 (백그라운드).
        1. get_active_untriggered_by_market(exchange_type, market_code)
        2. 각 알림 조건 체크:
           - above: current_price >= target_price
           - below: current_price <= target_price
        3. 트리거 시 _trigger_alert() 호출"""

    async def _trigger_alert(alert, current_price, coin_symbol, exchange_type) -> None:
        """개별 알림 트리거 처리.
        a. Redis SETNX(price_alert:triggering:{id}, 30s) — 실패 시 스킵
        b. PG mark_triggered() — affected=0이면 스킵 (이미 트리거)
        c. notification_service.create_notification(...)
        d. client_repo.get_active_by_user(alert.user_id)
           → FCM 발송 (복수 기기, fire-and-forget)"""
```

### 9.2 NotificationService

```python
class NotificationService:
    def __init__(
        self,
        notification_repo: NotificationRepository,
        redis: Redis,
        publisher: RedisPublisher,
    ) -> None: ...

    async def list_notifications(user_id, type_filter, cursor, limit) -> NotificationListResponse:
        1. notification_repo.list_by_user(cursor 기반)
        2. next_cursor 계산 (마지막 항목 created_at)
        3. get_unread_count()
        4. NotificationListResponse 반환

    async def mark_as_read(user_id, notification_id) -> None:
        1. notification_repo.get_by_id → 존재 + user_id 검증
        2. notification_repo.mark_read()
        3. Redis DECR(unread_count) — max(0, count-1)

    async def mark_all_as_read(user_id) -> int:
        1. notification_repo.mark_all_read() → marked count
        2. Redis DEL(unread_count)
        3. 반환: marked

    async def get_unread_count(user_id) -> int:
        1. Redis GET → 있으면 반환
        2. notification_repo.count_unread() → Redis SETEX (TTL 1시간)

    async def create_notification(user_id, type, title, body, data) -> Notification:
        1. notification_repo.create()
        2. Redis INCR(unread_count)
        3. publisher.publish_notification(user_id, notification_data)
        4. 반환: notification
```

### 9.3 FCMService (스텁)

```python
class FCMService:
    def __init__(self, settings: Settings) -> None:
        self._enabled = bool(settings.FCM_SERVER_KEY)

    async def send_price_alert(
        self, fcm_token: str, coin_symbol: str,
        condition: str, target_price: Decimal, current_price: Decimal,
    ) -> bool:
        """FCM 발송. 미설정 시 로깅만. 실패 시 False (fire-and-forget)."""
        if not self._enabled:
            logger.debug("FCM disabled, skipping push for %s", coin_symbol)
            return False
        # TODO: FCM v1 API 또는 Firebase Admin SDK 구현
        logger.info("FCM stub: %s %s %s→%s", coin_symbol, condition, target_price, current_price)
        return False
```

---

## 10. PriceAlertMonitor (실시간 감지)

### 10.1 `ws/price_alert_monitor.py`

```python
class PriceAlertMonitor:
    """Redis Pub/Sub ticker 채널 구독 → 가격 알림 조건 체크.

    FastAPI lifespan에서 시작/중지. 별도 asyncio.Task로 실행.
    ch:ticker:{exchange}:{market} 패턴 구독.
    """

    def __init__(
        self,
        price_alert_service: PriceAlertService,
        pubsub_redis: Redis,
    ) -> None:
        self._service = price_alert_service
        self._redis = pubsub_redis
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        """lifespan startup에서 호출. 구독 루프 시작."""
        self._task = asyncio.create_task(self._subscribe_loop())

    async def _subscribe_loop(self) -> None:
        """ch:ticker:*:* 패턴 구독, 메시지 수신 시 _on_ticker 호출."""
        pubsub = self._redis.pubsub()
        await pubsub.psubscribe("ch:ticker:*:*")
        try:
            async for message in pubsub.listen():
                if message["type"] != "pmessage":
                    continue
                try:
                    await self._on_ticker(message)
                except Exception:
                    logger.exception("PriceAlertMonitor error")
        finally:
            await pubsub.punsubscribe("ch:ticker:*:*")
            await pubsub.close()

    async def _on_ticker(self, message: dict) -> None:
        """ticker 메시지 파싱 → process_ticker 호출."""
        # channel: "ch:ticker:{exchange}:{market}"
        channel = message["channel"]
        parts = channel.split(":")  # ["ch", "ticker", exchange, market]
        exchange = parts[2]
        market = parts[3]
        data = json.loads(message["data"])
        price_str = data["data"].get("price") or data["data"].get("trade_price")
        if price_str is None:
            return
        current_price = Decimal(str(price_str))
        await self._service.process_ticker(exchange, market, current_price)

    async def stop(self) -> None:
        """lifespan shutdown에서 호출."""
        if self._task:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
```

### 10.2 `main.py` lifespan 연동

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # ... 기존 startup ...
    # PriceAlertMonitor 시작
    monitor = PriceAlertMonitor(price_alert_service, pubsub_redis)
    await monitor.start()
    yield
    # PriceAlertMonitor 중지
    await monitor.stop()
    # ... 기존 shutdown ...
```

---

## 11. DI 컨테이너 (`core/deps.py`)

```python
# ── 팩토리 함수 ──────────────────────────────────────────────────────────

def get_price_alert_repository(
    db: AsyncSession = Depends(get_db),
) -> "PriceAlertRepository":
    from app.repositories.price_alert_repository import PriceAlertRepository
    return PriceAlertRepository(db)

def get_notification_repository() -> "NotificationRepository":
    from app.repositories.notification_repository import NotificationRepository
    return NotificationRepository()

def get_fcm_service(
    settings: Settings = Depends(get_settings),
) -> "FCMService":
    from app.services.fcm_service import FCMService
    return FCMService(settings)

def get_notification_service(
    notification_repo: "NotificationRepository" = Depends(get_notification_repository),
    redis: Redis = Depends(get_redis),
    pubsub_redis: Redis = Depends(get_pubsub_redis),
) -> "NotificationService":
    from app.services.notification_service import NotificationService
    publisher = RedisPublisher(pubsub_redis)
    return NotificationService(notification_repo, redis, publisher)

def get_price_alert_service(
    alert_repo: "PriceAlertRepository" = Depends(get_price_alert_repository),
    coin_repo: "CoinRepository" = Depends(get_coin_repository),
    exchange_account_repo: "ExchangeAccountRepository" = Depends(get_exchange_account_repository),
    notification_service: "NotificationService" = Depends(get_notification_service),
    fcm_service: "FCMService" = Depends(get_fcm_service),
    client_repo: ClientRepository = Depends(get_client_repository),
    redis: Redis = Depends(get_redis),
) -> "PriceAlertService":
    from app.services.price_alert_service import PriceAlertService
    return PriceAlertService(
        alert_repo, coin_repo, exchange_account_repo,
        notification_service, fcm_service, client_repo, redis,
    )

# ── Type aliases ─────────────────────────────────────────────────────────

PriceAlertRepoDep = Annotated["PriceAlertRepository", Depends(get_price_alert_repository)]
NotificationRepoDep = Annotated["NotificationRepository", Depends(get_notification_repository)]
FCMServiceDep = Annotated["FCMService", Depends(get_fcm_service)]
PriceAlertServiceDep = Annotated["PriceAlertService", Depends(get_price_alert_service)]
NotificationServiceDep = Annotated["NotificationService", Depends(get_notification_service)]
```

---

## 12. 구현 파일 목록

### 신규 생성 파일

| # | 파일 | 역할 |
|---|------|------|
| 1 | `server/app/schemas/price_alert.py` | 가격 알림 요청/응답 스키마 |
| 2 | `server/app/schemas/notification.py` | 알림 기록 응답 스키마 |
| 3 | `server/app/repositories/price_alert_repository.py` | PriceAlert PG CRUD |
| 4 | `server/app/repositories/notification_repository.py` | Notification MongoDB CRUD |
| 5 | `server/app/services/price_alert_service.py` | 가격 알림 비즈니스 로직 + 트리거 |
| 6 | `server/app/services/notification_service.py` | 알림 기록 조회/읽음/미읽 카운트 |
| 7 | `server/app/services/fcm_service.py` | FCM 푸시 알림 스텁 |
| 8 | `server/app/api/v1/price_alerts.py` | 가격 알림 CRUD 라우터 |
| 9 | `server/app/api/v1/notifications.py` | 알림 기록 조회/읽음 라우터 |
| 10 | `server/app/ws/price_alert_monitor.py` | 실시간 시세 구독 → 알림 감지 |

### 수정 파일

| # | 파일 | 변경 내용 |
|---|------|-----------|
| 1 | `server/app/models/trading.py` | PriceAlert: `updated_at` + `ix_coin_active_untriggered` 인덱스 |
| 2 | `server/app/core/exceptions.py` | PriceAlertErrors, NotificationErrors 추가 |
| 3 | `server/app/core/deps.py` | DI 팩토리 6개 + 타입 별칭 5개 |
| 4 | `server/app/core/redis_keys.py` | RedisKey/RedisTTL 추가 (db-architect 완료) |
| 5 | `server/app/api/v1/__init__.py` | price_alerts + notifications 라우터 등록 |
| 6 | `server/app/main.py` | PriceAlertMonitor lifespan 연동 |
| 7 | `server/alembic/versions/007_v1_21_price_alert_extension.py` | updated_at + coin partial index (db-architect 완료) |

### 테스트 파일

| # | 파일 | 범위 | 예상 건수 |
|---|------|------|----------|
| 1 | `server/tests/unit/test_price_alert_service.py` | CRUD + 트리거 로직 | ~15건 |
| 2 | `server/tests/unit/test_notification_service.py` | 목록/읽음/카운트 | ~10건 |
| 3 | `server/tests/unit/test_price_alert_repository.py` | DB CRUD + mark_triggered | ~10건 |
| 4 | `server/tests/unit/test_notification_repository.py` | MongoDB CRUD | ~8건 |
| 5 | `server/tests/unit/test_price_alert_monitor.py` | ticker 파싱 + 조건 판단 | ~8건 |
| 6 | `server/tests/integration/test_price_alerts_api.py` | API 엔드포인트 | ~12건 |
| 7 | `server/tests/integration/test_notifications_api.py` | 알림 API | ~8건 |

---

## 13. 의존성 및 구현 순서

```
ST1: 스키마 + 에러 팩토리 + 모델 수정(updated_at + index) + migration 007
  │  (schemas/price_alert.py, schemas/notification.py, exceptions.py)
  ↓
ST2: 리포지토리 2개
  │  (price_alert_repository.py, notification_repository.py)
  ↓
ST3: NotificationService + DI 등록
  │  (notification_service.py — PriceAlertService가 의존)
  ↓
ST4: FCMService (스텁) + PriceAlertService + DI 등록
  │  (fcm_service.py, price_alert_service.py, deps.py)
  ↓
ST5: 가격 알림 API 라우터 + 알림 기록 API 라우터
  │  (price_alerts.py, notifications.py, __init__.py 등록)
  ↓
ST6: PriceAlertMonitor + lifespan 연동
  │  (ws/price_alert_monitor.py, main.py)
  ↓
ST7: 단위 테스트 (서비스/리포지토리/모니터)
  ↓
ST8: 통합 테스트 (API E2E)
  ↓
ST9: 코드 리뷰 + 최적화
```

### 서브태스크 매핑

| 원본 서브태스크 | 설명 | 구현 단계 |
|----------------|------|-----------|
| ST1 | 가격 알림 API 라우터 및 스키마 정의 | ST1 + ST5 |
| ST2 | 가격 알림 저장소 및 데이터 액세스 계층 | ST2 |
| ST3 | 가격 알림 비즈니스 로직 서비스 계층 | ST3 + ST4 |
| ST4 | 미읽 알림 카운트 Redis 캐싱 | ST3 (NotificationService) |
| ST5 | MongoDB Notification 문서 저장소 | ST2 (NotificationRepository) |
| ST6 | 실시간 시세 감시 백그라운드 작업 | ST6 (PriceAlertMonitor) |
| ST7 | FCM 푸시 알림 발송 통합 | ST4 (FCMService 스텁) |
| ST8 | 가격 알림 조회 API에 미읽 카운트 반영 | ST5 |
| ST9 | E2E 테스트 | ST8 |
| ST10 | 코드 리뷰 및 최적화 | ST9 |

---

## 14. 비기능 요구사항

### 성능

| 항목 | 목표 |
|------|------|
| 알림 CRUD API 응답 | < 100ms (p95) |
| 알림 목록 조회 (커서) | < 150ms (p95, 20건) |
| 미읽 카운트 조회 | < 10ms (Redis HIT) |
| 트리거 → WS 알림 지연 | < 2초 (이벤트 드리븐, ticker 수신 후) |
| process_ticker 단일 호출 | < 50ms (DB 조회 + 조건 비교) |

### 제한

| 항목 | 값 |
|------|-----|
| 사용자당 최대 활성 알림 수 | 50개 (서비스 레벨 검증) |
| 알림 기록 보존 기간 | 90일 (MongoDB TTL) |
| 트리거 중복 방지 Lock TTL | 30초 (Redis SETNX) |
| 가격 알림 미읽 카운트 TTL | 30일 (Redis) |

### 신뢰성

- **트리거 중복 방지**: DB UPDATE WHERE is_triggered=false (1차) + Redis SETNX (2차, 멀티 인스턴스)
- PriceAlertMonitor 예외 시 로깅 후 계속 실행 (단일 ticker 실패가 전체 중단하지 않음)
- MongoDB Notification TTL 인덱스로 자동 정리 (90일)
- 시세 데이터 없는 코인은 스킵 (에러 발생 안 함)
- FCM 실패는 fire-and-forget (주요 흐름 차단 안 함)

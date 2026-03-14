# v1-13 코인 마스터 및 관심 코인 관리 API — 설계서

> **작성**: project-architect (시스템 아키텍처/흐름/구현계획), code-architect (코드 구조/스키마/인터페이스 설계), db-architect (쿼리/인덱스 최적화)
> **대상 태스크**: v1-13 — 코인 검색, 코인 상세, 관심 코인 CRUD, 정렬, 실시간 시세 통합
> **현재 상태**: 구현 완료 (2026-03-14)

---

## 1. 개요

거래소별 코인 목록 조회/검색, 관심 코인 CRUD, 정렬 순서 변경, 실시간 시세 통합 API를 구현한다. 기존 `Coin`, `WatchlistCoin` 모델(`models/coin.py`)을 활용하며, Redis 캐시(`RedisKey.ticker()`)에서 실시간 시세를 병합하여 응답한다.

**의존성**: v1-11 (거래소 계정 관리 API), v1-12 (WebSocket 실시간 시세 허브)

**핵심 요구사항**:
- 코인 검색: 심볼/한글명/영문명 기반, 거래소 필터, GIN trgm 인덱스 활용
- 관심 코인: 사용자별 CRUD + 거래소 계정 연동
- 정렬: 드래그 앤 드롭 방식 reorder (일괄 업데이트)
- 실시간 시세: Redis 캐시에서 ticker 병합 (graceful degradation)
- 초기 데이터: Upbit/CoinOne 코인 seed 스크립트

---

## 2. 전체 아키텍처

### 2.1 데이터 흐름

```
[코인 검색]
  Flutter App ──GET /api/v1/coins?q=BTC&exchange=upbit──▶ FastAPI Server
                                                              │
                                                              ▼
                                                    ┌──────────────────┐
                                                    │ 1. Coin 테이블     │
                                                    │    검색 (trgm)    │
                                                    │ 2. Redis 캐시     │
                                                    │    ticker 조회    │
                                                    │ 3. 시세 병합 응답  │
                                                    └──────────────────┘

[관심 코인 목록]
  Flutter App ──GET /api/v1/watchlist──▶ FastAPI Server
                                              │
                                              ▼
                                    ┌──────────────────┐
                                    │ 1. WatchlistCoin  │
                                    │    + JOIN Coin    │
                                    │ 2. Redis ticker   │
                                    │    일괄 조회       │
                                    │ 3. 시세 병합 응답  │
                                    └──────────────────┘

[관심 코인 WS 구독]
  Flutter App ──WS subscribe ticker──▶ WSHub
                                          │
                                          ▼
                                    Exchange WS → Redis Pub/Sub → WS Broadcast
                                                      │
                                                      ▼
                                               Redis SETEX (스냅샷)
                                               → REST API에서 읽기
```

### 2.2 API 흐름도

```
[검색] GET /api/v1/coins?q={keyword}&exchange={exchange}&page=1&size=20
  (인증 선택) → Coin 테이블 검색 (GIN trgm) → Redis ticker 병합 → 페이지네이션 응답

[상세] GET /api/v1/coins/{coin_id}
  (인증 선택) → Coin 조회 → Redis ticker 병합 → 응답

[관심 목록] GET /api/v1/watchlist?exchange_account_id={id}
  JWT 인증 → WatchlistCoin + Coin JOIN → Redis ticker 일괄 조회 → sort_order 정렬 응답

[관심 추가] POST /api/v1/watchlist
  JWT 인증 → coin_id 존재 확인 → exchange_account 소유권 확인 → ON CONFLICT 중복 체크 → DB INSERT

[관심 제거] DELETE /api/v1/watchlist/{watchlist_id}
  JWT 인증 → 소유권 확인 → DB DELETE

[정렬 변경] PUT /api/v1/watchlist/reorder
  JWT 인증 → 소유권 일괄 확인 → CASE WHEN 배치 UPDATE → 응답
```

---

## 3. API 엔드포인트 상세

### 3.1 코인 검색 — `GET /api/v1/coins`

| 항목 | 값 |
|------|-----|
| 인증 | 선택 (CurrentUserOptional) — 코인 마스터는 공개 데이터 |
| 태그 | coins |

**쿼리 파라미터**:
| 파라미터 | 타입 | 필수 | 제약 | 설명 |
|----------|------|------|------|------|
| q | string | N | max_length=100 | 검색 키워드 (심볼/한글명/영문명, trgm 검색) |
| exchange | string | N | ExchangeType enum | 거래소 필터 (upbit, coinone). 잘못된 값 → 422 |
| is_active | bool | N | - | 활성 상태 필터 (기본 true) |
| page | int | N | ge=1 | 페이지 번호 (기본 1) |
| size | int | N | ge=1, le=100 | 페이지 크기 (기본 20) |

**응답 스키마** — `ApiResponse[PaginatedCoins]`:
```python
class CoinResponse(BaseModel):
    id: UUID
    symbol: str                        # "BTC"
    name_ko: str | None                # "비트코인"
    name_en: str | None                # "Bitcoin"
    exchange_type: str                 # "upbit"
    market_code: str                   # "KRW-BTC"
    is_active: bool

    # 실시간 시세 (Redis ticker 스냅샷, 없으면 None — graceful degradation)
    current_price: Decimal | None = None
    change_rate_24h: Decimal | None = None   # 전일 대비 변동률
    volume_24h: Decimal | None = None        # 24시간 거래량
    open_price: Decimal | None = None
    high_price: Decimal | None = None
    low_price: Decimal | None = None
    price_updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class PaginatedCoins(BaseModel):
    items: list[CoinResponse]
    total: int
    page: int
    size: int
    pages: int   # ceil(total / size)
```

> **설계 결정: flat ticker 필드 vs nested TickerSummary**
> code-architect 제안대로 flat 필드(`current_price`, `change_rate_24h`, ...) 채택.
> 이유: 클라이언트에서 `coin.ticker?.currentPrice` 대신 `coin.currentPrice`로 직접 접근 가능. Decimal 사용으로 부동소수점 정밀도 보장.

### 3.2 코인 상세 — `GET /api/v1/coins/{coin_id}`

| 항목 | 값 |
|------|-----|
| 인증 | 선택 (CurrentUserOptional) |
| 태그 | coins |

**응답 스키마** — `ApiResponse[CoinDetailResponse]`:
```python
class CoinDetailResponse(CoinResponse):
    """CoinResponse + 추가 상세 정보."""
    created_at: datetime
    updated_at: datetime
```

### 3.3 관심 코인 목록 — `GET /api/v1/watchlist`

| 항목 | 값 |
|------|-----|
| 인증 | 필수 (CurrentUser) |
| 태그 | watchlist |

**쿼리 파라미터**:
| 파라미터 | 타입 | 필수 | 설명 |
|----------|------|------|------|
| exchange_account_id | uuid | N | 거래소 계정 필터 (없으면 전체) |

**응답 스키마** — `ApiResponse[list[WatchlistCoinResponse]]`:
```python
class WatchlistCoinResponse(BaseModel):
    id: UUID                       # watchlist_coin.id
    coin_id: UUID
    coin: CoinResponse             # JOIN 포함 (실시간 시세 포함)
    exchange_account_id: UUID | None
    sort_order: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
```

### 3.4 관심 코인 추가 — `POST /api/v1/watchlist`

| 항목 | 값 |
|------|-----|
| 인증 | 필수 (CurrentUser) |
| 태그 | watchlist |

**요청 스키마**:
```python
class AddWatchlistRequest(BaseModel):
    coin_id: UUID
    exchange_account_id: UUID | None = None
```

**응답** — `ApiResponse[WatchlistCoinResponse]` (201)

**로직**:
1. coin_id 존재 확인 → 없으면 `CoinErrors.not_found()` (404)
2. exchange_account_id 제공 시 → 소유권 확인 → `CoinErrors.exchange_account_mismatch()` (403)
3. sort_order: 현재 사용자의 max(sort_order) + 1 자동 배정
4. ON CONFLICT DO NOTHING → rowcount == 0 → `CoinErrors.watchlist_duplicate()` (409)
5. selectinload(coin) 후 응답

### 3.5 관심 코인 제거 — `DELETE /api/v1/watchlist/{watchlist_id}`

| 항목 | 값 |
|------|-----|
| 인증 | 필수 (CurrentUser) |
| 태그 | watchlist |

**응답** — `ApiResponse[dict]` (200, `{"message": "관심 코인이 제거되었습니다."}`)

**로직**:
1. watchlist_id로 조회
2. user_id 소유권 확인 → 없거나 타인 소유 → `CoinErrors.watchlist_not_found()` (404)
3. DB DELETE

### 3.6 관심 코인 정렬 순서 변경 — `PUT /api/v1/watchlist/reorder`

| 항목 | 값 |
|------|-----|
| 인증 | 필수 (CurrentUser) |
| 태그 | watchlist |

> **라우터 등록 순서 주의**: `PUT /watchlist/reorder`를 `DELETE /watchlist/{watchlist_id}`보다 먼저 등록. "reorder"가 `{watchlist_id}`로 캡처되는 문제 방지.

**요청 스키마**:
```python
class ReorderItem(BaseModel):
    id: UUID                    # watchlist_coin.id
    sort_order: int = Field(ge=0)  # 새 순서값 (0-based, 클라이언트 결정)

class ReorderWatchlistRequest(BaseModel):
    items: list[ReorderItem] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_unique_sort_orders(self) -> "ReorderWatchlistRequest":
        orders = [item.sort_order for item in self.items]
        if len(orders) != len(set(orders)):
            raise ValueError("sort_order values must be unique")
        return self
```

**응답** — `ApiResponse[list[WatchlistCoinResponse]]`

**로직**:
1. 모든 id가 현재 사용자 소유인지 일괄 확인 → `CoinErrors.watchlist_access_denied()` (403)
2. CASE WHEN 배치 UPDATE (단일 쿼리)
3. 업데이트된 목록 반환

---

## 4. 에러 정의

`core/exceptions.py`에 `CoinErrors` 클래스 추가:

```python
class CoinErrors:
    @staticmethod
    def not_found() -> AppError:
        return AppError("COIN_NOT_FOUND", "코인을 찾을 수 없습니다.", 404)

    @staticmethod
    def watchlist_not_found() -> AppError:
        return AppError("WATCHLIST_NOT_FOUND", "관심 코인을 찾을 수 없습니다.", 404)

    @staticmethod
    def watchlist_duplicate() -> AppError:
        return AppError("WATCHLIST_DUPLICATE", "이미 관심 코인에 추가되어 있습니다.", 409)

    @staticmethod
    def watchlist_access_denied() -> AppError:
        return AppError("WATCHLIST_ACCESS_DENIED", "접근 권한이 없습니다.", 403)

    @staticmethod
    def watchlist_reorder_invalid() -> AppError:
        return AppError("WATCHLIST_REORDER_INVALID", "정렬 변경 대상이 올바르지 않습니다.", 400)

    @staticmethod
    def exchange_account_mismatch() -> AppError:
        return AppError("EXCHANGE_ACCOUNT_MISMATCH", "본인 소유 거래소 계정이 아닙니다.", 403)
```

---

## 5. 파일 구조

### 5.1 신규 생성 파일

| 파일 | 설명 |
|------|------|
| `server/app/schemas/coin.py` | Coin/Watchlist 요청/응답 스키마, PaginatedCoins |
| `server/app/repositories/coin_repository.py` | Coin 검색/조회/upsert DB 접근 |
| `server/app/repositories/watchlist_repository.py` | WatchlistCoin CRUD DB 접근 |
| `server/app/services/coin_service.py` | 코인 검색/상세 + 관심 코인 CRUD + 시세 병합 (통합 서비스) |
| `server/app/api/v1/coins.py` | 코인 검색/상세 API 엔드포인트 |
| `server/app/api/v1/watchlist.py` | 관심 코인 CRUD API 엔드포인트 |
| `server/scripts/seed/seed_coins.py` | Upbit/CoinOne 초기 코인 데이터 로드 스크립트 |
| `server/alembic/versions/005_v1_13_coin_search_indexes.py` | name_ko/name_en trgm + partial + 복합 인덱스 마이그레이션 |
| `server/tests/unit/test_coin_service.py` | CoinService 단위 테스트 |
| `server/tests/unit/test_coin_repository.py` | CoinRepository 단위 테스트 |
| `server/tests/unit/test_watchlist_repository.py` | WatchlistRepository 단위 테스트 |
| `server/tests/integration/test_coins_api.py` | 코인 API 통합 테스트 |
| `server/tests/integration/test_watchlist_api.py` | 관심 코인 API 통합 테스트 |

### 5.2 수정 파일

| 파일 | 변경 내용 |
|------|----------|
| `server/app/api/v1/__init__.py` | coins, watchlist 라우터 등록 |
| `server/app/core/deps.py` | CoinRepository, WatchlistRepository, CoinService DI 팩토리 + 타입 별칭 |
| `server/app/core/exceptions.py` | CoinErrors 클래스 추가 |
| `server/app/ws/bridge.py` | `_on_ticker()`에 Redis SETEX 스냅샷 추가 (ST8) |

> **설계 결정: 서비스 통합 vs 분리**
> code-architect 제안대로 `CoinService` 단일 서비스로 통합 (coin 검색/조회 + watchlist CRUD).
> 이유: WatchlistService가 coin_repo에 의존하므로 cross-service 복잡도 증가. 단일 서비스가 DI 체인 단순화.
> Repository는 `CoinRepository` + `WatchlistRepository`로 분리 유지 (SRP).

---

## 6. DI (의존성 주입) 설계

### 6.1 DI 팩토리 함수 (`core/deps.py` 추가)

```python
# ── Coin ──────────────────────────────────────────────────────────────────────

def get_coin_repository(db: AsyncSession = Depends(get_db)) -> "CoinRepository":
    from app.repositories.coin_repository import CoinRepository
    return CoinRepository(db)

def get_watchlist_repository(db: AsyncSession = Depends(get_db)) -> "WatchlistRepository":
    from app.repositories.watchlist_repository import WatchlistRepository
    return WatchlistRepository(db)

def get_coin_service(
    coin_repo: "CoinRepository" = Depends(get_coin_repository),
    watchlist_repo: "WatchlistRepository" = Depends(get_watchlist_repository),
    exchange_account_repo: "ExchangeAccountRepository" = Depends(get_exchange_account_repository),
    redis: Redis = Depends(get_redis),
) -> "CoinService":
    from app.services.coin_service import CoinService
    return CoinService(coin_repo, watchlist_repo, exchange_account_repo, redis)

# ── Type aliases ─────────────────────────────────────────────────────────────
CoinRepoDep = Annotated["CoinRepository", Depends(get_coin_repository)]
WatchlistRepoDep = Annotated["WatchlistRepository", Depends(get_watchlist_repository)]
CoinServiceDep = Annotated["CoinService", Depends(get_coin_service)]
```

> **DI 결정**: `CoinService`에 `Redis` 직접 주입 (MarketCacheService DI 미사용).
> 이유: `MarketCacheService`는 set/get 래퍼이고, ticker 조회만 필요하므로 Redis pipeline 직접 사용이 더 효율적 (pipeline 일괄 조회).
> `ExchangeAccountRepository` 주입: watchlist 추가 시 exchange_account 소유권 검증용.

### 6.2 라우터 등록 (`api/v1/__init__.py`)

```python
from app.api.v1.coins import router as coins_router
from app.api.v1.watchlist import router as watchlist_router

router.include_router(coins_router, prefix="/coins", tags=["coins"])
router.include_router(watchlist_router, prefix="/watchlist", tags=["watchlist"])
```

---

## 7. 서비스 계층 상세

### 7.1 CoinService (통합 서비스)

```python
class CoinService:
    def __init__(
        self,
        coin_repo: CoinRepository,
        watchlist_repo: WatchlistRepository,
        exchange_account_repo: ExchangeAccountRepository,
        redis: Redis,
    ) -> None:
        self._coin_repo = coin_repo
        self._watchlist_repo = watchlist_repo
        self._exchange_account_repo = exchange_account_repo
        self._redis = redis

    # ── 코인 검색/조회 ────────────────────────────────────────────────

    async def search_coins(
        self, query: str | None, exchange_type: str | None,
        page: int, size: int,
    ) -> PaginatedCoins:
        # 1. coin_repo.search(query, exchange_type, page, size) → (coins, total)
        # 2. _enrich_with_prices(coins) → Redis pipeline
        # 3. PaginatedCoins 반환

    async def get_coin(self, coin_id: UUID) -> CoinDetailResponse:
        # 1. coin_repo.get_by_id(coin_id) → 없으면 CoinErrors.not_found()
        # 2. _get_ticker_snapshot() → price 필드 채우기
        # 3. CoinDetailResponse 반환

    # ── 관심 코인 CRUD ────────────────────────────────────────────────

    async def get_watchlist(
        self, user_id: UUID, exchange_account_id: UUID | None,
    ) -> list[WatchlistCoinResponse]:
        # 1. watchlist_repo.get_by_user(user_id, exchange_account_id)
        #    → selectinload(coin) 포함
        # 2. 코인 목록 추출 → _enrich_with_prices()
        # 3. WatchlistCoinResponse 조립

    async def add_to_watchlist(
        self, user_id: UUID, body: AddWatchlistRequest,
    ) -> WatchlistCoinResponse:
        # 1. coin_repo.get_by_id(body.coin_id) → 없으면 not_found()
        # 2. body.exchange_account_id 제공 시:
        #    exchange_account_repo.get_by_id() → 없거나 user_id 불일치 → exchange_account_mismatch()
        # 3. sort_order = watchlist_repo.get_max_sort_order(user_id) + 1
        # 4. watchlist_repo.create_or_conflict(...)
        #    → ON CONFLICT DO NOTHING → rowcount 0 → watchlist_duplicate()
        # 5. selectinload(coin) 후 응답

    async def remove_from_watchlist(
        self, user_id: UUID, watchlist_id: UUID,
    ) -> None:
        # 1. watchlist_repo.get_by_user_and_id(user_id, watchlist_id)
        #    → 없으면 watchlist_not_found()
        # 2. watchlist_repo.delete(watchlist_id)

    async def reorder_watchlist(
        self, user_id: UUID, items: list[ReorderItem],
    ) -> list[WatchlistCoinResponse]:
        # 1. watchlist_repo.get_by_user(user_id) → 유효 ID 집합 계산
        # 2. 요청 ID 중 미소유 ID 존재 → watchlist_access_denied()
        # 3. watchlist_repo.bulk_update_sort_order(user_id, items)
        # 4. get_watchlist(user_id) 반환

    # ── Private: 시세 병합 ────────────────────────────────────────────

    async def _enrich_with_prices(self, coins: list[Coin]) -> list[CoinResponse]:
        """Redis pipeline으로 ticker 일괄 조회 → CoinResponse 병합.
        Redis 연결 실패 시 price=None으로 graceful degradation.
        """
        keys = [RedisKey.ticker(c.exchange_type, c.market_code) for c in coins]
        pipe = self._redis.pipeline(transaction=False)
        for key in keys:
            pipe.get(key)
        try:
            results = await pipe.execute()
        except Exception:
            results = [None] * len(coins)

        responses = []
        for coin, raw in zip(coins, results):
            ticker = json.loads(raw) if raw else None
            responses.append(self._build_coin_response(coin, ticker))
        return responses

    async def _get_ticker_snapshot(
        self, exchange_type: str, market_code: str,
    ) -> dict | None:
        """단건 ticker 조회."""
        try:
            raw = await self._redis.get(RedisKey.ticker(exchange_type, market_code))
            return json.loads(raw) if raw else None
        except Exception:
            return None

    @staticmethod
    def _build_coin_response(coin: Coin, ticker: dict | None) -> CoinResponse:
        return CoinResponse(
            id=coin.id,
            symbol=coin.symbol,
            name_ko=coin.name_ko,
            name_en=coin.name_en,
            exchange_type=coin.exchange_type,
            market_code=coin.market_code,
            is_active=coin.is_active,
            current_price=ticker.get("current_price") if ticker else None,
            change_rate_24h=ticker.get("change_rate_24h") if ticker else None,
            volume_24h=ticker.get("volume_24h") if ticker else None,
            open_price=ticker.get("open_price") if ticker else None,
            high_price=ticker.get("high_price") if ticker else None,
            low_price=ticker.get("low_price") if ticker else None,
            price_updated_at=ticker.get("price_updated_at") if ticker else None,
        )
```

---

## 8. Repository 계층 상세

### 8.1 CoinRepository

```python
class CoinRepository:
    def __init__(self, db: AsyncSession) -> None: ...

    async def get_by_id(self, coin_id: UUID) -> Coin | None: ...

    async def get_by_ids(self, coin_ids: list[UUID]) -> list[Coin]: ...

    async def search(
        self, query: str | None, exchange_type: str | None,
        page: int, size: int,
    ) -> tuple[list[Coin], int]:
        """GIN trgm 인덱스 활용 검색 + COUNT 동시 반환.

        q가 있으면: symbol ILIKE '%{q}%' OR name_ko ILIKE '%{q}%' OR name_en ILIKE '%{q}%'
        → 각 GIN trgm 인덱스 Bitmap Scan → Bitmap OR 머지
        exchange 필터: exchange_type = ?
        is_active = true (항상, partial index 활용)
        ORDER BY symbol ASC
        OFFSET (page-1)*size LIMIT size
        Returns: (coins, total_count)
        """

    async def upsert(
        self, *, symbol: str, exchange_type: str, market_code: str,
        name_ko: str | None = None, name_en: str | None = None,
    ) -> Coin:
        """INSERT ... ON CONFLICT (exchange_type, market_code) DO UPDATE.
        seed_coins.py에서 사용.
        """
```

### 8.2 WatchlistRepository

```python
class WatchlistRepository:
    def __init__(self, db: AsyncSession) -> None: ...

    async def get_by_id(self, watchlist_id: UUID) -> WatchlistCoin | None:
        """selectinload(WatchlistCoin.coin) 포함."""

    async def get_by_user_and_id(
        self, user_id: UUID, watchlist_id: UUID,
    ) -> WatchlistCoin | None:
        """소유권 검증용. selectinload(coin) 포함."""

    async def get_by_ids(self, ids: list[UUID]) -> list[WatchlistCoin]: ...

    async def get_by_user(
        self, user_id: UUID,
        exchange_account_id: UUID | None = None,
    ) -> list[WatchlistCoin]:
        """selectinload(WatchlistCoin.coin) 포함, ORDER BY sort_order ASC.

        exchange_account_id 제공 시: 해당 계정 필터.
        미제공 시: 사용자 전체.
        """

    async def get_max_sort_order(self, user_id: UUID) -> int:
        """SELECT COALESCE(MAX(sort_order), -1). +1해서 신규 순서 결정."""

    async def create_or_conflict(
        self, user_id: UUID, coin_id: UUID,
        exchange_account_id: UUID | None, sort_order: int,
    ) -> WatchlistCoin | None:
        """ON CONFLICT DO NOTHING — rowcount 0이면 중복. 성공 시 WatchlistCoin 반환."""

    async def delete(self, watchlist_id: UUID) -> None: ...

    async def bulk_update_sort_order(
        self, user_id: UUID, items: list[tuple[UUID, int]],
    ) -> None:
        """SQLAlchemy case() + update() — CASE WHEN 배치 단일 쿼리.

        UPDATE watchlist_coins
        SET sort_order = CASE id WHEN :id1 THEN :order1 WHEN :id2 THEN :order2 ... END
        WHERE id = ANY(:ids) AND user_id = :user_id
        """
```

---

## 9. DB 쿼리 및 인덱스 전략

### 9.1 추가 인덱스 (새 Migration 필요)

> db-architect 분석 결과, 기존 인덱스만으로는 name_ko/name_en 검색 및 exchange_account_id 필터에 비효율 발생. 아래 4개 인덱스 추가 권장.

**마이그레이션 파일**: `server/alembic/versions/005_v1_13_coin_search_indexes.py`

```sql
-- ① name_ko GIN trigram (한국어 검색)
CREATE INDEX ix_coins_name_ko_trgm ON coins USING gin (name_ko gin_trgm_ops);

-- ② name_en GIN trigram (영문명 검색)
CREATE INDEX ix_coins_name_en_trgm ON coins USING gin (name_en gin_trgm_ops);

-- ③ exchange_type + is_active Partial (코인 목록 필터 최적화)
CREATE INDEX ix_coins_exchange_active
  ON coins (exchange_type) WHERE is_active = true;

-- ④ watchlist exchange_account_id 포함 복합 (계정별 필터 + 정렬)
CREATE INDEX ix_watchlist_user_account_sort
  ON watchlist_coins (user_id, exchange_account_id, sort_order);
```

**인덱스 추가 근거**:
- ①②: 사용자가 "비트코인", "이더리움" 등 한국어명 또는 "Bitcoin" 등 영문명으로 검색하는 케이스가 실사용에서 빈번. 코인 수 200~300개 수준으로 인덱스 유지 비용 낮음.
- ③: 코인 검색에 항상 `is_active = true` 조건 포함 → partial index로 스캔 범위를 활성 코인으로 제한.
- ④: exchange_account_id 필터 시 기존 covering index 미활용 → 복합 인덱스로 커버. PG B-tree는 NULL 인덱싱 지원하므로 `IS NULL` 케이스도 처리.

### 9.2 코인 검색 쿼리

```sql
-- q="BTC", exchange="upbit"
SELECT * FROM coins
WHERE exchange_type = 'upbit'
  AND is_active = true
  AND (
    symbol ILIKE '%BTC%'         -- ix_coins_symbol_trgm (GIN) 활용
    OR name_ko ILIKE '%비트%'     -- ix_coins_name_ko_trgm (GIN) 활용
    OR name_en ILIKE '%bitcoin%' -- ix_coins_name_en_trgm (GIN) 활용
  )
ORDER BY symbol ASC
OFFSET 0 LIMIT 20;
```

**인덱스 활용**:
- OR 조건 + GIN: 각 인덱스 Bitmap Scan → Bitmap OR 머지 → 효율적
- `ix_coins_exchange_active`: exchange_type + is_active 필터 최적화
- name_ko nullable이므로 `ILIKE '%비트%'` → NULL 행은 자동 제외

### 9.3 관심 코인 목록 쿼리

```sql
-- user_id=?, exchange_account_id=?
SELECT wc.*, c.symbol, c.name_ko, c.name_en, c.exchange_type, c.market_code
FROM watchlist_coins wc
JOIN coins c ON c.id = wc.coin_id
WHERE wc.user_id = :user_id
  AND wc.exchange_account_id = :ea_id
ORDER BY wc.sort_order ASC;
```

**인덱스 활용**:
- `ix_watchlist_user_account_sort` (④): user_id + exchange_account_id + sort_order 복합 → WHERE + ORDER BY 완전 커버
- coins PK lookup: 유저 관심 코인 10~50개 수준 → N번 PK 조회 충분히 빠름

**exchange_account_id IS NULL 케이스**:
```sql
WHERE wc.user_id = ? AND wc.exchange_account_id IS NULL
```
→ ④ 인덱스 활용 가능 (PG B-tree NULL 인덱싱 지원)

### 9.4 정렬 일괄 업데이트

```sql
-- CASE WHEN 단일 쿼리 (권장)
UPDATE watchlist_coins
SET sort_order = CASE id
    WHEN 'uuid1' THEN 0
    WHEN 'uuid2' THEN 1
    WHEN 'uuid3' THEN 2
END
WHERE id = ANY(ARRAY['uuid1','uuid2','uuid3']) AND user_id = :user_id;
```

**SQLAlchemy `case()` 구현**:
```python
from sqlalchemy import case, update

stmt = (
    update(WatchlistCoin)
    .where(
        WatchlistCoin.id.in_(id_list),
        WatchlistCoin.user_id == user_id,
    )
    .values(
        sort_order=case(
            {id_: order for id_, order in zip(id_list, order_list)},
            value=WatchlistCoin.id,
        )
    )
)
await db.execute(stmt)
```

CASE WHEN 배치 방식 선택 이유: 단일 쿼리로 완결, `bulk_update_mappings()`는 내부적으로 개별 UPDATE executemany이므로 CASE WHEN 단일 쿼리가 우위.

### 9.5 중복 방지 — ON CONFLICT DO NOTHING 방식

> db-architect 권장: 서비스 레벨 SELECT → INSERT 사이 race condition 존재하므로 DB 레벨 보장.

```python
from sqlalchemy.dialects.postgresql import insert as pg_insert

stmt = pg_insert(WatchlistCoin).values(
    user_id=user_id,
    coin_id=coin_id,
    exchange_account_id=exchange_account_id,
    sort_order=next_sort_order,
).on_conflict_do_nothing(
    constraint="uq_watchlist_user_coin_account"
)
result = await db.execute(stmt)
if result.rowcount == 0:
    raise CoinErrors.watchlist_duplicate()
```

ON CONFLICT 방식이 IntegrityError 파싱 대비 명시적이고 안전.

---

## 10. 시세 병합 전략

### 10.1 Redis Pipeline 일괄 조회

```python
async def _enrich_with_prices(self, coins: list[Coin]) -> list[CoinResponse]:
    """Redis pipeline으로 ticker 일괄 조회 → CoinResponse 병합."""
    keys = [RedisKey.ticker(c.exchange_type, c.market_code) for c in coins]

    pipe = self._redis.pipeline(transaction=False)
    for key in keys:
        pipe.get(key)

    try:
        results = await pipe.execute()
    except Exception:
        # Redis 연결 실패 → price=None으로 graceful degradation
        results = [None] * len(coins)

    responses = []
    for coin, raw in zip(coins, results):
        ticker = json.loads(raw) if raw else None
        responses.append(self._build_coin_response(coin, ticker))
    return responses
```

### 10.2 Ticker 스냅샷 저장 (bridge.py 수정 — ST8)

> code-architect 지적: 현재 bridge.py는 Pub/Sub 발행만 수행. REST 엔드포인트에서 ticker를 읽으려면 Redis에 SETEX 스냅샷 저장 필요.

```python
# ws/bridge.py — _on_ticker() 수정
async def _on_ticker(self, ticker: Ticker) -> None:
    data = {
        "current_price": float(ticker.price),
        "open_price": float(ticker.open_price),
        "high_price": float(ticker.high_price),
        "low_price": float(ticker.low_price),
        "volume_24h": float(ticker.volume),
        "change_rate_24h": float(ticker.change_rate),
        "price_updated_at": ticker.timestamp.isoformat(),
    }
    # 기존: Pub/Sub 발행 (WS 클라이언트용)
    await self._publisher.publish_ticker(ticker.exchange.value, ticker.market, data)
    # 추가: REST 엔드포인트용 스냅샷 저장
    await self._redis.setex(
        RedisKey.ticker(ticker.exchange.value, ticker.market),
        RedisTTL.TICKER,  # 10초
        json.dumps(data),
    )
```

> `RedisKey.ticker()`, `RedisTTL.TICKER = 10`은 이미 `redis_keys.py`에 정의됨.
> CoinService._enrich_with_prices()에서 이 키를 읽어 가격 enrichment 수행.

---

## 11. 코인 초기 데이터 로드 (Seed)

### 11.1 스크립트 위치

`server/scripts/seed/seed_coins.py` (Alembic과 분리 — 네트워크 의존성 때문)

### 11.2 동작 방식

1. Upbit `GET https://api.upbit.com/v1/market/all?isDetails=true` → 코인 목록 조회
   - 파싱: `market.split("-")[1]` → symbol, `market` → market_code, `korean_name` → name_ko, `english_name` → name_en
2. CoinOne `GET https://api.coinone.co.kr/public/v2/markets/all` → 코인 목록 조회
3. 정규화: exchange_type, symbol, market_code, name_ko, name_en 추출
4. DB upsert (SQLAlchemy `pg_insert().on_conflict_do_update()`):
   ```python
   stmt = pg_insert(Coin).values(rows).on_conflict_do_update(
       constraint="uq_coin_exchange_market",
       set_={
           "symbol": pg_insert(Coin).excluded.symbol,
           "name_ko": pg_insert(Coin).excluded.name_ko,
           "name_en": pg_insert(Coin).excluded.name_en,
           "is_active": pg_insert(Coin).excluded.is_active,
           "updated_at": func.now(),
       }
   )
   ```
5. 비활성 처리: 거래소에서 삭제된 코인은 `is_active = false`
6. 재실행 멱등성 보장 (ON CONFLICT 기반)

### 11.3 실행 방법

```bash
# 직접 실행
cd server && python -m scripts.seed.seed_coins

# Docker
docker compose exec server python -m scripts.seed.seed_coins

# 특정 거래소만
python -m scripts.seed.seed_coins --exchange upbit

# Makefile
make seed
```

### 11.4 정적 fallback

거래소 API 호출 실패 시 하드코딩된 주요 코인 15개로 fallback:
- BTC, ETH, XRP, SOL, DOGE, ADA, AVAX, DOT, MATIC, LINK, ATOM, ETC, BCH, TRX, EOS

### 11.5 향후 확장

주기적 코인 목록 갱신은 Celery task로 연계 가능 (v2 범위).

---

## 12. WebSocket 실시간 시세 통합 (ST8)

### 12.1 기존 WS 인프라 활용

관심 코인의 실시간 시세는 기존 WSHub + PubSubSubscriber 인프라를 그대로 활용:

1. 클라이언트가 `GET /api/v1/watchlist`로 관심 코인 목록 조회
2. 응답의 `exchange_type` + `market_code`로 WS subscribe 요청:
   ```json
   {"action": "subscribe", "channel": "ticker", "exchange": "upbit", "market": "KRW-BTC"}
   ```
3. ExchangeStreamBridge → 거래소 WS → Redis Pub/Sub → WSHub broadcast
4. 동시에 Redis SETEX로 스냅샷 저장 → REST API에서 읽기 (섹션 10.2)

### 12.2 서버 측 추가 구현

| 항목 | 변경 |
|------|------|
| `ws/bridge.py` | `_on_ticker()`에 SETEX 추가 (REST용 스냅샷) |
| API 응답 | `exchange_type` + `market_code` 포함으로 클라이언트 WS 구독 지원 |

기존 v1-12 인프라가 완비되어 있으므로 새로운 WS 핸들러/채널 추가는 불필요.

---

## 13. 구현 순서 및 의존성

```
ST1: 스캐폴딩
 │   schemas/coin.py, repositories/*.py, services/coin_service.py, api/v1/coins.py, api/v1/watchlist.py
 │   + deps.py DI + __init__.py 라우터 등록 + CoinErrors + Migration 005
 │
 ├── ST2: CoinRepository + CoinService.search_coins() + GET /api/v1/coins
 │    │
 │    └── ST3: CoinService.get_coin() + GET /api/v1/coins/{coin_id}
 │         │
 │         └── ST4: WatchlistRepository + CoinService.get_watchlist() + GET /api/v1/watchlist
 │              │
 │              ├── ST5: CoinService.add_to_watchlist() + POST /api/v1/watchlist
 │              │
 │              ├── ST6: CoinService.remove_from_watchlist() + DELETE /api/v1/watchlist/{id}
 │              │
 │              └── ST7: CoinService.reorder_watchlist() + PUT /api/v1/watchlist/reorder
 │
 ├── ST8: seed_coins.py (초기 데이터 로드)
 │
 └── ST9: bridge.py SETEX 추가 (WS 실시간 시세 → REST 스냅샷)
      │
      └── ST10: 통합 테스트 + 코드 리뷰
```

---

## 14. 테스트 전략

### 14.1 단위 테스트 (예상 30건)

| 대상 | 테스트 항목 |
|------|------------|
| CoinRepository | search (q/exchange/is_active 조합), get_by_id, upsert |
| WatchlistRepository | get_by_user, create_or_conflict (정상/중복), delete, get_max_sort_order, bulk_update_sort_order |
| CoinService | search_coins + ticker 병합, get_coin, ticker 캐시 미스 graceful degradation |
| CoinService (watchlist) | get_watchlist, add (정상/중복/coin_not_found/account_mismatch), remove (정상/not_found), reorder (정상/access_denied) |

### 14.2 통합 테스트 (예상 15건)

| 엔드포인트 | 테스트 항목 |
|-----------|------------|
| GET /coins | 검색 (q, exchange 필터), 페이지네이션, 빈 결과, is_active 필터 |
| GET /coins/{id} | 정상 조회, 404 |
| GET /watchlist | 인증 필수 (401), 목록 조회, exchange_account_id 필터 |
| POST /watchlist | 정상 추가 (201), 중복 409, coin_not_found 404, account_mismatch 403 |
| DELETE /watchlist/{id} | 정상 제거, not_found 404 |
| PUT /watchlist/reorder | 정상 reorder, access_denied 403, sort_order 중복 422 |

---

## 15. 설계 결정 요약 (ADR)

### ADR-13-1: 서비스 통합 vs 분리

| 항목 | 결정 |
|------|------|
| 선택 | 단일 `CoinService` (coin 검색 + watchlist CRUD 통합) |
| 대안 | `CoinService` + `WatchlistService` 분리 |
| 이유 | Watchlist가 CoinRepository에 의존, 분리 시 cross-service DI 복잡도 증가. Repository만 분리하여 SRP 유지. |

### ADR-13-2: Ticker 스키마 형태

| 항목 | 결정 |
|------|------|
| 선택 | Flat 필드 (`current_price`, `change_rate_24h`, ... 직접 CoinResponse에 포함) |
| 대안 | 중첩 `TickerSummary` 객체 |
| 이유 | 클라이언트 접근 편의성, `Decimal` 정밀도 보장, nullable로 graceful degradation |

### ADR-13-3: 중복 방지 전략

| 항목 | 결정 |
|------|------|
| 선택 | `ON CONFLICT DO NOTHING` + rowcount 확인 |
| 대안 | 서비스 레벨 `exists()` 사전 체크 또는 IntegrityError catch |
| 이유 | Race condition 방지, 오류 파싱 불필요, 명시적 처리 |

### ADR-13-4: 코인 검색 인증

| 항목 | 결정 |
|------|------|
| 선택 | `CurrentUserOptional` (인증 선택) |
| 대안 | `CurrentUser` (인증 필수) |
| 이유 | 코인 마스터 데이터는 공개 정보, 미인증 사용자도 검색 가능해야 함 |

### ADR-13-5: Redis 직접 vs MarketCacheService

| 항목 | 결정 |
|------|------|
| 선택 | CoinService에 `Redis` 직접 주입 |
| 대안 | `MarketCacheService` DI 래퍼 사용 |
| 이유 | Redis pipeline 일괄 조회가 필요, MarketCacheService는 단건 get/set만 제공 |

---

## 16. 코드 패턴 참조

기존 v1-11 패턴 일관성 유지:
- API: `ApiResponse[T]` 래핑, `CurrentUser`/`CurrentUserOptional` DI
- Repository: `AsyncSession` 주입, `select`/`delete` 사용, `selectinload` eager loading
- Service: Repository + Redis 주입, `AppError` 도메인 예외, graceful degradation
- DI: `Depends(get_xxx)` + `Annotated[T, Depends()]` 타입 별칭, lazy import (`from app...`)
- 에러: `CoinErrors` 팩토리 패턴 (AuthErrors, ExchangeErrors와 동일 형태)
- 라우터: SRP 기반 파일 분리 (`coins.py`, `watchlist.py`), `__init__.py`에서 등록

# v1:2 데이터베이스 스키마 설계 및 마이그레이션 구성

## 1. 개요

하이브리드 DB 전략에 따라 PostgreSQL(트랜잭션)과 MongoDB(비정형/시계열) 스키마를 정의하고, Alembic(PG) + 커스텀 러너(Mongo) 마이그레이션을 구성한다.

**의존성**: v1:1(프로젝트 인프라) 완료 — `database.py`(Base, engine), `mongodb.py`(Motor client), Docker Compose(PG+Mongo+Redis) 준비됨.

**현재 상태**: `models/`, `documents/` 디렉토리 빈 `__init__.py`만 존재. `mongodb.py`의 `init_beanie()` 주석 처리. `pyproject.toml`에 `alembic` 미포함.

## 2. 데이터 모델

### 2-1. PostgreSQL 테이블 (11개)

| 테이블 | ST | PK | 주요 컬럼 | FK/제약 |
|--------|----|----|-----------|---------|
| users | 1 | UUID | email, password_hash(nullable), nickname, language, theme, price_color_style, ai_trading_enabled, totp_secret, is_2fa_enabled | email UNIQUE |
| user_social_accounts | 1 | UUID | user_id, provider, provider_id | FK→users CASCADE, UNIQUE(provider, provider_id) |
| clients | 1 | UUID | user_id, device_type, fcm_token | FK→users CASCADE |
| user_consents | 1 | UUID | user_id, consent_type, agreed_at, version | FK→users CASCADE |
| user_exchange_accounts | 2 | UUID | user_id, exchange_type, api_key_encrypted(BYTEA), api_secret_encrypted(BYTEA), is_active | FK→users CASCADE |
| coins | 2 | UUID | symbol, name_ko, name_en, exchange_type, market_code, is_active | UNIQUE(exchange_type, market_code) |
| watchlist_coins | 2 | UUID | user_id, coin_id, exchange_account_id, sort_order | FK→users/coins/accounts, UNIQUE(user_id, coin_id, exchange_account_id) |
| ai_trading_configs | 3 | UUID | watchlist_coin_id(UNIQUE), is_enabled, max_investment_ratio, stop/take/daily ratios, timeframes, strategy_params(JSONB) | FK→watchlist_coins CASCADE |
| ai_trading_config_history | 3 | UUID | config_id, action, changed_by, change_detail(JSONB) | FK→ai_trading_configs CASCADE |
| trade_orders | 3 | UUID | user_id, watchlist_coin_id, coin_id, exchange_account_id, order_type, price, quantity, status, is_ai_order, exchange_order_id | FK→users CASCADE, coins/accounts RESTRICT |
| price_alerts | 3 | UUID | user_id, coin_id, condition, target_price, is_triggered, is_active | FK→users/coins CASCADE |

> `backtest_runs`(M9)은 v1:2 범위 외. 별도 태스크에서 추가.

**공통 규칙**: 모든 테이블 `created_at`/`updated_at`(TIMESTAMPTZ) 필수, 금액 `NUMERIC(20,8)`, UUID v4 PK(`gen_random_uuid()`), SQLAlchemy 2.0 `Mapped[T]` + `mapped_column()`.

### 2-2. MongoDB 컬렉션 (7+6개)

| 컬렉션 | ST | 주요 필드 | TTL | 비고 |
|--------|----|-----------|----|------|
| trade_logs | 4 | user_id, trade_order_id, 주문 스냅샷, AI 컨텍스트, PnL | 없음 | PG 스냅샷 비정규화 |
| ai_decisions | 4 | user_id, regime, strategy, action, indicators_snapshot(내장), GPT 메타 | 6개월 | IndicatorsSnapshot 14종 지표 |
| daily_pnl_reports | 4 | user_id, report_date, PnL 집계, regime/strategy 통계 | 없음 | upsert 멱등 |
| candle_data_{1m,5m,15m,1h,4h,1d} | 5 | meta(exchange+market), OHLCV, trade_count | 차등(7d~5y) | Time Series 컬렉션 6개 |
| notifications | 6 | user_id, type, title, body, data, is_read | 90일 | |
| audit_logs | 6 | user_id, action, ip, user_agent, details | 없음 | 법적 보관 |
| news_data | 6 | source, title, url(unique), coin_symbols, sentiment | 없음 | |

**공통 규칙**: Beanie Document + `ConfigDict(populate_by_name=True)`, 컬렉션명 `Settings.name` 명시, PG 참조는 `int`/`UUID` 타입(DB FK 아님), API 응답 시 Schema 변환 필수.

## 3. 구현 파일 목록

### PG 모델 (ST1→ST2→ST3, FK 의존 순서)

| ST | 파일 | 역할 |
|----|------|------|
| 1 | `server/app/models/user.py` | User, UserSocialAccount, Client, UserConsent |
| 2 | `server/app/models/exchange.py` | UserExchangeAccount (FK→users) |
| 2 | `server/app/models/coin.py` | Coin, WatchlistCoin (FK→users, coins, accounts) |
| 3 | `server/app/models/trading.py` | AiTradingConfig, AiTradingConfigHistory, TradeOrder, PriceAlert |
| * | `server/app/models/__init__.py` | Base + 전체 모델 re-export (Alembic autogenerate용) |

### Mongo Documents (ST4, ST5, ST6 — 상호 독립)

| ST | 파일 | 역할 |
|----|------|------|
| 4 | `server/app/documents/trading_logs.py` | TradeLog, AiDecision, DailyPnlReport + IndicatorsSnapshot |
| 5 | `server/app/documents/candle_data.py` | CandleData (6개 타임프레임 컬렉션) |
| 6 | `server/app/documents/notifications.py` | Notification |
| 6 | `server/app/documents/audit_logs.py` | AuditLog |
| 6 | `server/app/documents/news_data.py` | NewsData |
| * | `server/app/documents/__init__.py` | ALL_DOCUMENTS 리스트 노출 |

### 마이그레이션 (ST7, ST8)

| ST | 파일 | 역할 |
|----|------|------|
| 7 | `server/pyproject.toml` | `alembic>=1.13` 의존성 추가 |
| 7 | `server/alembic.ini` | Alembic 설정 |
| 7 | `server/alembic/env.py` | async 엔진 연동 + `import app.models` + `target_metadata=Base.metadata` |
| 7 | `server/alembic/script.py.mako` | 마이그레이션 템플릿 |
| 7 | `server/alembic/versions/001_initial_schema.py` | 초기 스키마 (autogenerate) |
| 8 | `server/app/core/mongodb.py` (수정) | `init_beanie(ALL_DOCUMENTS)` 주석 해제 + Time Series 컬렉션 수동 생성 |
| 8 | `server/migrations/mongo/{__init__,runner,001_initial_indexes}.py` | Mongo 마이그레이션 러너 + 초기 인덱스 |

### 인덱스 최적화 (ST9) + 시드/테스트 (ST10)

| ST | 파일 | 역할 |
|----|------|------|
| 9 | `server/app/models/*.py` (수정) | PG 복합/부분/GIN 인덱스 추가 |
| 9 | `server/app/documents/*.py` (수정) | Mongo Settings.indexes 보강 |
| 10 | `server/app/seeds/{__init__,coins}.py` | 코인 마스터 시드 데이터 |
| 10 | `server/tests/integration/test_pg_models.py` | PG CRUD 통합 테스트 |
| 10 | `server/tests/integration/test_mongo_documents.py` | Mongo CRUD 통합 테스트 |

## 4. 주요 결정사항

| 결정 | 선택 | 근거 |
|------|------|------|
| PK 타입 | UUID v4 (`gen_random_uuid()`) | 분산 환경 대비, URL 노출 안전 |
| 금액 타입 | PG `NUMERIC(20,8)` / Mongo `Decimal128` | 부동소수점 오차 방지 |
| 암호화 키 저장 | `BYTEA` (AES-256-GCM) | `config.EXCHANGE_API_KEY_SECRET` 활용 |
| 타임스탬프 | 전체 UTC, PG `TIMESTAMPTZ` / Mongo `ISODate` | 글로벌 일관성 |
| 크로스DB 참조 | 비정규화 스냅샷 (trade_logs에 주문 정보 복사) | DB 레벨 JOIN 불가, 조회 성능 |
| 삭제 정책 | users→하위 CASCADE, coins/accounts→orders RESTRICT | 거래 기록 보호 (전자금융거래법) |
| 캔들 저장 | 타임프레임별 별도 Time Series 컬렉션 6개 | MongoDB 최적화, TTL 차등 적용 |
| backtest_runs/results | v1:2 범위 제외 (M9) | MVP 우선순위 |
| notifications | v1:2에 포함 (기본 모델만) | audit_logs와 함께 기반 구조 제공 |
| pg_trgm 익스텐션 | 초기 마이그레이션에서 `CREATE EXTENSION IF NOT EXISTS pg_trgm` | coins 검색 GIN 인덱스 전제 |

## 5. 빌드 시퀀스

```
Phase A (병렬 시작):
  ┌─ ST1: models/user.py (PG 사용자/인증)
  ├─ ST4: documents/trading_logs.py (Mongo 트레이딩 로그)
  ├─ ST5: documents/candle_data.py (Mongo 캔들 시계열)
  └─ ST6: documents/notifications.py, audit_logs.py, news_data.py (Mongo 기타)

Phase B (ST1 완료 후):
  └─ ST2: models/exchange.py, models/coin.py (PG 거래소/코인, FK→users)

Phase C (ST2 완료 후):
  └─ ST3: models/trading.py (PG AI매매/주문, FK→users/coins/accounts)

Phase D (병렬):
  ┌─ ST7: Alembic 초기화 + 초기 마이그레이션 (ST1,2,3 완료 필요)
  └─ ST8: Beanie 초기화 + Mongo 마이그레이션 (ST4,5,6 완료 필요)

Phase E (ST7,8 완료 후):
  └─ ST9: 인덱스 최적화 (PG + Mongo 양쪽)

Phase F (ST9 완료 후):
  └─ ST10: 시드 데이터 + 통합 테스트
```

**최대 병렬도**: Phase A에서 4-way (ST1 + ST4 + ST5 + ST6), Phase D에서 2-way (ST7 + ST8).

## 6. 파일 의존관계 요약

```
models/user.py          ← (의존 없음, Base만 import)
models/exchange.py      ← models/user.py (user_id FK)
models/coin.py          ← models/user.py + models/exchange.py (FKs)
models/trading.py       ← models/user.py + exchange.py + coin.py (FKs)
models/__init__.py      ← 위 전체 re-export

documents/*.py          ← (PG 모델 의존 없음, 완전 독립)
documents/__init__.py   ← 위 전체 ALL_DOCUMENTS 리스트

alembic/env.py          ← models/__init__.py (target_metadata)
core/mongodb.py         ← documents/__init__.py (ALL_DOCUMENTS)
```

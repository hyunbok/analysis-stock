# Code Architect Agent Memory

## 프로젝트 핵심 결정사항

- DB: 하이브리드 - PostgreSQL 16(SQLAlchemy 2.0 async) + MongoDB 7(Beanie async ODM)
  - PostgreSQL: 트랜잭션 데이터 (users, orders, exchange_accounts, coins, watchlist, ai_trading_configs)
  - MongoDB: 비정형/시계열 (trade_logs, daily_pnl_reports, candle_data, news_data, ai_decisions)
- AI 모듈: `server/trading/` 독립 패키지, `services/`를 통해서만 호출
- WebSocket: 단일 연결 `/ws/v1` + 채널 구독 메시지 방식 (채널당 개별 연결 방식 사용 안 함)
- Celery Tasks: `server/tasks/` 별도 패키지
- Repository Layer: `server/app/repositories/` 추가 (PG + Mongo 분리된 베이스 클래스)

## 디렉토리 구조 원칙

- `core/`: config.py, database.py(PG), mongodb.py(Beanie 초기화), security.py, deps.py
- `models/`: SQLAlchemy 모델만 (PG 테이블 7개)
- `documents/`: Beanie Document만 (MongoDB 컬렉션 5개)
- `repositories/`: base_pg.py + base_mongo.py 분리된 베이스, 각 레포지토리가 적절한 베이스 상속
- `ws/`: hub.py + router.py + handlers/ (api/v1에 혼재 금지)
- `providers/`: base.py(ABC 분리), factory.py 포함
- `trading/`: regime/, strategy/, execution/, indicators/ 하위 패키지
- `tasks/`: celery_app.py, ai_trading.py, news_scraper.py
- Flutter: `core/`는 진정한 공용 코드만, feature별 모델/프로바이더는 각 feature 안에

## API 경로 규칙

- `GET /api/v1/orders?status=open` (open 경로 파라미터 충돌 방지)
- `/api/v1/ai-trading/configs` (복수형)
- `/api/v1/users/me` (auth/me 아님)
- toggle 같은 동사 대신 명사 자원으로: `.../activation`

## Provider ABC 패턴

- ExchangeRestProvider: REST 호출 전용
- ExchangeStreamProvider: WebSocket 스트림 전용
- ExchangeProvider: 두 ABC 통합 상속
- ExchangeProviderFactory: 런타임 거래소 선택 (providers/factory.py)

## 의존 방향 (단방향)

api -> services -> repositories -> models (PG)
api -> services -> repositories -> documents (Mongo)
services -> providers (ABC만)
services -> trading/ (Protocol 인터페이스만)
ws/hub.py -> Redis Pub/Sub (services 직접 호출 금지)

## Beanie Document 사용 시 주의사항

- Beanie Document는 Pydantic BaseModel 상속 → API 응답으로 직접 반환 금지
- MongoDB 내부 필드(_id, revision_id 등)가 노출되므로 반드시 `schemas/`의 별도 Pydantic 스키마로 변환 필요
- 변환 패턴: `ResponseSchema.model_validate(document)` 사용
- Document 클래스에 `model_config = ConfigDict(populate_by_name=True)` 필요

## WebSocket 채널 목록 (events.yaml 기준)

- ticker, orderbook, trades, auto-trading, my-orders (PRD 5.2 명시)
- my-orders 채널: events.yaml 스펙에 추가 필요 (현재 시스템 프롬프트 표에 누락)

## API 네이밍 미결 항목

- PRD 5.1: `POST /api/v1/ai-trading/toggle` vs 코드 아키텍처 규칙 `PATCH .../activation`
- 구현 시 `PATCH /api/v1/ai-trading/configs/{id}/activation` 으로 통일 (PRD 수정 대상)

## 상세 참조

- architecture.md: 디렉토리 구조 전체 최종안

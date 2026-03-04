# DB Architect Agent Memory

## 프로젝트 핵심 결정사항

- PRD 위치: `/Users/hyunbokkim/workspaces/python-projects/analysis-stock/docs/prd.md`
- PRD 확정 스택: PostgreSQL 16 + SQLAlchemy 2.0 (트랜잭션) + MongoDB 7 + Beanie (비정형/시계열) 하이브리드
- 마이그레이션: Alembic (PG) + Beanie 마이그레이션 (MongoDB) 병행

## DB 분리 구조 (PRD 확정)

### PostgreSQL 테이블
users, clients, user_exchange_accounts, coins, watchlist_coins, ai_trading_configs, trade_orders

### MongoDB 컬렉션
trade_logs, daily_pnl_reports, candle_data, news_data, ai_decisions

## 핵심 아키텍처 결정

- Refresh Token: Redis `auth:refresh:{user_id}:{client_id}` (멀티 디바이스 지원, PRD 확정)
- `trade_logs`에 `coin_symbol`, `exchange_type` 비정규화 복제 (크로스DB 조회 최소화)
- `candle_data`는 MongoDB Time Series Collection 사용 권장
- `daily_pnl_reports` 집계: PG+MongoDB 동시 읽기 → Celery 태스크 멱등성(upsert) 필수

## 크로스DB 참조 주의사항

- trade_orders(PG) ← trade_logs(MongoDB): DB FK 불가, 앱 레벨 배치 조회로 N+1 방지
- order 체결 스냅샷 필드(price, quantity, order_type 등)를 trade_logs에 비정규화 검토 필요

## 마이그레이션

- Alembic: PostgreSQL 스키마 변경 (`server/alembic/`)
- Beanie 마이그레이션: MongoDB 컬렉션 변경
- 모든 마이그레이션에 롤백 전략 필수

## 상세 분석 문서

- [prd-db-analysis.md](./prd-db-analysis.md): PRD 충돌 분석 및 미결 사항 전체 정리

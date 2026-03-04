# PRD DB 아키텍처 분석 (2026-03-04 기준)

## PRD 확정 기술 스택

- PostgreSQL 16 + SQLAlchemy 2.0 async (트랜잭션 데이터)
- MongoDB 7 + Beanie async ODM (비정형/시계열 데이터)
- Redis 7 (캐시, Celery 브로커, Pub/Sub, Rate Limit)
- 마이그레이션: Alembic (PG) / Beanie 마이그레이션 (MongoDB)

## PostgreSQL 테이블 목록

users, clients, user_exchange_accounts, coins, watchlist_coins, ai_trading_configs, trade_orders

## MongoDB 컬렉션 목록

trade_logs, daily_pnl_reports, candle_data, news_data, ai_decisions

## 핵심 충돌 및 미결 사항

### [P1] 시스템 프롬프트 인덱싱 가이드 오류
- `watchlist_coins`, `ai_trading_configs`는 PRD 기준 PostgreSQL 테이블임
- 시스템 프롬프트 인덱싱 가이드에서 이 두 테이블 항목 제거 필요
- `candle_data`, `news_data`, `ai_decisions` 컬렉션 인덱싱 가이드 미정의 → 추가 필요

### [P1] Redis Refresh Token 키 패턴 불일치
- PRD 기준: `auth:refresh:{user_id}:{client_id}` (멀티 디바이스 지원)
- 시스템 프롬프트 기준: `session:{token}` (단일 토큰, 멀티 디바이스 일괄 무효화 불가)
- PRD 키 패턴이 올바른 기준

### [P2] trade_orders(PG) - trade_logs(MongoDB) 크로스DB 참조
- DB 레벨 foreign key constraint 불가 → 고아 참조 위험
- trade_logs에 비정규화할 스냅샷 필드 범위 확정 필요
  - 이미 확정: coin_symbol, exchange_type
  - 추가 확정 필요: order_price, order_quantity, order_type, order_method, status at execution time
- 주문+로그 조인 조회 API에서 N+1 방지를 위해 애플리케이션 레벨 배치 조회 필요

### [P2] daily_pnl_reports 집계 - 크로스DB 문제
- 집계 입력: trade_orders(PG) + trade_logs/ai_decisions(MongoDB)
- 집계 출력: daily_pnl_reports(MongoDB)
- 단일 트랜잭션 불가 → 멱등성(idempotent) 집계 설계 필수
- Celery 태스크 실패 시 재실행 전략 필요 (report_date 기준 upsert로 멱등성 보장)

### [P3] candle_data Time Series Collection 설계 필요
- MongoDB 5.0+ Time Series Collection 사용 권장
- timeField, metaField, granularity, TTL 설계 필요

## 확정된 캐시 키 패턴 (PRD 기준)

| 키 패턴 | 데이터 | 출처 |
|---------|--------|------|
| `auth:refresh:{user_id}:{client_id}` | Refresh Token | PRD 확정 |
| `rate:{ip}` | Rate Limit | PRD 확정 |
| `rate:{user_id}` | Rate Limit | PRD 확정 |
| `ticker:{exchange}:{market}` | 실시간 시세 | PRD + 시스템프롬프트 일치 |
| `user:{id}:profile` | 사용자 프로필 | 시스템프롬프트 (PRD 미기재) |
| `user:{id}:watchlist` | 관심코인 목록 | 시스템프롬프트 (PRD 미기재) |
| `user:{id}:balance:{exchange}` | 잔고 정보 | 시스템프롬프트 (PRD 미기재) |
| `coins:{exchange}` | 코인 마스터 | 시스템프롬프트 (PRD 미기재) |

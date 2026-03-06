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

## v1-7 2FA/세션 관리 DB 확정 (2026-03-06)

### Client 모델 확장 (server/app/models/user.py)
- 추가 컬럼: device_name(200), user_agent(500), ip_address(45), device_fingerprint(64), is_active(Bool, default=True)
- 추가 인덱스: ix_clients_user_fingerprint (user_id, device_fingerprint)
- is_active 활용: 일반 로그아웃=Redis 토큰 폐기만, 명시적 기기 제거=PG is_active=False

### UserTotpBackupCode 모델 (user_totp_backup_codes 테이블)
- 백업 코드 별도 테이블 (JSONB/LargeBinary 배열 기각)
- 컬럼: user_id(FK CASCADE), code_hash(SHA-256 hex, 64자), is_used(Bool), used_at(DateTime)
- 이유: 코드별 개별 사용/무효화 추적, used_at 감사 이력

### Alembic 마이그레이션
- 파일: server/alembic/versions/003_v1_7_2fa_session.py
- revision: c3d4e5f6a7b2 / down_revision: b2c3d4e5f6a1

### Redis 2FA 키 패턴 (auth: 네임스페이스 통일)
- `auth:2fa_pending:{user_id}:{temp_id}` TTL 5분 — 2FA 인증 대기 임시 상태 (temp_id는 Client 생성 전 서버 발급 UUID)
- `auth:2fa_fail:{user_id}` TTL 15분 — TOTP 실패 횟수 카운터 (max 5회)
- `auth:2fa_setup:{user_id}` — 2FA 초기 설정 세션

### AuditLog (MongoDB) — 변경 없음
- action 값 추가: 2fa_enabled, 2fa_disabled, 2fa_backup_used (코드 레벨)

## 크로스DB 참조 주의사항

- trade_orders(PG) ← trade_logs(MongoDB): DB FK 불가, 앱 레벨 배치 조회로 N+1 방지
- order 체결 스냅샷 필드(price, quantity, order_type 등)를 trade_logs에 비정규화 검토 필요

## 마이그레이션

- Alembic: PostgreSQL 스키마 변경 (`server/alembic/`)
- Beanie 마이그레이션: MongoDB 컬렉션 변경
- 모든 마이그레이션에 롤백 전략 필수

## 상세 분석 문서

- [prd-db-analysis.md](./prd-db-analysis.md): PRD 충돌 분석 및 미결 사항 전체 정리

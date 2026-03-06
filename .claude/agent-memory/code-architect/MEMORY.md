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

## PRD 누락/불일치 항목 (Stitch 화면 대조 결과)

- `api/v1/notifications.py` 라우터 파일 구조에 누락 (API 엔드포인트는 PRD 5.1에 정의됨)
- `POST /api/v1/auth/me/avatar` 아바타 업로드 엔드포인트 PRD 5.1 미정의 (M2에 기능 포함)
- 소셜 로그인 엔드포인트 PRD 5.1 완전 누락: `POST /api/v1/auth/social/google|apple` 추가 필요
- `api/v1/social_auth.py` 분리 권장 (SRP 원칙, OAuth 로직 복잡성)
- Flutter `features/notifications/` 디렉토리 PRD 11.2에 누락
- 파일 업로드(아바타): 별도 스토리지 인프라 결정 필요 (S3/MinIO/로컬 - PRD 미정의)
- WS notifications 채널 불필요 - `clients.fcm_token`으로 FCM 처리 (백그라운드 알림)

## v1-5 JWT 인증 시스템 설계 결정사항

- User 모델: `soft_deleted_at: datetime | None` 필드 추가 (30일 유예 soft delete)
- Refresh Token: SHA-256 해시만 Redis 저장 (원본 미저장), `auth:refresh:{user_id}:{client_id}` 키
- 토큰 로테이션: 갱신 시 기존 refresh token 폐기 + 새 발급, `client_id` 유지
- AppError 예외 체계: `core/exceptions.py` (AppError + AuthErrors 팩토리)
- AppError 핸들러: `middleware/error_handler.py`에 통합 (main.py 아님)
- ApiResponse<T> 공통 래퍼: `schemas/common.py` 신규
- DI 팩토리: `deps.py`에 `get_auth_service()`, `get_user_repository()` 등 추가
  - `settings: Settings = Depends(get_settings)` 패턴 사용 (AppSettings 별칭)
- 인증 엔드포인트: `POST /api/v1/auth/{register,verify-email,login,refresh,logout}`
- 사용자 엔드포인트: `GET/PUT/DELETE /api/v1/users/me`
- DELETE /api/v1/users/me: body에 refresh_token 포함 (로그아웃+삭제 동시 처리)
- Settings SMTP 추가: SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM_EMAIL, SMTP_FROM_NAME, SMTP_STARTTLS
- 설계서: `docs/tasks/v1-5-jwt-auth-system-plan.md`

## v1-6 소셜 로그인 설계 결정사항

- 설계서: `docs/tasks/v1-6-social-login-oauth2-plan.md`
- 엔드포인트: `POST /api/v1/auth/social/google|apple` (200 단일 응답 + is_new_user 플래그)
- 라우터 파일: `api/v1/social_auth.py` (auth.py 분리, SRP)
- 스키마 파일: `schemas/social_auth.py` (auth.py 분리, SRP)
- OAuthVerificationService: **단일 클래스** (Google/Apple 통합, _PROVIDER_CONFIG dict 패턴)
  - JWKS URL은 클래스 상수 고정 (환경변수 노출 금지, SSRF 방지)
  - `verify_google_token()` / `verify_apple_token()` → `_verify_token()` 공통 메서드
- JwksCacheService: Redis 기반 (인메모리 dict 사용 금지, 멀티워커 환경)
  - 캐시 키: `oauth:jwks:{provider}`, TTL: `OAUTH_JWKS_CACHE_TTL` (기본 3600초)
  - kid 없음(키 순환) 감지 시 캐시 무효화 후 1회 재조회
- SocialAuthService: OAuthUserInfo DTO만 받음 (검증 책임 분리)
  - [A] 기존 소셜 계정 → JWT 발급
  - [B] 이메일 병합 → UserSocialAccount 추가 + email_verified_at 업데이트
  - [C] 신규 User 생성 (password_hash=None, email_verified_at=now)
- 에러 코드: AuthErrors에 3개 추가 (별도 SocialAuthErrors 클래스 금지)
  - INVALID_OAUTH_TOKEN(401), OAUTH_EMAIL_REQUIRED(422), OAUTH_PROVIDER_UNAVAILABLE(502)
- Settings 추가: GOOGLE_CLIENT_ID 3개 + APPLE_APP_BUNDLE_ID + APPLE_WEB_CLIENT_ID + OAUTH_JWKS_CACHE_TTL
- DI: OAuthVerificationServiceDep + SocialAuthServiceDep (단일화)

## 상세 참조

- architecture.md: 디렉토리 구조 전체 최종안

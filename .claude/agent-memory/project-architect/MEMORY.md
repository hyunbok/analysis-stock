# Project Architect Memory

## 프로젝트 구조
- 설계서 위치: `docs/tasks/v1-{N}-{name}-plan.md`
- 참조 문서: `docs/refs/project-prd.md`, `docs/refs/architecture.md`, `docs/refs/security.md`
- 서버 코드: `server/app/` (FastAPI, 3계층: api → services → repositories)
- 테스트: `server/tests/` (unit/, integration/)

## 아키텍처 패턴
- 모듈러 모놀리스, 3계층 패턴 (API → Service → Repository)
- DI: FastAPI Depends 체인, `deps.py`에 팩토리 함수 + Annotated 타입 별칭
- 에러 처리: AppError 도메인 예외 → error_handler.py 글로벌 핸들러 → ErrorResponse 통일 포맷
- 미들웨어 체인 (LIFO): CORS → CorrelationId → RateLimit → Prometheus → ErrorHandler

## 기존 인프라
- DB: PostgreSQL (SQLAlchemy async), MongoDB (Beanie), Redis (redis.asyncio)
- 설정: `core/config.py` (pydantic-settings), `core/redis_keys.py` (키 패턴/TTL)
- 인증 캐시: `services/auth_cache_service.py` (refresh token, email verify, password reset)

## 설계서 작성 컨벤션
- code-architect와 분업: 나는 파일 구조/DI 흐름/시퀀스 다이어그램, 상대는 API 규격/스키마/컨벤션
- 기존 코드와의 정합성 반드시 확인 후 작성
- 시퀀스 다이어그램은 ASCII art 형식 사용

## v1-5 결정 사항
- soft delete: `soft_deleted_at: datetime | None` (bool 아닌 timestamp)
- JWT: python-jose, bcrypt: passlib, email: aiosmtplib
- Refresh token rotation + SHA-256 해시 Redis 저장

## v1-6 결정 사항 (소셜 로그인)
- 단일 OAuthVerificationService (Google/Apple 통합, _PROVIDER_CONFIG dict + _verify_token() 공통)
- JWKS URL 하드코딩 (SSRF 방지, 환경변수 노출 금지)
- JWKS Redis 캐시 (JwksCacheService, 멀티워커 안전)
- SRP 분리: schemas/social_auth.py, api/v1/social_auth.py (기존 auth.py에 추가 안 함)
- AuthErrors에 통합 (별도 SocialAuthErrors 클래스 금지)
- 의존 라이브러리: python-jose[cryptography] (RSA), httpx (JWKS fetch)

## 협업 패턴
- code-architect와 이견 시 먼저 합의 후 설계서 반영 (동시 편집 충돌 주의)
- 설계서 초안을 먼저 작성하고 상대에게 수정/보강 요청하는 방식이 효율적

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

## v1-7 결정 사항 (2FA + 세션 관리)
- 2FA: TOTP (pyotp), AES-256-GCM 암호화 (cryptography), QR (qrcode[pil])
- 백업 코드: 10개 × 10자리, 별도 `user_totp_backup_codes` 테이블 (LargeBinary 기각)
- 백업 코드 반환 시점: setup이 아닌 **verify 성공 시** 반환
- 로그인 2FA: temp_token(5분 TTL) → POST /2fa/login-verify, LoginResponse nullable 통합
- Device 정보: Header 방식 (X-Device-Name, X-Device-Fingerprint), Body 아님
- Client 모델: device_name(200), user_agent, ip_address, device_fingerprint, is_active 추가
- 에러 통합: INVALID_BACKUP_CODE → invalid_totp_code(), TOTP_SETUP_EXPIRED → totp_setup_required()
- TOTP 브루트포스: 2fa:fail_count:{user_id} Redis 키 (5회/15분)
- AuditService: mongodb DI 주입, fire-and-forget (실패해도 주요 로직 차단 안 함)
- 서비스 오케스트레이션: AuthService에 TwoFactorService 주입 안 함 → API 레이어에서 조율 (순환 의존 방지)
- Setup TTL: 10분, Temp token TTL: 5분
- URL: POST /2fa/disable (DELETE 아님, body 필요), POST /2fa/login-verify

## v1-8 결정 사항 (거래소 추상화 계층)
- ABC 3단계: ExchangeRestProvider → ExchangeStreamProvider → ExchangeProvider (통합)
- BaseExchangeProvider: `_execute_rest()` 래퍼로 Rate Limiter → Circuit Breaker 자동 적용
- Factory 싱글턴: `ExchangeProviderFactory.init(redis)` → `.instance()` 패턴
- Registry 데코레이터: `@ExchangeProviderRegistry.register(ExchangeType.UPBIT)` 방식
- Circuit Breaker: 인메모리, 거래소별 독립, 슬라이딩 윈도우 + 연속 실패 하이브리드
- Circuit Breaker 제외 예외: Auth, Permission, InvalidSymbol, InsufficientBalance (사용자 오류)
- 기존 ExchangeRateLimiter 100% 재사용 (providers/rate_limiter.py 별도 생성 안 함)
- 예외 이중 계층: providers/exceptions.py (내부) → core/exceptions.py ExchangeErrors (HTTP 응답)
- v1-8 범위: 추상화 + Mock Provider만. 실제 거래소는 M3(Upbit), M5(CoinOne) 등에서 구현
- 의존 라이브러리: websockets 신규 추가, httpx 기존 의존
- SymbolMapper: 정규화 심볼 "BTC/KRW" ↔ 거래소 마켓 코드 양방향 변환

## v1-9 결정 사항 (Upbit 거래소 프로바이더)
- 디렉토리: `providers/upbit/` (provider.py, auth.py, stream.py, mappers.py, constants.py)
- JWT 알고리즘: **HS512** (Upbit 공식 문서 기준, HS256 아님)
- JWT payload: access_key, nonce(UUID4), query_hash(SHA-512, 조건부), query_hash_alg
- POST body query_hash: body를 "key=value&key=value"로 변환 후 SHA-512
- WS 파일명: `stream.py` (websockets 라이브러리명 충돌 방지, ExchangeStreamProvider 일관성)
- WS 클래스: `_UpbitWebSocketClient` (언더스코어 prefix로 internal 표시)
- SymbolMapper 동적 등록: initialize() 시 GET /v1/market/all → register_batch()
- 정적 fallback: UPBIT_STATIC_MARKETS 15개 (동적 로드 실패 시 유지)
- 에러 매핑: UPBIT_ERROR_MAP(error.name 기반) + HTTP_STATUS_ERROR_MAP(폴백)
- HTTP 418 처리: Upbit 고유 IP 차단 → ExchangeRateLimitError
- 시장가 매수 특이사항: ord_type="price", volume 대신 price(총 KRW)로 입력
- 재시도: Provider는 단발 호출, 서비스 레이어에서 Exponential Backoff (최대 3회)
- 의존 라이브러리: PyJWT>=2.8, websockets>=12.0
- 테스트: 42건 (단위 38 + 통합 4)

## 협업 패턴
- code-architect와 이견 시 먼저 합의 후 설계서 반영 (동시 편집 충돌 주의)
- 설계서 초안을 먼저 작성하고 상대에게 수정/보강 요청하는 방식이 효율적
- db-architect와 3자 합의 패턴 확립: 초안 → 병렬 리뷰 요청 → 피드백 반영 → 최종 확정

# code-review-expert 메모리

## 프로젝트 구조
- 백엔드: `server/app/` (FastAPI, Python 3.12+)
- 프론트엔드: `lib/` (Flutter)
- 테스트: `server/tests/integration/` (fakeredis 기반)
- 설계서 위치: `docs/tasks/`

## 리뷰 워크플로
1. team-lead 또는 python-backend로부터 [REVIEW] 메시지 수신
2. 설계서(`docs/tasks/`) 먼저 숙지
3. 구현 파일 병렬 Read (전체 파일 한번에)
4. 체크리스트 기준 분석
5. python-backend에 [REVIEW] 피드백 전달
6. 수정 완료 후 재리뷰, 통과 시 team-lead에 [NOTIFY] 보고

## 자주 발견되는 패턴 (인증/보안 관련)

### CRITICAL 패턴
- **Rate Limiting 미구현**: 설계서에 에러코드가 정의되어 있어도 실제 체크 로직 누락 가능 → 반드시 서비스 메서드 내 실제 구현 확인

### WARNING 패턴
- **Timing Attack**: `user is None` 시 bcrypt 비교 건너뜀 → `_DUMMY_HASH`로 항상 bcrypt 수행
- **assert 프로덕션 사용**: `-O` 빌드 시 무시 → `RuntimeError`로 교체
- **PII 평문 로깅**: 이메일 주소 마스킹 필요 (`email[:3] + "***" + email[email.find("@"):]`)
- **RedisKey 미사용**: 신규 Redis 키를 하드코딩 → `RedisKey` 헬퍼 클래스에 메서드 추가
- **Rate Limit TTL 슬라이딩 윈도우**: `expire(key, window)` 매 호출마다 TTL 리셋 → `expire(key, window, nx=True)` 고정 윈도우

## 자주 발견되는 패턴 (Redis 관련)

### CRITICAL 패턴
- **TOCTOU 레이스 컨디션**: GET → compare → DELETE 패턴 → `GETDEL` (Redis 6.2+)로 수정
- **Rate Limit identifier 오류**: JWT 토큰을 identifier로 사용 → 미들웨어는 IP만, user_id는 라우터 레벨에서 처리

### WARNING 패턴
- **get_status()가 acquire() 호출**: 상태 조회 메서드가 실제 토큰 소비 → Redis GET 파싱으로 수정
- **Pub/Sub 재연결 버그**: 예외 후 `_pubsub = None` 리셋 누락 → 예외 처리 블록에 `self._pubsub = None` 추가
- **expire(xx=True)**: incr로 새로 생성된 키에 TTL 미설정 → `expire()` (xx 없이) 사용
- **X-Forwarded-For 신뢰**: 검증 없이 직접 사용 → Starlette ProxyHeadersMiddleware 위임
- **채널 누락**: 설계서 §4-1 모든 채널이 PubSubChannel 클래스에 있는지 확인 필요

### 테스트 패턴
- fakeredis: `fakeredis.aioredis.FakeRedis(decode_responses=True)` 사용
- Pub/Sub 테스트: `redis_client.pubsub()` → subscribe → listen 루프
- graceful degradation: `patch.object(redis_client, "evalsha", side_effect=ConnectionError(...))`
- 토큰 리필: `patch("app.core.rate_limiter.time")` 으로 time.time 모킹

## 자주 발견되는 패턴 (OAuth/소셜 로그인 관련)

### CRITICAL 패턴
- **python-jose private API 사용**: `from jose.backends import RSAKey` → private API, 버전 업 시 깨질 위험
  → `jwt.decode(token, jwk_dict, algorithms=["RS256"], ...)` 로 JWK dict 직접 전달 (공개 API)
  → `JwksCacheService._extract_key()`가 PEM 변환 없이 JWK dict 반환하는 패턴으로 수정

### WARNING 패턴
- **OAuth audience 빈 리스트**: 환경변수 미설정 시 `allowed_audiences=[]` → python-jose가 JWTClaimsError 발생
  → 모든 소셜 로그인 실패하지만 원인 불명 → verify 메서드 진입 시 빈 리스트 조기 검증 후 `oauth_provider_unavailable()` 발생
- **소셜 로그인 테스트 누락 패턴**: Google 에러 케이스는 있지만 Apple 동일 케이스 누락 (account_deleted 등)
- **JWKS 캐시 키 순환**: 캐시 HIT + kid 없음 시 명시적 DEL 없이 덮어쓰기 → 설계서 §7.2 명시 DEL 후 재조회 패턴 준수

### OAuthVerificationService 설계 패턴
- 단일 클래스 + `_PROVIDER_CONFIG` dict + `_verify_token()` 공통 private 메서드 (DRY)
- JWKS URL 클래스 상수 하드코딩 (SSRF 방지, 환경변수 금지)
- `except AppError: raise` → JWKS 가용성 오류를 invalid_token으로 마스킹하지 않음
- `allowed_audiences` 빈 리스트 조기 검증은 `verify_google_token()` / `verify_apple_token()` 진입 시점

## 자주 발견되는 패턴 (2FA/세션 관리 관련)

### CRITICAL 패턴
- **Private attribute 직접 접근**: API 레이어에서 `svc._cache.xxx()` 직접 호출 → 서비스에 위임 메서드 추가
- **Redis 키 하드코딩**: `f"auth:2fa_pending:{token_hash}"` → `RedisKey` 헬퍼 미사용 감지 필수
- **JWT payload에 client_id 미포함**: logout-all/is_current 기능 불가 → `create_access_token(client_id=)` 포함 확인

### WARNING 패턴
- **deactivate_all() N+1 UPDATE**: 루프 내 개별 UPDATE → 단일 bulk UPDATE + `rowcount` 반환
- **광범위한 except Exception**: 암호화 실패는 `cryptography.exceptions.InvalidTag` + `ValueError`로 좁혀야 함
- **import inside try block**: `from cryptography.exceptions import InvalidTag`는 모듈 상단으로

### Redis 2FA 키 설계 주의
- `auth:2fa_pending:{user_id}:{token_hash}` (설계서) vs token_hash만 사용 구현 → 인덱스 키 패턴으로 해결:
  - store: pipeline으로 실제키 + `auth:2fa_pending_idx:{token_hash}` 동시 저장
  - getdel: 인덱스 GETDEL → user_id 획득 → 실제키 GETDEL (2단계 비원자적이나 보안상 안전)
- 신규 키 패턴은 반드시 `RedisKey` 클래스에 메서드 추가

### 테스트 패턴 (2FA)
- 3개 fixture 분리: `test_app` (비인증), `test_app_authed` (2FA 비활성), `test_app_authed_2fa` (2FA 활성)
- `get_current_client_id` 오버라이드 없으면 logout-all의 `except_client_id=None` → 주의
- audit log 검증: `mock_audit_service`를 파라미터로 받지 않으면 호출 횟수 검증 불가
- MongoDB 모듈: `sys.modules`에 `ModuleType` 인스턴스로 mock (Pydantic v2 + bson.Decimal128 비호환 우회)

## 팀 구성 (v1-5 이후)
- team-lead: 총괄, 최종 보고 대상
- python-backend-expert: 백엔드 구현 (리뷰 대상, SendMessage recipient = "python-backend-expert")
- e2e-test-expert: 통합 테스트 구현 (SendMessage recipient = "e2e-test-expert")
- code-review-expert: 본인

## 주요 설계 결정 (v1-3)
- Rate Limiter: Token Bucket Lua EVALSHA (`server/app/core/lua/token_bucket.lua`)
- Pub/Sub 전용 풀: `socket_timeout=None` (블로킹 listen용 분리)
- Refresh Token: String + Set 인덱스 (세션 관리)
- 미들웨어: IP 기반만, user_id Rate Limit은 라우터 의존성

## 주요 설계 결정 (v1-7)
- JWT access token에 client_id 포함 → `get_current_client_id()` DI로 현재 세션 식별
- 2FA pending 토큰: `secrets.token_urlsafe(32)` → SHA-256 해시를 Redis 키로 사용
- AuditService: fire-and-forget (try-except 격리, 실패해도 주요 플로우 차단 안 함)
- 오케스트레이션: AuthService에 2FA/Session 미주입, API 레이어에서 조율 (순환 의존 방지)

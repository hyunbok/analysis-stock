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

## 팀 구성 (v1-5 이후)
- team-lead: 총괄, 최종 보고 대상
- python-backend-expert: 백엔드 구현 (리뷰 대상, SendMessage recipient = "python-backend-expert")
- code-review-expert: 본인

## 주요 설계 결정 (v1-3)
- Rate Limiter: Token Bucket Lua EVALSHA (`server/app/core/lua/token_bucket.lua`)
- Pub/Sub 전용 풀: `socket_timeout=None` (블로킹 listen용 분리)
- Refresh Token: String + Set 인덱스 (세션 관리)
- 미들웨어: IP 기반만, user_id Rate Limit은 라우터 의존성

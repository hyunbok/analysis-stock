# v1-6: 소셜 로그인 구현 (Google/Apple OAuth2) - 상세 설계서

## 1. 개요

Google 및 Apple OAuth2 소셜 로그인을 통합하여 사용자가 소셜 계정으로 간편하게 로그인할 수 있도록 한다.
클라이언트(Flutter)에서 OAuth2 인증을 수행하고 id_token을 서버로 전송하면, 서버는 토큰을 검증하고 JWT를 발급한다.

### 1.1 핵심 원칙

- **서버 검증 전용**: 클라이언트 OAuth 플로우 → id_token만 서버로 전송 → 서버에서 서명 검증
- **기존 코드 최대 활용**: AuthService, UserRepository, AuthCacheService 재사용
- **자동 계정 병합**: provider_email과 기존 users.email 일치 시 자동 연동
- **소셜 전용 계정 지원**: password_hash=NULL인 사용자 허용 (이미 nullable)

---

## 2. 시스템 아키텍처

### 2.1 전체 흐름

```
Flutter App                    Server (FastAPI)                          External
-----------                    ----------------                          --------

[Google Sign-In SDK] ───────────────────────────────────────────────> [Google OAuth2]
       │                                                                   │
       │ <── id_token ─────────────────────────────────────────────────────┘
       │
       ├── POST /api/v1/auth/social/google ──> [API: social_auth.py]
       │        { id_token }                        │
       │                                            ├─> [OAuthVerificationService]
       │                                            │       ├─> verify_google_token()
       │                                            │       └─> verify_apple_token()
       │                                            │              │
       │                                            │       [JwksCacheService]
       │                                            │         ├─ Redis 캐시 조회/저장
       │                                            │         └─ httpx JWKS fetch (캐시 미스 시)
       │                                            │
       │                                            └─> [SocialAuthService]
       │                                                    ├─> [SocialAccountRepository]
       │                                                    │       └─> provider+provider_id 조회
       │                                                    ├─> [UserRepository]
       │                                                    │       └─> email 기반 기존 사용자 조회
       │                                                    └─> JWT(Access+Refresh) 발급
       │                                                            └─> [AuthCacheService]
       │ <── { user, tokens } ─────────────────────┘
       │
[Apple Sign-In SDK] ── (동일 흐름, /social/apple) ──> ...
```

### 2.2 인증 흐름 분류

| 시나리오 | 조건 | 처리 |
|----------|------|------|
| 기존 소셜 사용자 | provider+provider_id 존재 | JWT 발급 |
| 이메일 일치 병합 | provider 미등록, email 일치 | social_account 추가 → JWT 발급 |
| 신규 사용자 | provider 미등록, email 미존재 | User 생성 + social_account 추가 → JWT 발급 |
| 소셜 email 없음 (Google) | Google 토큰에 이메일 없음 | `OAUTH_EMAIL_REQUIRED` 에러 반환 (Google은 이메일 필수) |
| Apple email 없음 | Apple private relay 이메일 제공 | relay 이메일을 users.email로 저장 (유효한 이메일) |

---

## 3. 파일 구조

### 3.1 새로 생성할 파일

```
server/app/
├── schemas/
│   └── social_auth.py               # 소셜 로그인 요청/응답 스키마 + OAuthUserInfo DTO
├── services/
│   ├── oauth_verification_service.py # 단일 OAuthVerificationService (Google/Apple 통합)
│   ├── jwks_cache_service.py         # JWKS Redis 캐시 + httpx 조회
│   └── social_auth_service.py        # 소셜 로그인 오케스트레이션 (검증 제외)
├── repositories/
│   └── social_account_repository.py  # UserSocialAccount DB 접근 계층
└── api/v1/
    └── social_auth.py                # POST /google, /apple 엔드포인트 (auth.py 분리)

server/tests/
├── unit/
│   ├── test_oauth_verification_service.py
│   └── test_social_auth_service.py
└── integration/
    └── test_social_auth_api.py
```

### 3.2 수정할 파일

| 파일 | 변경 내용 |
|------|-----------|
| `core/config.py` | Google Client ID 3개 + Apple audience 2개 + `OAUTH_JWKS_CACHE_TTL` (JWKS URL은 하드코딩) |
| `core/deps.py` | `get_jwks_cache_service`, `get_oauth_verification_service`, `get_social_account_repository`, `get_social_auth_service` + `OAuthVerificationServiceDep`, `SocialAuthServiceDep` 타입 별칭 |
| `core/exceptions.py` | `AuthErrors`에 `invalid_oauth_token`, `oauth_email_required`, `oauth_provider_unavailable` 3개 추가 |
| `api/v1/__init__.py` | `social_auth` 라우터 등록 (`/auth/social` prefix) |
| `repositories/user_repository.py` | `create_social_user()` 추가 (password_hash=None, email_verified_at=now, avatar_url 지원) |

---

## 4. DI 의존성 흐름

```
                    ┌─────────────────────────────────────────┐
                    │        API Layer (social_auth.py)        │
                    │  POST /google          POST /apple       │
                    └──────────┬──────────────────┬───────────┘
                               │                  │
                     OAuthVerificationServiceDep + SocialAuthServiceDep
                               │                  │
                               ▼                  ▼
                    ┌─────────────────────────────────────────┐
                    │      OAuthVerificationService           │
                    │  verify_google_token() / verify_apple_token()  │
                    │  _PROVIDER_CONFIG (JWKS URL 하드코딩)    │
                    └──────────────┬──────────────────────────┘
                                   │
                                   ▼
                    ┌─────────────────────────────────────────┐
                    │         JwksCacheService                 │
                    │  Redis GET/SETEX (oauth:jwks:{provider}) │
                    │  httpx JWKS fetch (캐시 미스 시)          │
                    └──────────────┬──────────────────────────┘
                                   │
                            Redis + httpx
                                   │
                    ┌──────────────┴──────────────────────────┐
                    │         SocialAuthService                │
                    │  DB 조회/생성/병합 + JWT 발급             │
                    └──┬──────────┬──────────┬────────────────┘
                       │          │          │
                  UserRepo  SocialRepo  AuthCacheService
                  (기존)    (신규)      (기존, Redis JWT)
```

### 4.1 deps.py 추가 항목

v1-5 `deps.py` 패턴을 그대로 따름 (`Depends` 팩토리 + `Annotated` 타입 별칭).

```python
# server/app/core/deps.py 추가

from app.repositories.social_account_repository import SocialAccountRepository
from app.services.oauth_verification_service import OAuthVerificationService
from app.services.jwks_cache_service import JwksCacheService
from app.services.social_auth_service import SocialAuthService


def get_social_account_repository(
    db: AsyncSession = Depends(get_db),
) -> SocialAccountRepository:
    return SocialAccountRepository(db)


def get_jwks_cache_service(
    redis: Redis = Depends(get_redis),
    settings: Settings = Depends(get_settings),
) -> JwksCacheService:
    return JwksCacheService(redis, settings)


def get_oauth_verification_service(
    jwks_cache: JwksCacheService = Depends(get_jwks_cache_service),
    settings: Settings = Depends(get_settings),
) -> OAuthVerificationService:
    return OAuthVerificationService(settings, jwks_cache)


def get_social_auth_service(
    user_repo: UserRepository = Depends(get_user_repository),
    social_repo: SocialAccountRepository = Depends(get_social_account_repository),
    cache: AuthCacheService = Depends(get_auth_cache_service),
    settings: Settings = Depends(get_settings),
) -> SocialAuthService:
    return SocialAuthService(user_repo, social_repo, cache, settings)


# ── Type aliases (Annotated) ──────────────────────────────────────────────────
SocialAuthServiceDep = Annotated[SocialAuthService, Depends(get_social_auth_service)]
OAuthVerificationServiceDep = Annotated[OAuthVerificationService, Depends(get_oauth_verification_service)]
```

> **설계 결정**: 단일 `OAuthVerificationService` 클래스에 `verify_google_token()` / `verify_apple_token()` 메서드.
> `_PROVIDER_CONFIG` dict + `_verify_token()` 공통 private 메서드로 DRY 원칙 준수.
> JWKS URL은 클래스 상수로 하드코딩 (SSRF 방지).

---

## 5. 시퀀스 다이어그램

### 5.1 Google 소셜 로그인 (신규 사용자)

```
Client (Flutter)          Server (FastAPI)              Google
     │                         │                          │
     │──── Google Sign-In ─────────────────────────────> │
     │ <── id_token ────────────────────────────────────  │
     │                         │                          │
     │── POST /social/google ─>│                          │
     │   { id_token }          │                          │
     │                         │── Fetch JWKS (캐시) ────>│
     │                         │<── Public Keys ──────────│
     │                         │                          │
     │                         │── RS256 서명 검증         │
     │                         │── iss, aud, exp 클레임 검증
     │                         │                          │
     │                         │── SocialAccountRepo.get_by_provider_id()
     │                         │   (provider=google, provider_id=sub)
     │                         │   → None (미등록)
     │                         │                          │
     │                         │── UserRepo.get_by_email(provider_email)
     │                         │   → None (미존재)
     │                         │                          │
     │                         │── UserRepo.create_social_user()
     │                         │   (email, nickname=이메일앞부분, password_hash=None)
     │                         │   email_verified_at = now()  ← 소셜 인증이므로
     │                         │                          │
     │                         │── SocialAccountRepo.create()
     │                         │   (user_id, provider=google, provider_id=sub, provider_email)
     │                         │                          │
     │                         │── JWT Access + Refresh 생성
     │                         │── AuthCacheService.store_refresh_token()
     │                         │                          │
     │ <── 200 { user, tokens }│                          │
```

### 5.2 이메일 일치 자동 병합

```
Client (Flutter)          Server (FastAPI)
     │                         │
     │── POST /social/google ─>│
     │   { id_token }          │
     │                         │── id_token 검증 OK
     │                         │
     │                         │── SocialAccountRepo.get_by_provider_id()
     │                         │   → None (이 provider로 미등록)
     │                         │
     │                         │── UserRepo.get_by_email(provider_email)
     │                         │   → User 존재! (이메일 가입 사용자)
     │                         │
     │                         │── SocialAccountRepo.create()
     │                         │   (기존 user_id에 소셜 계정 연동)
     │                         │
     │                         │── 기존 User로 JWT 발급
     │                         │── email_verified_at이 NULL이면 now()로 업데이트
     │                         │
     │ <── 200 { user, tokens }│
```

### 5.3 기존 소셜 사용자 로그인

```
Client (Flutter)          Server (FastAPI)
     │                         │
     │── POST /social/google ─>│
     │   { id_token }          │
     │                         │── id_token 검증 OK
     │                         │
     │                         │── SocialAccountRepo.get_by_provider_id()
     │                         │   → UserSocialAccount 존재 → user_id 확인
     │                         │
     │                         │── UserRepo.get_by_id(user_id)
     │                         │   → User 존재
     │                         │
     │                         │── soft_deleted_at 체크
     │                         │── JWT Access + Refresh 발급
     │                         │
     │ <── 200 { user, tokens }│
```

---

## 6. 환경변수 구성

### 6.1 config.py 추가 필드

```python
# OAuth2 (Social Login)
GOOGLE_CLIENT_ID: str = ""            # Google Cloud Console 웹 Client ID
GOOGLE_CLIENT_ID_IOS: str = ""        # iOS 전용 Client ID (선택, 없으면 GOOGLE_CLIENT_ID 사용)
GOOGLE_CLIENT_ID_ANDROID: str = ""    # Android 전용 Client ID (선택)

APPLE_APP_BUNDLE_ID: str = ""         # Apple Developer 앱 Bundle ID (aud 검증용)
APPLE_WEB_CLIENT_ID: str = ""         # Sign In with Apple for Web Client ID (선택)

OAUTH_JWKS_CACHE_TTL: int = 3600      # JWKS 공개키 Redis 캐시 TTL (초, 기본 1시간)
```

> **JWKS URL**: `OAuthVerificationService._PROVIDER_CONFIG`에 클래스 상수로 하드코딩 (SSRF 방지).
> 테스트 시에는 `JwksCacheService`를 mock하거나 `httpx` 응답을 mock.

### 6.2 .env 예시

```env
# Google OAuth2
GOOGLE_CLIENT_ID=123456789.apps.googleusercontent.com
GOOGLE_CLIENT_ID_IOS=ios-client-id.apps.googleusercontent.com
GOOGLE_CLIENT_ID_ANDROID=android-client-id.apps.googleusercontent.com

# Apple Sign In
APPLE_APP_BUNDLE_ID=com.cointrader.app
APPLE_WEB_CLIENT_ID=com.cointrader.web  # 웹 로그인 사용 시

# JWKS Cache (기본값 유지 시 생략 가능)
OAUTH_JWKS_CACHE_TTL=3600
```

### 6.3 Google audience 검증 규칙

Google의 경우 플랫폼별 Client ID가 다르므로, `aud` 검증 시 허용 목록으로 처리:

```python
@property
def google_allowed_audiences(self) -> list[str]:
    """Google aud 검증에 허용할 Client ID 목록."""
    return [v for v in [
        self.GOOGLE_CLIENT_ID,
        self.GOOGLE_CLIENT_ID_IOS,
        self.GOOGLE_CLIENT_ID_ANDROID,
    ] if v]

@property
def apple_allowed_audiences(self) -> list[str]:
    """Apple aud 검증에 허용할 audience 목록."""
    return [v for v in [
        self.APPLE_APP_BUNDLE_ID,
        self.APPLE_WEB_CLIENT_ID,
    ] if v]
```

---

## 7. 핵심 모듈 설계

### 7.1 OAuthVerificationService (oauth_verification_service.py)

**책임**: Google/Apple id_token의 JWKS 기반 RS256 서명 검증
**설계**: **단일 클래스** + `_PROVIDER_CONFIG` dict + `_verify_token()` 공통 private 메서드

> **설계 결정 (project-architect 합의)**:
> Google/Apple 공통 로직 90%+ 동일 → 단일 구현 클래스로 통합 (DRY).
> JWKS URL은 SSRF 방지를 위해 클래스 상수 고정. 테스트는 JwksCacheService mock 사용.

```python
"""OAuth 공급자 JWT 검증 서비스 — Google / Apple."""
from __future__ import annotations

import logging
from typing import Any

from jose import JWTError, jwt

from app.core.config import Settings
from app.core.exceptions import AuthErrors
from app.schemas.social_auth import OAuthUserInfo
from app.services.jwks_cache_service import JwksCacheService

logger = logging.getLogger(__name__)


class OAuthVerificationService:
    """Google/Apple OAuth2 id_token 검증 단일 구현체.

    provider별 차이(JWKS URL, issuer, audience, email 필수 여부)는
    _PROVIDER_CONFIG dict으로 관리. 검증 로직은 _verify_token()에서 공통 처리.
    """

    # SSRF 방지: JWKS URL 환경변수 노출 금지 — 클래스 상수 고정
    _PROVIDER_CONFIG: dict[str, dict[str, Any]] = {
        "google": {
            "jwks_url": "https://www.googleapis.com/oauth2/v3/certs",
            "issuers": frozenset({
                "accounts.google.com",
                "https://accounts.google.com",
            }),
            "require_email": True,
        },
        "apple": {
            "jwks_url": "https://appleid.apple.com/auth/keys",
            "issuers": frozenset({"https://appleid.apple.com"}),
            "require_email": False,
        },
    }

    def __init__(self, settings: Settings, jwks_cache: JwksCacheService) -> None:
        self._settings = settings
        self._jwks_cache = jwks_cache

    async def verify_google_token(self, id_token: str) -> OAuthUserInfo:
        """Google id_token RS256 검증 → OAuthUserInfo 반환.

        검증 항목: RS256 서명, iss, aud(google_allowed_audiences), exp, email_verified.

        Raises:
            AppError(INVALID_OAUTH_TOKEN): 서명/만료/iss/aud 불일치.
            AppError(OAUTH_EMAIL_REQUIRED): email 없음 또는 email_verified != true.
            AppError(OAUTH_PROVIDER_UNAVAILABLE): JWKS 서버 응답 실패.
        """
        payload = await self._verify_token(
            provider="google",
            id_token=id_token,
            allowed_audiences=self._settings.google_allowed_audiences,
        )
        if not payload.get("email") or not payload.get("email_verified"):
            raise AuthErrors.oauth_email_required()

        return OAuthUserInfo(
            provider="google",
            provider_id=payload["sub"],
            email=payload["email"],
            display_name=payload.get("name"),
            avatar_url=payload.get("picture"),
        )

    async def verify_apple_token(self, id_token: str) -> OAuthUserInfo:
        """Apple id_token RS256 검증 → OAuthUserInfo 반환.

        검증 항목: RS256 서명, iss, aud(apple_allowed_audiences), exp.
        email: private relay 이메일 허용, 없어도 허용.

        Raises:
            AppError(INVALID_OAUTH_TOKEN): 서명/만료/iss/aud 불일치.
            AppError(OAUTH_PROVIDER_UNAVAILABLE): JWKS 서버 응답 실패.
        """
        payload = await self._verify_token(
            provider="apple",
            id_token=id_token,
            allowed_audiences=self._settings.apple_allowed_audiences,
        )
        return OAuthUserInfo(
            provider="apple",
            provider_id=payload["sub"],
            email=payload.get("email"),
            display_name=None,
            avatar_url=None,
        )

    async def _verify_token(
        self,
        provider: str,
        id_token: str,
        allowed_audiences: list[str],
    ) -> dict[str, Any]:
        """공통 JWT 검증 로직: kid 추출 → JWKS 공개키 조회 → RS256 검증.

        Args:
            provider: "google" | "apple"
            id_token: 클라이언트로부터 받은 JWT.
            allowed_audiences: 허용할 aud 값 목록.

        Returns:
            검증된 JWT 페이로드 dict.

        Raises:
            AppError(INVALID_OAUTH_TOKEN): 검증 실패.
            AppError(OAUTH_PROVIDER_UNAVAILABLE): JWKS 조회 실패.
        """
        config = self._PROVIDER_CONFIG[provider]
        try:
            header = jwt.get_unverified_header(id_token)
            kid: str = header.get("kid", "")

            public_key = await self._jwks_cache.get_public_key(
                provider=provider,
                kid=kid,
                jwks_url=config["jwks_url"],
            )

            payload: dict[str, Any] = jwt.decode(
                id_token,
                public_key,
                algorithms=["RS256"],
                audience=allowed_audiences,
                issuer=list(config["issuers"]),
            )
        except AppError:
            raise
        except JWTError as e:
            logger.warning("oauth_token_invalid", provider=provider, error=str(e))
            raise AuthErrors.invalid_oauth_token()
        except Exception as e:
            logger.error("oauth_verify_unexpected", provider=provider, error=str(e))
            raise AuthErrors.invalid_oauth_token()

        return payload
```

**JWKS 캐시 전략**: **Redis** 기반 (인메모리 dict 사용 금지).

> **사유**: Uvicorn 멀티워커 환경에서 인메모리 캐시는 워커간 공유되지 않아 불필요한 JWKS 반복 조회 발생.
> Redis는 이미 의존성으로 존재하므로 추가 비용 없음. 캐시 키 형식: `oauth:jwks:{provider}`.

**JWKS 캐시 흐름**:
```
get_public_key(provider, kid) 호출
  │
  ├─ Redis GET oauth:jwks:{provider}
  │   ├─ HIT: JSON 파싱 → kid 매칭 공개키 반환
  │   └─ MISS:
  │       ├─ HTTP GET {JWKS_URL} (httpx.AsyncClient, timeout=5s)
  │       ├─ Redis SETEX oauth:jwks:{provider} {OAUTH_JWKS_CACHE_TTL} {json}
  │       └─ kid 매칭 공개키 반환
  │
  └─ kid 없음 (키 순환 감지):
      ├─ Redis DEL oauth:jwks:{provider}   ← 캐시 강제 무효화
      ├─ HTTP GET {JWKS_URL}               ← 재조회 (1회만)
      └─ 재조회 후에도 kid 없음 → AppError(INVALID_OAUTH_TOKEN)
```

**의존 라이브러리**: `python-jose[cryptography]` (RSA 키 파싱 + JWT 검증), `httpx` (JWKS fetch, 이미 의존성 존재 확인 필요)

### 7.2 JwksCacheService (jwks_cache_service.py)

**책임**: JWKS 공개키 Redis 캐시 + httpx 원격 조회

```python
"""JWKS 공개키 Redis 캐시 서비스."""
from __future__ import annotations

import json
import logging

import httpx
from redis.asyncio import Redis

from app.core.config import Settings
from app.core.exceptions import AuthErrors

logger = logging.getLogger(__name__)

_CACHE_KEY_PREFIX = "oauth:jwks"


class JwksCacheService:
    """JWKS 공개키 Redis 캐시.

    캐시 키: oauth:jwks:{provider}
    TTL: settings.OAUTH_JWKS_CACHE_TTL (기본 3600초)
    저장 형식: JWKS JSON 원문 string
    """

    def __init__(self, redis: Redis, settings: Settings) -> None:
        self._redis = redis
        self._settings = settings

    async def get_public_key(self, provider: str, kid: str, jwks_url: str) -> str:
        """JWKS에서 kid에 해당하는 공개키(PEM) 반환.

        캐시 미스 또는 kid 없음(키 순환) 시 원격 재조회 1회 수행.

        Args:
            provider: "google" | "apple"
            kid: JWT header의 kid 클레임.
            jwks_url: JWKS 조회 URL.

        Returns:
            PEM 형식 공개키 문자열.

        Raises:
            AppError(INVALID_OAUTH_TOKEN): kid에 해당하는 키 없음 (재시도 후에도).
            AppError(OAUTH_PROVIDER_UNAVAILABLE): JWKS HTTP 조회 실패.
        """
        cache_key = f"{_CACHE_KEY_PREFIX}:{provider}"

        # 1차 시도: 캐시 조회
        key = await self._find_key(cache_key, kid)
        if key:
            return key

        # 캐시 미스 또는 kid 없음 → 원격 재조회
        jwks = await self._fetch_and_cache(cache_key, jwks_url)
        key = self._extract_key(jwks, kid)
        if key is None:
            raise AuthErrors.invalid_oauth_token()
        return key

    async def _find_key(self, cache_key: str, kid: str) -> str | None:
        raw = await self._redis.get(cache_key)
        if raw is None:
            return None
        jwks = json.loads(raw)
        return self._extract_key(jwks, kid)

    async def _fetch_and_cache(self, cache_key: str, jwks_url: str) -> dict:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(jwks_url)
                resp.raise_for_status()
                jwks = resp.json()
        except Exception as e:
            logger.error("jwks_fetch_failed", url=jwks_url, error=str(e))
            raise AuthErrors.oauth_provider_unavailable()

        await self._redis.setex(
            cache_key,
            self._settings.OAUTH_JWKS_CACHE_TTL,
            json.dumps(jwks),
        )
        return jwks

    @staticmethod
    def _extract_key(jwks: dict, kid: str) -> str | None:
        """JWKS JSON에서 kid 일치 키의 PEM 공개키 추출. 없으면 None."""
        from jose.backends import RSAKey  # python-jose
        for key_data in jwks.get("keys", []):
            if key_data.get("kid") == kid:
                return RSAKey(key_data, algorithm="RS256").public_key().to_pem().decode()
        return None

    async def invalidate(self, provider: str) -> None:
        """캐시 강제 무효화 (키 순환 감지 시 사용)."""
        await self._redis.delete(f"{_CACHE_KEY_PREFIX}:{provider}")
```

### 7.3 SocialAccountRepository (social_account_repository.py)

**책임**: UserSocialAccount 테이블 CRUD

```python
class SocialAccountRepository:
    """UserSocialAccount DB 접근 계층."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def get_by_provider_id(self, provider: str, provider_id: str) -> UserSocialAccount | None:
        """provider + provider_id로 소셜 계정 조회."""
        ...

    async def get_by_user_id(self, user_id: uuid.UUID) -> list[UserSocialAccount]:
        """사용자의 모든 소셜 계정 조회."""
        ...

    async def create(
        self, user_id: uuid.UUID, provider: str, provider_id: str, provider_email: str | None
    ) -> UserSocialAccount:
        """소셜 계정 연동 레코드 생성."""
        ...
```

### 7.4 SocialAuthService (social_auth_service.py)

**책임**: 소셜 로그인 전체 오케스트레이션 (id_token 검증 제외)

```python
"""소셜 로그인 비즈니스 로직 오케스트레이션."""
from __future__ import annotations

import uuid
import logging
from datetime import datetime, timezone

from app.core import security
from app.core.config import Settings
from app.core.exceptions import AuthErrors
from app.models.user import User
from app.repositories.social_account_repository import SocialAccountRepository
from app.repositories.user_repository import UserRepository
from app.schemas.auth import TokenPair
from app.schemas.social_auth import AppleUserData, OAuthUserInfo
from app.services.auth_cache_service import AuthCacheService

logger = logging.getLogger(__name__)


class SocialAuthService:
    """소셜 로그인 비즈니스 로직.

    id_token 검증은 OAuth 서비스(Google/Apple)에서 수행.
    이 서비스는 OAuthUserInfo를 받아 DB 조회/생성/병합 + JWT 발급만 담당.
    """

    def __init__(
        self,
        user_repo: UserRepository,
        social_repo: SocialAccountRepository,
        cache: AuthCacheService,
        settings: Settings,
    ) -> None:
        self._user_repo = user_repo
        self._social_repo = social_repo
        self._cache = cache
        self._settings = settings

    async def social_login(
        self,
        oauth_info: OAuthUserInfo,
        apple_user: AppleUserData | None = None,
    ) -> tuple[User, TokenPair, bool]:
        """소셜 로그인 처리 → (User, TokenPair, is_new_user) 반환.

        Args:
            oauth_info: OAuth 검증 서비스가 반환한 표준화된 사용자 정보.
            apple_user: Apple 최초 로그인 시 클라이언트가 전달한 사용자 데이터 (선택).

        Returns:
            (User, TokenPair, is_new_user) 튜플.

        Raises:
            AppError(ACCOUNT_DELETED): 이메일 병합 대상 계정이 삭제 예약 상태.

        처리 흐름:
            [A] social_repo.get_by_provider(provider, provider_id) → 존재
                → 연결된 User 로드 → JWT 발급 (is_new_user=False)
            [B] 소셜 계정 없음 + email 있음 + user_repo.get_by_email(email) → 존재
                → 소셜 계정 병합(UserSocialAccount 생성) → JWT 발급 (is_new_user=False)
                → 기존 User의 email_verified_at이 None이면 now()로 업데이트
            [C] 소셜 계정 없음 + 기존 User 없음
                → 신규 User 생성 + UserSocialAccount 생성 → JWT 발급 (is_new_user=True)
        """
        # [A] 기존 소셜 계정 조회
        social_account = await self._social_repo.get_by_provider(
            oauth_info.provider, oauth_info.provider_id
        )
        if social_account is not None:
            user = await self._user_repo.get_by_id(social_account.user_id)
            if user is None or user.soft_deleted_at is not None:
                raise AuthErrors.account_deleted()
            tokens = await self._issue_tokens(user)
            return user, tokens, False

        # [B] 이메일 기반 기존 계정 병합
        if oauth_info.email:
            existing_user = await self._user_repo.get_by_email(oauth_info.email)
            if existing_user is not None:
                if existing_user.soft_deleted_at is not None:
                    raise AuthErrors.account_deleted()
                await self._social_repo.create(
                    user_id=existing_user.id,
                    provider=oauth_info.provider,
                    provider_id=oauth_info.provider_id,
                    provider_email=oauth_info.email,
                )
                # 이메일 미인증 상태라면 소셜 로그인으로 인증 처리
                if existing_user.email_verified_at is None:
                    await self._user_repo.update_email_verified(existing_user.id)
                tokens = await self._issue_tokens(existing_user)
                return existing_user, tokens, False

        # [C] 신규 사용자 생성
        nickname = self._derive_nickname(oauth_info, apple_user)
        new_user = await self._user_repo.create_social_user(
            email=oauth_info.email or self._generate_placeholder_email(oauth_info),
            nickname=nickname,
            avatar_url=oauth_info.avatar_url,
        )
        await self._social_repo.create(
            user_id=new_user.id,
            provider=oauth_info.provider,
            provider_id=oauth_info.provider_id,
            provider_email=oauth_info.email,
        )
        tokens = await self._issue_tokens(new_user)
        return new_user, tokens, True

    async def _issue_tokens(self, user: User) -> TokenPair:
        """JWT Access + Refresh 발급 (AuthService.login 토큰 발급 패턴 동일)."""
        user_id_str = str(user.id)
        client_id = str(uuid.uuid4())

        access_token = security.create_access_token(user_id=user_id_str, email=user.email)
        refresh_token = security.create_refresh_token(user_id=user_id_str, client_id=client_id)
        token_hash = security.hash_token(refresh_token)

        await self._cache.store_refresh_token(user_id_str, client_id, token_hash)

        return TokenPair(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=self._settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        )

    @staticmethod
    def _derive_nickname(
        oauth_info: OAuthUserInfo, apple_user: AppleUserData | None
    ) -> str | None:
        """소셜 정보에서 초기 닉네임 도출. 없으면 None (온보딩에서 설정)."""
        # Apple: apple_user.name.last_name + first_name
        if apple_user and apple_user.name:
            parts = [
                apple_user.name.last_name or "",
                apple_user.name.first_name or "",
            ]
            name = "".join(parts).strip()
            if name:
                return name[:50]
        # Google: display_name 클레임
        if oauth_info.display_name:
            return oauth_info.display_name[:50]
        return None

    @staticmethod
    def _generate_placeholder_email(oauth_info: OAuthUserInfo) -> str:
        """Apple 이메일 없는 경우 내부 플레이스홀더 이메일 생성.

        실제 이메일 발송에 사용되지 않음 — DB unique 제약 만족용.
        """
        return f"{oauth_info.provider_id}@{oauth_info.provider}.social"
```

### 7.5 UserRepository 확장

기존 `user_repository.py`에 메서드 추가:

```python
async def create_social_user(
    self,
    *,
    email: str,
    nickname: str | None = None,
    avatar_url: str | None = None,
) -> User:
    """소셜 로그인 전용 User 생성.

    Args:
        email: OAuth 공급자에서 확인된 이메일 (또는 플레이스홀더).
        nickname: 표시 이름 (없으면 None, 온보딩에서 설정).
        avatar_url: 프로필 이미지 URL (Google만 제공).

    Returns:
        생성된 User.

    특이사항:
        - password_hash=None (소셜 전용 계정, 비밀번호 로그인 불가)
        - email_verified_at=now() (OAuth가 이메일 검증 보장)
    """
    now = datetime.now(timezone.utc)
    user = User(
        email=email,
        password_hash=None,
        nickname=nickname,
        avatar_url=avatar_url,
        email_verified_at=now,
    )
    self._db.add(user)
    await self._db.flush()
    await self._db.refresh(user)
    return user
```

> **password_hash=None 처리**: 기존 `login()` 메서드에서 `user.password_hash`가 None이면
> `_DUMMY_HASH`로 타이밍 어택 방지 로직이 이미 구현되어 있음. 변경 불필요.

---

## 8. 에러 처리

### 8.1 AuthErrors 추가 메서드 (exceptions.py 확장)

v1-5 `AuthErrors` 팩토리 패턴을 그대로 따름. **별도 `SocialAuthErrors` 클래스 생성 금지** — 모든 인증 에러는 `AuthErrors` 하나로 통합한다.

```python
class AuthErrors:
    # ... 기존 메서드 유지 ...

    @staticmethod
    def invalid_oauth_token() -> AppError:
        """Google/Apple id_token 서명 검증 실패 또는 만료."""
        return AppError("INVALID_OAUTH_TOKEN", "유효하지 않은 OAuth 토큰입니다.", 401)

    @staticmethod
    def oauth_email_required() -> AppError:
        """OAuth 토큰에 이메일이 포함되지 않아 처리 불가 (Google 이메일 공개 미허용)."""
        return AppError(
            "OAUTH_EMAIL_REQUIRED",
            "소셜 로그인에 이메일 제공이 필요합니다. 설정에서 이메일 공개 권한을 허용해주세요.",
            422,
        )

    @staticmethod
    def oauth_provider_unavailable() -> AppError:
        """JWKS 조회 실패 등 OAuth 공급자 서버 오류."""
        return AppError(
            "OAUTH_PROVIDER_UNAVAILABLE",
            "소셜 인증 서버에 일시적으로 연결할 수 없습니다. 잠시 후 재시도해주세요.",
            502,
        )
```

### 8.2 에러 코드 전체 목록

| 에러 코드 | HTTP | 발생 조건 |
|-----------|------|---------|
| `INVALID_OAUTH_TOKEN` | 401 | id_token 서명/만료/iss/aud 불일치 |
| `OAUTH_EMAIL_REQUIRED` | 422 | Google 토큰에 이메일 없음 |
| `OAUTH_PROVIDER_UNAVAILABLE` | 502 | JWKS fetch 실패 (타임아웃, 네트워크 오류) |
| `ACCOUNT_DELETED` | 410 | 이메일 병합 대상 계정이 soft_deleted_at 설정됨 (기존 재사용) |

> **설계 결정**: `SOCIAL_ACCOUNT_ALREADY_LINKED` (409) 에러는 MVP에서 제외.
> `uq_social_provider_id` DB UniqueConstraint가 중복 삽입을 차단하고,
> 계정 연동 관리 기능은 v2 이후 별도 엔드포인트에서 다룬다.

---

## 9. 보안 고려사항

### 9.1 id_token 검증 체크리스트

- [ ] JWKS 공개키로 RS256 서명 검증 (HS256 fallback 절대 금지)
- [ ] `iss` (issuer) 화이트리스트 검증
- [ ] `aud` (audience) 자사 Client ID 일치 확인
- [ ] `exp` 만료 시간 검증
- [ ] Google: `email_verified` 클레임 true 확인
- [ ] Apple: 첫 로그인 시 `user` 객체에서만 이름 추출 (이후 미제공)

### 9.2 JWKS 캐시 보안

- 캐시 TTL: 1시간 (`OAUTH_JWKS_CACHE_TTL`, 기본값)
- JWKS URL은 Settings 환경변수로 관리하나, **프로덕션 배포 시 화이트리스트 검증** 필요
  - 허용: `*.googleapis.com`, `appleid.apple.com` 도메인만
  - 테스트 환경에서만 Mock 서버 URL 허용
- httpx 요청 시 `verify=True` (TLS 검증 비활성화 금지)
- Redis 캐시 키는 `oauth:jwks:{provider}` — provider 값은 코드 내 고정값만 허용 ("google"|"apple")

### 9.3 계정 병합 보안

- 이메일 일치 시 자동 병합은 provider가 email_verified를 보장하는 경우만 허용
- Google: `email_verified` 클레임 확인
- Apple: Apple이 보장 (인증된 이메일만 제공)
- 병합 시 기존 비밀번호/2FA 설정은 유지

---

## 10. API 엔드포인트 규격

### 10.1 POST /api/v1/auth/social/google

**라우터 파일**: `server/app/api/v1/social_auth.py` (auth.py 아님, SRP 원칙)

**요청:**
```json
{
  "id_token": "eyJhbGciOiJSUzI1NiIs..."
}
```

**응답 200 OK (기존 사용자 / 이메일 병합):**
```json
{
  "data": {
    "user": {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "email": "user@gmail.com",
      "nickname": "user",
      "avatar_url": "https://lh3.googleusercontent.com/...",
      "language": "ko",
      "theme": "system",
      "price_color_style": "korean",
      "ai_trading_enabled": false,
      "is_2fa_enabled": false,
      "email_verified": true,
      "created_at": "2026-03-06T12:00:00Z"
    },
    "tokens": {
      "access_token": "eyJ...",
      "refresh_token": "eyJ...",
      "token_type": "Bearer",
      "expires_in": 1800
    },
    "is_new_user": false
  },
  "error": null,
  "meta": { "timestamp": "2026-03-06T12:00:00Z" }
}
```

**응답 200 OK (신규 사용자):** 동일 구조, `is_new_user: true`

> **HTTP 상태 코드**: 신규/기존 구분 없이 **200**. `is_new_user` 플래그로 클라이언트가 온보딩 처리.
> (201 사용 시 클라이언트가 Created/OK를 구분해야 하는 불필요한 복잡성 추가됨)

**에러 응답:**
```json
{
  "data": null,
  "error": {
    "code": "INVALID_OAUTH_TOKEN",
    "message": "유효하지 않은 OAuth 토큰입니다."
  },
  "meta": { "timestamp": "2026-03-06T12:00:00Z" }
}
```

| HTTP | code | 사유 |
|------|------|------|
| 401 | `INVALID_OAUTH_TOKEN` | id_token 서명/만료/iss/aud 불일치 |
| 422 | `OAUTH_EMAIL_REQUIRED` | Google 토큰에 이메일 없음 |
| 410 | `ACCOUNT_DELETED` | 이메일 일치 계정이 삭제 예약 상태 |
| 502 | `OAUTH_PROVIDER_UNAVAILABLE` | Google JWKS 서버 응답 실패 |

---

### 10.2 POST /api/v1/auth/social/apple

**요청:**
```json
{
  "id_token": "eyJhbGciOiJSUzI1NiIs...",
  "user": {
    "name": {
      "first_name": "길동",
      "last_name": "홍"
    }
  }
}
```

> **`user` 필드 규칙**: Apple이 **최초 로그인 시에만** 클라이언트에 전달. 이후 로그인에서는 `null`.
> 서버는 `user` 값이 `null`이어도 정상 처리해야 함.

**응답**: Google과 동일 구조

| HTTP | code | 사유 |
|------|------|------|
| 401 | `INVALID_OAUTH_TOKEN` | id_token 서명/만료/iss/aud 불일치 |
| 410 | `ACCOUNT_DELETED` | 이메일 일치 계정이 삭제 예약 상태 |
| 502 | `OAUTH_PROVIDER_UNAVAILABLE` | Apple JWKS 서버 응답 실패 |

---

### 10.3 엔드포인트 구현 예시

```python
# server/app/api/v1/social_auth.py
"""소셜 로그인 API 엔드포인트."""
from __future__ import annotations

import logging

from fastapi import APIRouter

from app.core.deps import OAuthVerificationServiceDep, SocialAuthServiceDep
from app.schemas.auth import UserResponse
from app.schemas.common import ApiResponse
from app.schemas.social_auth import (
    AppleSocialLoginRequest,
    GoogleSocialLoginRequest,
    SocialLoginResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post(
    "/google",
    response_model=ApiResponse[SocialLoginResponse],
    summary="Google 소셜 로그인",
    description="Google OAuth2 id_token 검증 후 JWT 발급. 신규 사용자는 자동 가입 처리.",
)
async def google_social_login(
    body: GoogleSocialLoginRequest,
    oauth_svc: OAuthVerificationServiceDep,
    social_auth: SocialAuthServiceDep,
) -> ApiResponse[SocialLoginResponse]:
    oauth_info = await oauth_svc.verify_google_token(body.id_token)
    user, tokens, is_new_user = await social_auth.social_login(oauth_info)
    return ApiResponse(data=SocialLoginResponse(
        user=UserResponse.from_user(user),
        tokens=tokens,
        is_new_user=is_new_user,
    ))


@router.post(
    "/apple",
    response_model=ApiResponse[SocialLoginResponse],
    summary="Apple 소셜 로그인",
    description="Apple Sign In id_token 검증 후 JWT 발급. 최초 로그인 시 user 정보 포함.",
)
async def apple_social_login(
    body: AppleSocialLoginRequest,
    oauth_svc: OAuthVerificationServiceDep,
    social_auth: SocialAuthServiceDep,
) -> ApiResponse[SocialLoginResponse]:
    oauth_info = await oauth_svc.verify_apple_token(body.id_token)
    user, tokens, is_new_user = await social_auth.social_login(
        oauth_info, apple_user=body.user
    )
    return ApiResponse(data=SocialLoginResponse(
        user=UserResponse.from_user(user),
        tokens=tokens,
        is_new_user=is_new_user,
    ))
```

---

## 11. 스키마 정의

**파일**: `server/app/schemas/social_auth.py` (auth.py에 추가하지 않음 — SRP 원칙)

### 11.1 요청 스키마

```python
"""소셜 로그인 관련 Pydantic 스키마."""
from __future__ import annotations

from pydantic import BaseModel, Field


class AppleUserName(BaseModel):
    """Apple 최초 로그인 시 전달되는 이름 정보.

    Apple 클라이언트 SDK는 snake_case로 전달하지 않으므로
    model_config alias 설정으로 camelCase 요청도 허용.
    """

    model_config = {"populate_by_name": True}

    first_name: str | None = Field(default=None, alias="firstName", max_length=50)
    last_name: str | None = Field(default=None, alias="lastName", max_length=50)


class AppleUserData(BaseModel):
    """Apple 최초 로그인 시 클라이언트가 함께 전달하는 사용자 데이터.

    Apple은 최초 로그인 시에만 이 데이터를 클라이언트에 전달하므로
    서버는 즉시 저장해야 함. 이후 로그인에서는 null.
    """

    name: AppleUserName | None = None


class GoogleSocialLoginRequest(BaseModel):
    """Google 소셜 로그인 요청."""

    id_token: str = Field(min_length=1, description="Google OAuth2 id_token (JWT)")


class AppleSocialLoginRequest(BaseModel):
    """Apple 소셜 로그인 요청."""

    id_token: str = Field(min_length=1, description="Apple Sign In id_token (JWT)")
    user: AppleUserData | None = Field(
        default=None,
        description="최초 로그인 시에만 Apple이 클라이언트에 전달하는 사용자 정보",
    )
```

### 11.2 응답 스키마

```python
from app.schemas.auth import LoginResponse, TokenPair, UserResponse


class SocialLoginResponse(BaseModel):
    """소셜 로그인 응답.

    LoginResponse와 동일 구조에 is_new_user 플래그 추가.
    클라이언트는 is_new_user=true 시 닉네임 설정 온보딩 화면으로 안내.
    """

    user: UserResponse
    tokens: TokenPair
    is_new_user: bool = Field(
        description="True: 소셜 계정으로 최초 가입, False: 기존 계정 로그인 또는 병합"
    )
```

> **설계 결정**: `LoginResponse` 상속 대신 독립 클래스로 정의.
> 향후 소셜 로그인 전용 필드 추가 시 `LoginResponse` 변경 없이 확장 가능.

### 11.3 내부 DTO (dataclass)

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class OAuthUserInfo:
    """OAuth 공급자 JWT 검증 후 추출된 표준화된 사용자 정보.

    서비스 레이어는 provider 종류와 무관하게 이 DTO만 다룬다.
    """

    provider: str           # "google" | "apple"
    provider_id: str        # JWT sub claim (공급자 내 고유 ID)
    email: str | None       # 이메일 (Apple private relay 가능, 없을 수도 있음)
    display_name: str | None  # 표시 이름 (없으면 None)
    avatar_url: str | None  # 프로필 이미지 URL (Google만 picture 클레임 제공)
```

### 11.4 스키마 파일 배치 요약

| 스키마 | 파일 | 비고 |
|--------|------|------|
| `GoogleSocialLoginRequest` | `schemas/social_auth.py` | 신규 |
| `AppleSocialLoginRequest` | `schemas/social_auth.py` | 신규 |
| `AppleUserData`, `AppleUserName` | `schemas/social_auth.py` | 신규 |
| `SocialLoginResponse` | `schemas/social_auth.py` | 신규 |
| `OAuthUserInfo` | `schemas/social_auth.py` | dataclass, 신규 |
| `UserResponse`, `TokenPair` | `schemas/auth.py` | 기존 재사용 |

---

## 12. 테스트 전략

<!-- code-architect 작성 영역 -->

### 12.1 단위 테스트

| 테스트 파일 | 대상 | 주요 시나리오 |
|------------|------|--------------|
| `test_oauth_verification_service.py` | OAuthVerificationService | 유효 토큰, 만료 토큰, 잘못된 서명, JWKS 캐시 |
| `test_social_auth_service.py` | SocialAuthService | 신규 사용자, 기존 소셜 사용자, 이메일 병합, 삭제된 계정 |

### 12.2 통합 테스트

| 테스트 파일 | 대상 | 주요 시나리오 |
|------------|------|--------------|
| `test_social_login_api.py` | API 엔드포인트 | E2E 플로우, 에러 응답, Rate Limiting |

### 12.3 목킹 전략

- `OAuthVerificationService`: JwksCacheService를 목킹, 테스트용 RSA 키쌍으로 id_token 생성
- `httpx.AsyncClient`: JWKS 엔드포인트 응답 목킹
- DB: 기존 테스트 픽스처 패턴 사용 (AsyncSession)

---

## 13. 서브태스크 의존성 그래프

```
[1] OAuth2 설정 (config.py)
 │
 ├──> [2] Google/Apple JWT 검증 서비스 (oauth_verification_service.py + jwks_cache_service.py)
 │         │
[3] SocialAccountRepository ─────┤
[4] UserRepository 확장 ─────────┤
                                  │
                                  ▼
                    [5] SocialAuthService (오케스트레이션)
                                  │
                    [7] JWT 토큰 서비스 확장 ──┤
                                  │            │
                                  ▼            │
                    [6] API 엔드포인트 ────────┤
                                  │            │
                    [8] 계정 병합 로직 ─────────┤
                                               │
                                               ▼
                                  [9] E2E 테스트
                                               │
                                               ▼
                                  [10] 코드 리뷰
```

### 13.1 병렬 실행 가능 태스크

- **Phase 1** (병렬): [1], [3], [4] — 독립적, 동시 진행 가능
- **Phase 2** (병렬): [2], [7] — Phase 1 완료 후
- **Phase 3**: [5] — Phase 2 완료 후
- **Phase 4** (병렬): [6], [8] — Phase 3 완료 후
- **Phase 5**: [9] — Phase 4 완료 후
- **Phase 6**: [10] — Phase 5 완료 후

---

## 14. 구현 시 주의사항

### 14.1 Apple Sign-In 특이사항

- Apple은 **첫 로그인 시에만** 사용자 이름을 제공함 → 클라이언트가 `user` 객체를 서버에 전달해야 함
- 이후 로그인에서는 `sub` (고유 ID)만 제공
- 사용자가 Apple ID 설정에서 "이메일 숨기기" 선택 시 relay 이메일 제공 (`xxx@privaterelay.appleid.com`)

### 14.2 닉네임 자동 생성

- 소셜 로그인 신규 사용자: 이메일 로컬 파트 사용 (예: `user@gmail.com` → `user`)
- 닉네임 중복 시: `user_1234` (랜덤 4자리 suffix)
- Apple에서 이름 제공 시: `lastName + firstName` 사용

### 14.3 기존 AuthService와의 관계

- `SocialAuthService`는 `AuthService`와 **별도 서비스**로 구현 (SRP)
- JWT 발급 로직은 `security.py`의 `create_access_token()`, `create_refresh_token()` 직접 사용
- Refresh Token 저장은 `AuthCacheService.store_refresh_token()` 재사용

---

## 15. 구현 현재 상태

**상태: 구현 완료 (2026-03-06)**

### 15.1 구현 파일 목록

| 파일 | 설명 |
|------|------|
| `server/app/schemas/social_auth.py` | Google/Apple 요청·응답 스키마, OAuthUserInfo dataclass |
| `server/app/services/jwks_cache_service.py` | JWKS Redis 캐싱, httpx fetch, kid 회전 감지 |
| `server/app/services/oauth_verification_service.py` | OAuthVerificationService (_PROVIDER_CONFIG 패턴, RS256) |
| `server/app/services/social_auth_service.py` | 3단계 소셜 로그인 플로우 (기존 소셜→이메일 병합→신규) |
| `server/app/repositories/social_account_repository.py` | UserSocialAccount CRUD |
| `server/app/api/v1/social_auth.py` | POST /google, /apple 엔드포인트 |
| `server/tests/integration/test_social_auth_api.py` | 통합 테스트 14케이스 |
| `docs/tasks/v1-6-social-login-oauth2-plan.md` | 설계서 (본 문서) |

### 15.2 수정된 기존 파일

| 파일 | 변경 내용 |
|------|----------|
| `server/app/core/config.py` | Google/Apple OAuth2 환경변수 + audience 프로퍼티 |
| `server/app/core/exceptions.py` | SOCIAL_AUTH_FAILED, OAUTH_TOKEN_INVALID, OAUTH_PROVIDER_ERROR 추가 |
| `server/app/core/deps.py` | 소셜 인증 DI 팩토리 + Annotated 타입 별칭 |
| `server/app/repositories/user_repository.py` | create_social_user() 메서드 추가 |
| `server/app/api/v1/__init__.py` | social_auth 라우터 등록 |

### 15.3 코드 리뷰 결과

- CRITICAL 1건 수정 완료 (PyJWT verify_at_hash 파라미터 타입 오류)
- WARNING 3건 수정 완료
- INFO 2건 수정 완료
- 최종 승인 완료

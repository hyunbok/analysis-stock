# v1-5 JWT 인증 시스템 구현 - 설계서

> **작성**: code-architect (API 스키마/인터페이스/에러코드), project-architect (파일 구조/시퀀스)
> **대상 태스크**: v1-5 — 회원가입, 로그인, JWT 토큰 관리, 인증 미들웨어
> **현재 상태**: 전체 구현 완료. 코드 리뷰 CRITICAL 1건(Rate Limit) + WARNING 6건 수정 후 최종 승인. 신규 7파일 생성, 수정 5파일, 통합 테스트 27케이스 포함.

---

## 1. 개요

이메일 기반 회원가입(6자리 인증 코드 발송), JWT Access/Refresh 토큰 발급·갱신, 로그아웃, 프로필 조회·수정, 계정 삭제(30일 유예)를 구현한다.

**의존성**: v1-4 (FastAPI 미들웨어/에러 핸들러) 완료.

**기존 코드 활용**:
- `server/app/services/auth_cache_service.py` — Refresh Token·이메일 인증 코드 Redis 관리
- `server/app/core/redis_keys.py` — `RedisKey`, `RedisTTL` 상수
- `server/app/schemas/error.py` — `ErrorResponse`, `ErrorBody`, `ErrorDetail`
- `server/app/models/user.py` — `User` 모델 (soft_deleted 필드 추가 필요)

---

## 2. 파일 구조

### 2.1 신규 파일

```
server/app/
├── core/
│   ├── security.py              # ST2: JWT 토큰 생성/검증, bcrypt 해싱
│   └── exceptions.py            # ST4: AppError, AuthErrors 도메인 에러
├── schemas/
│   ├── auth.py                  # ST1: 인증 요청/응답 Pydantic 스키마
│   └── common.py (수정)         # ST1: ApiResponse 제네릭 래퍼 추가
├── repositories/
│   └── user_repository.py       # ST4: User CRUD (AsyncSession)
├── services/
│   ├── auth_service.py          # ST4: 인증 비즈니스 로직 오케스트레이션
│   └── email_service.py         # ST3: SMTP 이메일 발송 (aiosmtplib)
└── api/v1/
    └── auth.py                  # ST6,7: 인증 + 프로필 API 엔드포인트

server/tests/
├── unit/
│   ├── test_security.py         # JWT/bcrypt 단위 테스트
│   ├── test_auth_service.py     # AuthService 단위 테스트 (mock repo/cache)
│   └── test_email_service.py    # EmailService 단위 테스트 (mock SMTP)
└── integration/
    └── test_auth_api.py         # ST8: 인증 API 통합 테스트
```

### 2.2 수정 파일

| 파일 | 변경 내용 | ST# |
|------|----------|-----|
| `server/app/models/user.py` | `soft_deleted_at` 필드 + 인덱스 추가 | 1 |
| `server/app/core/config.py` | SMTP 설정 7개 추가 | 3 |
| `server/app/core/deps.py` | `CurrentUser`, `get_current_user`, 서비스 DI 팩토리 추가 | 5 |
| `server/app/api/v1/__init__.py` | auth router 주석 해제 및 등록 | 6 |
| `server/app/middleware/error_handler.py` | `AppError` exception handler 추가 | 8 |

### 2.3 의존성 흐름도 (DI 체인)

```
┌─────────────────────────────────────────────────────────────────────┐
│  API Layer: auth.py                                                  │
│                                                                      │
│  register/login/verify-email/refresh (공개)                          │
│    ├── DbSession ─────────────────────┐                              │
│    ├── RedisClient ──────────┐        │                              │
│    └── AppSettings ──┐       │        │                              │
│                      ▼       ▼        ▼                              │
│               ┌──────────────────────────────┐                       │
│               │     get_auth_service()       │                       │
│               │  ┌─────────────────────────┐ │                       │
│               │  │ AuthService             │ │                       │
│               │  │  ├── UserRepository(db) │ │                       │
│               │  │  ├── AuthCacheService(r)│ │                       │
│               │  │  ├── EmailService(s)    │ │                       │
│               │  │  └── Settings           │ │                       │
│               │  └─────────────────────────┘ │                       │
│               └──────────────────────────────┘                       │
│                                                                      │
│  logout/me/profile/delete (인증 필요)                                │
│    ├── CurrentUser ──► get_current_user()                             │
│    │                    ├── OAuth2PasswordBearer → Bearer token       │
│    │                    ├── decode_access_token() (security.py)       │
│    │                    └── UserRepository.get_by_id() → User        │
│    └── get_auth_service() (위와 동일)                                │
└─────────────────────────────────────────────────────────────────────┘
```

**DI 팩토리 함수 (deps.py에 추가):**

```python
def get_user_repository(db: DbSession) -> UserRepository:
    return UserRepository(db)

def get_email_service(settings: AppSettings) -> EmailService:
    return EmailService(settings)

def get_auth_cache_service(redis: RedisClient) -> AuthCacheService:
    return AuthCacheService(redis)

def get_auth_service(
    user_repo: UserRepository = Depends(get_user_repository),
    auth_cache: AuthCacheService = Depends(get_auth_cache_service),
    email_svc: EmailService = Depends(get_email_service),
    settings: Settings = Depends(get_settings),
) -> AuthService:
    return AuthService(user_repo, auth_cache, email_svc, settings)

# Type aliases
AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]
CurrentUser = Annotated[User, Depends(get_current_user)]
CurrentUserOptional = Annotated[User | None, Depends(get_current_user_optional)]
```

---

## 3. User 모델 변경사항

### 3.1 추가 필드 (`server/app/models/user.py`)

```python
soft_deleted_at: Mapped[datetime | None] = mapped_column(
    DateTime(timezone=True), nullable=True, index=True
)
```

- `soft_deleted_at IS NOT NULL` → 삭제 예약 상태
- 30일 후 Celery 태스크가 hard delete 수행
- 로그인 시 `soft_deleted_at IS NOT NULL`이면 `ACCOUNT_DELETED` 에러 반환

### 3.2 인덱스 추가

```python
__table_args__ = (
    Index("ix_users_created_at", "created_at"),
    Index("ix_users_soft_deleted_at", "soft_deleted_at"),  # 추가
)
```

---

## 4. Settings 추가 항목 (`server/app/core/config.py`)

```python
# SMTP (이메일 발송)
SMTP_HOST: str = "smtp.gmail.com"
SMTP_PORT: int = 587
SMTP_USER: str = ""
SMTP_PASSWORD: str = ""
SMTP_FROM_EMAIL: str = "noreply@cointrader.io"
SMTP_FROM_NAME: str = "CoinTrader"
SMTP_STARTTLS: bool = True
```

---

## 5. Pydantic 스키마 (`server/app/schemas/auth.py`)

### 5.1 요청 스키마

```python
class RegisterRequest(BaseModel):
    """회원가입 요청."""

    email: EmailStr
    password: str = Field(min_length=8, max_length=100)
    nickname: str = Field(min_length=2, max_length=50)


class VerifyEmailRequest(BaseModel):
    """이메일 인증 코드 확인 요청."""

    email: EmailStr
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


class LoginRequest(BaseModel):
    """로그인 요청."""

    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    """토큰 갱신 요청."""

    refresh_token: str


class LogoutRequest(BaseModel):
    """로그아웃 요청."""

    refresh_token: str


class UpdateProfileRequest(BaseModel):
    """프로필 수정 요청 — 모든 필드 선택적."""

    nickname: str | None = Field(default=None, min_length=2, max_length=50)
    language: str | None = Field(default=None, pattern=r"^(ko|en)$")
    theme: str | None = Field(default=None, pattern=r"^(light|dark|system)$")
    price_color_style: str | None = Field(default=None, pattern=r"^(korean|western)$")
```

### 5.2 응답 스키마

```python
class TokenPair(BaseModel):
    """Access + Refresh 토큰 쌍."""

    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_in: int  # access token 만료까지 초


class UserResponse(BaseModel):
    """사용자 정보 응답."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    nickname: str | None
    avatar_url: str | None
    language: str
    theme: str
    price_color_style: str
    ai_trading_enabled: bool
    is_2fa_enabled: bool
    email_verified: bool  # email_verified_at IS NOT NULL
    created_at: datetime


class RegisterResponse(BaseModel):
    """회원가입 응답."""

    message: str = "인증 코드가 이메일로 발송되었습니다."
    email: str


class VerifyEmailResponse(BaseModel):
    """이메일 인증 완료 응답."""

    message: str = "이메일 인증이 완료되었습니다."


class LoginResponse(BaseModel):
    """로그인 응답."""

    user: UserResponse
    tokens: TokenPair


class RefreshResponse(BaseModel):
    """토큰 갱신 응답."""

    tokens: TokenPair


class LogoutResponse(BaseModel):
    """로그아웃 응답."""

    message: str = "로그아웃되었습니다."


class ProfileUpdateResponse(BaseModel):
    """프로필 수정 응답."""

    user: UserResponse


class AccountDeleteResponse(BaseModel):
    """계정 삭제 예약 응답."""

    message: str = "계정 삭제가 예약되었습니다. 30일 후 영구 삭제됩니다."
    scheduled_delete_at: datetime
```

### 5.3 표준 응답 래퍼 (`server/app/schemas/common.py`)

```python
from typing import Generic, TypeVar
from datetime import datetime, timezone
from pydantic import BaseModel, Field

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    """표준 API 성공 응답 포맷."""

    data: T
    error: None = None
    meta: dict = Field(default_factory=lambda: {
        "timestamp": datetime.now(timezone.utc).isoformat()
    })
```

**사용 예시**:
```python
# 엔드포인트에서
return ApiResponse(data=LoginResponse(user=user_resp, tokens=tokens))
```

---

## 6. JWT 토큰 구조

### 6.1 Access Token 페이로드

```json
{
  "sub": "user_id (UUID string)",
  "type": "access",
  "email": "user@example.com",
  "iat": 1234567890,
  "exp": 1234569690
}
```

### 6.2 Refresh Token 페이로드

```json
{
  "sub": "user_id (UUID string)",
  "type": "refresh",
  "client_id": "UUID string (기기 세션 식별자)",
  "iat": 1234567890,
  "exp": 1235777890
}
```

**`client_id`**: 로그인 시 서버가 생성하는 UUID. Redis 키 `auth:refresh:{user_id}:{client_id}`에 refresh token hash를 저장.

### 6.3 JWT 유틸리티 (`server/app/core/security.py`)

```python
def create_access_token(user_id: str, email: str) -> str:
    """Access JWT 생성 (30분 만료)."""
    ...

def create_refresh_token(user_id: str, client_id: str) -> str:
    """Refresh JWT 생성 (14일 만료)."""
    ...

def decode_access_token(token: str) -> dict:
    """Access JWT 검증 및 페이로드 반환. 만료/변조 시 예외."""
    ...

def decode_refresh_token(token: str) -> dict:
    """Refresh JWT 검증 및 페이로드 반환. 만료/변조 시 예외."""
    ...

def hash_token(token: str) -> str:
    """SHA-256 해시 (Redis 저장용). 원본 토큰은 저장 안 함."""
    ...

def hash_password(plain: str) -> str:
    """bcrypt(cost=12) 해싱."""
    ...

def verify_password(plain: str, hashed: str) -> bool:
    """bcrypt 검증."""
    ...

def generate_email_code() -> str:
    """6자리 숫자 인증 코드 (secrets.randbelow 사용)."""
    ...
```

---

## 7. Repository 인터페이스 (`server/app/repositories/user_repository.py`)

```python
class UserRepository:
    """User 엔티티 DB 접근 계층."""

    def __init__(self, db: AsyncSession) -> None: ...

    async def create(self, email: str, password_hash: str, nickname: str) -> User:
        """신규 User 생성 후 반환."""
        ...

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        """UUID로 User 조회."""
        ...

    async def get_by_email(self, email: str) -> User | None:
        """이메일로 User 조회."""
        ...

    async def update_email_verified(self, user_id: uuid.UUID) -> User:
        """email_verified_at = now() 업데이트."""
        ...

    async def update_profile(
        self,
        user_id: uuid.UUID,
        *,
        nickname: str | None = None,
        language: str | None = None,
        theme: str | None = None,
        price_color_style: str | None = None,
    ) -> User:
        """프로필 필드 부분 업데이트. None 필드는 변경하지 않음."""
        ...

    async def soft_delete(self, user_id: uuid.UUID) -> User:
        """soft_deleted_at = now() 설정."""
        ...
```

---

## 8. 서비스 인터페이스 (`server/app/services/auth_service.py`)

```python
class AuthService:
    """인증 비즈니스 로직."""

    def __init__(
        self,
        user_repo: UserRepository,
        cache: AuthCacheService,
        email_service: EmailService,
    ) -> None: ...

    async def register(self, email: str, password: str, nickname: str) -> None:
        """회원가입: User 생성 → 인증 코드 발송.

        Raises:
            AppError(EMAIL_ALREADY_EXISTS): 이미 가입된 이메일.
            AppError(NICKNAME_TAKEN): 이미 사용 중인 닉네임.
        """
        ...

    async def verify_email(self, email: str, code: str) -> None:
        """이메일 인증 코드 확인.

        Raises:
            AppError(INVALID_VERIFY_CODE): 코드 불일치 또는 만료.
            AppError(USER_NOT_FOUND): 해당 이메일 사용자 없음.
            AppError(EMAIL_ALREADY_VERIFIED): 이미 인증 완료.
        """
        ...

    async def login(self, email: str, password: str) -> tuple[User, TokenPair]:
        """로그인: 자격증명 검증 → 토큰 발급.

        Raises:
            AppError(INVALID_CREDENTIALS): 이메일/비밀번호 불일치.
            AppError(EMAIL_NOT_VERIFIED): 이메일 미인증.
            AppError(ACCOUNT_DELETED): 삭제 예약된 계정.
        """
        ...

    async def refresh_tokens(self, refresh_token: str) -> TokenPair:
        """Refresh Token 검증 → 새 토큰 쌍 발급 (토큰 로테이션).

        Raises:
            AppError(INVALID_REFRESH_TOKEN): 토큰 불일치/만료/폐기.
        """
        ...

    async def logout(self, user_id: str, refresh_token: str) -> None:
        """해당 세션의 Refresh Token 폐기.

        Raises:
            AppError(INVALID_REFRESH_TOKEN): 토큰 불일치/폐기됨.
        """
        ...

    async def get_current_user(self, user_id: uuid.UUID) -> User:
        """user_id로 User 조회.

        Raises:
            AppError(USER_NOT_FOUND): 사용자 없음.
        """
        ...

    async def update_profile(
        self, user_id: uuid.UUID, data: UpdateProfileRequest
    ) -> User:
        """프로필 수정.

        Raises:
            AppError(USER_NOT_FOUND): 사용자 없음.
            AppError(NICKNAME_TAKEN): 이미 사용 중인 닉네임.
        """
        ...

    async def delete_account(self, user_id: uuid.UUID, refresh_token: str) -> datetime:
        """계정 삭제 예약 (soft delete) + 모든 세션 폐기.

        Returns:
            scheduled_delete_at: 영구 삭제 예정 시각 (now + 30일).

        Raises:
            AppError(USER_NOT_FOUND): 사용자 없음.
        """
        ...
```

### 8.2 이메일 서비스 인터페이스 (`server/app/services/email_service.py`)

```python
class EmailService:
    """SMTP 이메일 발송 서비스."""

    def __init__(self, settings: Settings) -> None: ...

    async def send_verification_code(self, to_email: str, code: str) -> None:
        """6자리 인증 코드 발송. SMTP 실패 시 AppError(EMAIL_SEND_FAILED)."""
        ...
```

---

## 9. 인증 미들웨어 & 의존성 주입 (`server/app/core/deps.py`)

### 9.1 JWT 검증 의존성

```python
async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Bearer JWT 검증 → User 반환.

    Raises:
        HTTPException(401): 토큰 없음/만료/변조.
        HTTPException(403): 이메일 미인증.
        HTTPException(410): 삭제 예약된 계정.
    """
    ...

async def get_current_user_optional(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User | None:
    """인증 선택적 — 토큰 없으면 None 반환."""
    ...
```

### 9.2 타입 별칭 추가 (deps.py)

```python
CurrentUser = Annotated[User, Depends(get_current_user)]
CurrentUserOptional = Annotated[User | None, Depends(get_current_user_optional)]
```

### 9.3 OAuth2 스킴

```python
from fastapi.security import OAuth2PasswordBearer

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)
```

---

## 10. API 엔드포인트 상세

### 10.1 회원가입 — `POST /api/v1/auth/register`

**요청**:
```json
{
  "email": "user@example.com",
  "password": "Str0ng!Pw",
  "nickname": "트레이더"
}
```

**응답 201**:
```json
{
  "data": {
    "message": "인증 코드가 이메일로 발송되었습니다.",
    "email": "user@example.com"
  },
  "error": null,
  "meta": { "timestamp": "2026-03-06T00:00:00Z" }
}
```

**에러**:
| 조건 | HTTP | code |
|------|------|------|
| 이미 가입된 이메일 | 409 | `EMAIL_ALREADY_EXISTS` |
| 이미 사용 중인 닉네임 | 409 | `NICKNAME_TAKEN` |
| 이메일 발송 실패 | 502 | `EMAIL_SEND_FAILED` |

---

### 10.2 이메일 인증 — `POST /api/v1/auth/verify-email`

**요청**:
```json
{ "email": "user@example.com", "code": "123456" }
```

**응답 200**:
```json
{
  "data": { "message": "이메일 인증이 완료되었습니다." },
  "error": null,
  "meta": { "timestamp": "..." }
}
```

**에러**:
| 조건 | HTTP | code |
|------|------|------|
| 코드 불일치/만료 | 400 | `INVALID_VERIFY_CODE` |
| 이미 인증 완료 | 409 | `EMAIL_ALREADY_VERIFIED` |
| 사용자 없음 | 404 | `USER_NOT_FOUND` |

---

### 10.3 로그인 — `POST /api/v1/auth/login`

**요청**:
```json
{ "email": "user@example.com", "password": "Str0ng!Pw" }
```

**응답 200**:
```json
{
  "data": {
    "user": {
      "id": "uuid",
      "email": "user@example.com",
      "nickname": "트레이더",
      "avatar_url": null,
      "language": "ko",
      "theme": "system",
      "price_color_style": "korean",
      "ai_trading_enabled": false,
      "is_2fa_enabled": false,
      "email_verified": true,
      "created_at": "2026-03-06T00:00:00Z"
    },
    "tokens": {
      "access_token": "eyJ...",
      "refresh_token": "eyJ...",
      "token_type": "Bearer",
      "expires_in": 1800
    }
  },
  "error": null,
  "meta": { "timestamp": "..." }
}
```

**에러**:
| 조건 | HTTP | code |
|------|------|------|
| 이메일/비밀번호 불일치 | 401 | `INVALID_CREDENTIALS` |
| 이메일 미인증 | 403 | `EMAIL_NOT_VERIFIED` |
| 삭제 예약된 계정 | 410 | `ACCOUNT_DELETED` |
| 로그인 시도 초과 | 429 | `LOGIN_RATE_LIMIT` |

---

### 10.4 토큰 갱신 — `POST /api/v1/auth/refresh`

**요청**:
```json
{ "refresh_token": "eyJ..." }
```

**응답 200**:
```json
{
  "data": {
    "tokens": {
      "access_token": "eyJ...",
      "refresh_token": "eyJ...",
      "token_type": "Bearer",
      "expires_in": 1800
    }
  },
  "error": null,
  "meta": { "timestamp": "..." }
}
```

**에러**:
| 조건 | HTTP | code |
|------|------|------|
| 토큰 만료/변조/폐기 | 401 | `INVALID_REFRESH_TOKEN` |

**토큰 로테이션**: 갱신 시 기존 refresh token 폐기 후 새 토큰 발급. `client_id`는 유지.

---

### 10.5 로그아웃 — `POST /api/v1/auth/logout`

**헤더**: `Authorization: Bearer {access_token}`
**요청**:
```json
{ "refresh_token": "eyJ..." }
```

**응답 200**:
```json
{
  "data": { "message": "로그아웃되었습니다." },
  "error": null,
  "meta": { "timestamp": "..." }
}
```

---

### 10.6 내 정보 조회 — `GET /api/v1/users/me`

**헤더**: `Authorization: Bearer {access_token}`

**응답 200**:
```json
{
  "data": { "user": { ...UserResponse } },
  "error": null,
  "meta": { "timestamp": "..." }
}
```

**에러**:
| 조건 | HTTP | code |
|------|------|------|
| 토큰 없음/만료 | 401 | `UNAUTHORIZED` |

---

### 10.7 프로필 수정 — `PUT /api/v1/users/me`

**헤더**: `Authorization: Bearer {access_token}`
**요청** (모든 필드 선택):
```json
{
  "nickname": "새닉네임",
  "language": "en",
  "theme": "dark",
  "price_color_style": "western"
}
```

**응답 200**:
```json
{
  "data": { "user": { ...UserResponse } },
  "error": null,
  "meta": { "timestamp": "..." }
}
```

**에러**:
| 조건 | HTTP | code |
|------|------|------|
| 닉네임 중복 | 409 | `NICKNAME_TAKEN` |

---

### 10.8 계정 삭제 — `DELETE /api/v1/users/me`

**헤더**: `Authorization: Bearer {access_token}`
**요청**:
```json
{ "refresh_token": "eyJ..." }
```

**응답 200**:
```json
{
  "data": {
    "message": "계정 삭제가 예약되었습니다. 30일 후 영구 삭제됩니다.",
    "scheduled_delete_at": "2026-04-05T00:00:00Z"
  },
  "error": null,
  "meta": { "timestamp": "..." }
}
```

**처리 흐름**:
1. `User.soft_deleted_at = now()` 설정
2. `AuthCacheService.revoke_all_sessions(user_id)` 호출
3. Celery 태스크 `tasks.cleanup.hard_delete_user` 30일 후 예약

---

## 11. 에러 코드 정의

### 11.1 인증 도메인 에러 코드 전체 목록

| code | HTTP | 설명 |
|------|------|------|
| `EMAIL_ALREADY_EXISTS` | 409 | 이미 가입된 이메일 |
| `NICKNAME_TAKEN` | 409 | 이미 사용 중인 닉네임 |
| `EMAIL_SEND_FAILED` | 502 | SMTP 발송 실패 |
| `INVALID_VERIFY_CODE` | 400 | 인증 코드 불일치 또는 만료 |
| `EMAIL_ALREADY_VERIFIED` | 409 | 이미 인증 완료된 이메일 |
| `INVALID_CREDENTIALS` | 401 | 이메일/비밀번호 불일치 |
| `EMAIL_NOT_VERIFIED` | 403 | 이메일 미인증 상태 |
| `ACCOUNT_DELETED` | 410 | 삭제 예약된 계정 |
| `INVALID_REFRESH_TOKEN` | 401 | Refresh Token 만료/변조/폐기 |
| `UNAUTHORIZED` | 401 | Access Token 없음 또는 만료 |
| `USER_NOT_FOUND` | 404 | 사용자 없음 |
| `LOGIN_RATE_LIMIT` | 429 | 로그인 시도 초과 (5회/15분) |

### 11.2 에러 응답 포맷 예시

```json
{
  "error": {
    "code": "INVALID_CREDENTIALS",
    "message": "이메일 또는 비밀번호가 올바르지 않습니다.",
    "details": null,
    "correlation_id": "550e8400-e29b-41d4-a716-446655440000"
  }
}
```

### 11.3 AppError 예외 클래스 (`server/app/core/exceptions.py`)

```python
class AppError(Exception):
    """도메인 비즈니스 로직 에러."""

    def __init__(self, code: str, message: str, http_status: int) -> None:
        self.code = code
        self.message = message
        self.http_status = http_status
        super().__init__(message)


# 미리 정의된 에러 팩토리
class AuthErrors:
    @staticmethod
    def email_already_exists() -> AppError:
        return AppError("EMAIL_ALREADY_EXISTS", "이미 가입된 이메일입니다.", 409)

    @staticmethod
    def nickname_taken() -> AppError:
        return AppError("NICKNAME_TAKEN", "이미 사용 중인 닉네임입니다.", 409)

    @staticmethod
    def invalid_credentials() -> AppError:
        return AppError("INVALID_CREDENTIALS", "이메일 또는 비밀번호가 올바르지 않습니다.", 401)

    @staticmethod
    def email_not_verified() -> AppError:
        return AppError("EMAIL_NOT_VERIFIED", "이메일 인증이 필요합니다.", 403)

    @staticmethod
    def account_deleted() -> AppError:
        return AppError("ACCOUNT_DELETED", "삭제 예약된 계정입니다.", 410)

    @staticmethod
    def invalid_refresh_token() -> AppError:
        return AppError("INVALID_REFRESH_TOKEN", "유효하지 않은 Refresh Token입니다.", 401)

    @staticmethod
    def unauthorized() -> AppError:
        return AppError("UNAUTHORIZED", "인증이 필요합니다.", 401)

    @staticmethod
    def user_not_found() -> AppError:
        return AppError("USER_NOT_FOUND", "사용자를 찾을 수 없습니다.", 404)

    @staticmethod
    def invalid_verify_code() -> AppError:
        return AppError("INVALID_VERIFY_CODE", "인증 코드가 올바르지 않거나 만료되었습니다.", 400)

    @staticmethod
    def email_already_verified() -> AppError:
        return AppError("EMAIL_ALREADY_VERIFIED", "이미 인증 완료된 이메일입니다.", 409)

    @staticmethod
    def email_send_failed() -> AppError:
        return AppError("EMAIL_SEND_FAILED", "이메일 발송에 실패했습니다. 잠시 후 재시도해주세요.", 502)
```

**`AppError` → `ErrorResponse` 변환**: `main.py`의 글로벌 에러 핸들러에 `AppError` 핸들러 추가.

```python
@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    correlation_id = get_correlation_id()
    return JSONResponse(
        status_code=exc.http_status,
        content=ErrorResponse(
            error=ErrorBody(
                code=exc.code,
                message=exc.message,
                correlation_id=correlation_id,
            )
        ).model_dump(),
    )
```

---

## 12. 시퀀스 다이어그램

### 12.1 회원가입 + 이메일 인증

```
Client              auth.py             AuthService         UserRepo          AuthCache        EmailService
  │                     │                    │                  │                  │                 │
  │ POST /register      │                    │                  │                  │                 │
  │ {email,pw,nickname} │                    │                  │                  │                 │
  │────────────────────►│                    │                  │                  │                 │
  │                     │  register(dto)     │                  │                  │                 │
  │                     │───────────────────►│                  │                  │                 │
  │                     │                    │ get_by_email()   │                  │                 │
  │                     │                    │─────────────────►│                  │                 │
  │                     │                    │   None (신규)     │                  │                 │
  │                     │                    │◄─────────────────│                  │                 │
  │                     │                    │                  │                  │                 │
  │                     │                    │ hash_password(pw, bcrypt12)         │                 │
  │                     │                    │──┐               │                  │                 │
  │                     │                    │◄─┘               │                  │                 │
  │                     │                    │                  │                  │                 │
  │                     │                    │ create(user)     │                  │                 │
  │                     │                    │─────────────────►│                  │                 │
  │                     │                    │   User           │                  │                 │
  │                     │                    │◄─────────────────│                  │                 │
  │                     │                    │                  │                  │                 │
  │                     │                    │ code = generate_email_code()        │                 │
  │                     │                    │ store_email_verify_code(email,code) │                 │
  │                     │                    │─────────────────────────────────────►│                 │
  │                     │                    │                  │    Redis SET     │                 │
  │                     │                    │                  │    TTL 10min     │                 │
  │                     │                    │                  │                  │                 │
  │                     │                    │ send_verification_code(email, code) │                 │
  │                     │                    │────────────────────────────────────────────────────────►
  │                     │                    │                  │                  │   SMTP 발송     │
  │                     │                    │                  │                  │                 │
  │                     │ 201 RegisterResp   │                  │                  │                 │
  │◄────────────────────│                    │                  │                  │                 │
  │                     │                    │                  │                  │                 │
  │ POST /verify-email  │                    │                  │                  │                 │
  │ {email, code}       │                    │                  │                  │                 │
  │────────────────────►│                    │                  │                  │                 │
  │                     │ verify_email(dto)  │                  │                  │                 │
  │                     │───────────────────►│                  │                  │                 │
  │                     │                    │ verify_email_code(email, code)      │                 │
  │                     │                    │─────────────────────────────────────►│                 │
  │                     │                    │   true (GETDEL — 1회용 소비)        │                 │
  │                     │                    │◄─────────────────────────────────────│                 │
  │                     │                    │                  │                  │                 │
  │                     │                    │ update_email_verified(user_id)      │                 │
  │                     │                    │─────────────────►│                  │                 │
  │                     │                    │   email_verified_at = now()         │                 │
  │                     │                    │◄─────────────────│                  │                 │
  │                     │                    │                  │                  │                 │
  │                     │ 200 VerifyResp     │                  │                  │                 │
  │◄────────────────────│                    │                  │                  │                 │
```

### 12.2 로그인

```
Client              auth.py             AuthService         UserRepo          AuthCache        security.py
  │                     │                    │                  │                  │                 │
  │ POST /login         │                    │                  │                  │                 │
  │ {email, password}   │                    │                  │                  │                 │
  │────────────────────►│                    │                  │                  │                 │
  │                     │  login(dto)        │                  │                  │                 │
  │                     │───────────────────►│                  │                  │                 │
  │                     │                    │ get_by_email()   │                  │                 │
  │                     │                    │─────────────────►│                  │                 │
  │                     │                    │   User           │                  │                 │
  │                     │                    │◄─────────────────│                  │                 │
  │                     │                    │                  │                  │                 │
  │                     │                    │ verify_password(pw, hash)           │                 │
  │                     │                    │──┐               │                  │                 │
  │                     │                    │◄─┘ OK            │                  │                 │
  │                     │                    │                  │                  │                 │
  │                     │                    │ Guard checks:                       │                 │
  │                     │                    │ ├ soft_deleted_at? → ACCOUNT_DELETED│                 │
  │                     │                    │ └ email_verified_at? → EMAIL_NOT_VER│                 │
  │                     │                    │                  │                  │                 │
  │                     │                    │ client_id = uuid4()                 │                 │
  │                     │                    │ create_access_token(user_id, email) │                 │
  │                     │                    │────────────────────────────────────────────────────────►
  │                     │                    │   access_token (HS256, 30min)       │                 │
  │                     │                    │◄────────────────────────────────────────────────────────
  │                     │                    │                  │                  │                 │
  │                     │                    │ create_refresh_token(user_id, client_id)              │
  │                     │                    │────────────────────────────────────────────────────────►
  │                     │                    │   refresh_token (HS256, 14d)        │                 │
  │                     │                    │◄────────────────────────────────────────────────────────
  │                     │                    │                  │                  │                 │
  │                     │                    │ hash_token(refresh_token) → sha256  │                 │
  │                     │                    │ store_refresh_token(uid, cid, hash) │                 │
  │                     │                    │─────────────────────────────────────►│                 │
  │                     │                    │                  │   Redis SET      │                 │
  │                     │                    │                  │   TTL 14d        │                 │
  │                     │                    │                  │                  │                 │
  │                     │ 200 LoginResponse  │                  │                  │                 │
  │                     │ {user, tokens}     │                  │                  │                 │
  │◄────────────────────│                    │                  │                  │                 │
```

### 12.3 토큰 갱신 (Refresh Token Rotation)

```
Client              auth.py             AuthService         AuthCache        security.py
  │                     │                    │                  │                 │
  │ POST /refresh       │                    │                  │                 │
  │ {refresh_token}     │                    │                  │                 │
  │────────────────────►│                    │                  │                 │
  │                     │ refresh_tokens(dto)│                  │                 │
  │                     │───────────────────►│                  │                 │
  │                     │                    │ decode_refresh_token(token)        │
  │                     │                    │───────────────────────────────────►│
  │                     │                    │  {sub, type:"refresh", client_id}  │
  │                     │                    │◄───────────────────────────────────│
  │                     │                    │                  │                 │
  │                     │                    │ hash_token(old_refresh)            │
  │                     │                    │ get_refresh_token(uid, cid)        │
  │                     │                    │─────────────────►│                 │
  │                     │                    │  stored_hash     │                 │
  │                     │                    │◄─────────────────│                 │
  │                     │                    │                  │                 │
  │                     │                    │ compare hash == stored_hash        │
  │                     │                    │──┐ (불일치 시 INVALID_REFRESH_TOKEN)│
  │                     │                    │◄─┘               │                 │
  │                     │                    │                  │                 │
  │                     │                    │ revoke_refresh_token(uid, cid)     │
  │                     │                    │─────────────────►│  기존 토큰 폐기 │
  │                     │                    │                  │                 │
  │                     │                    │ create new access + refresh tokens │
  │                     │                    │───────────────────────────────────►│
  │                     │                    │◄───────────────────────────────────│
  │                     │                    │                  │                 │
  │                     │                    │ store_refresh_token(uid, cid, new_hash)
  │                     │                    │─────────────────►│  신규 토큰 저장 │
  │                     │                    │                  │                 │
  │                     │ 200 RefreshResp    │                  │                 │
  │                     │ {tokens}           │                  │                 │
  │◄────────────────────│                    │                  │                 │
```

### 12.4 로그아웃

```
Client              auth.py          get_current_user    AuthService         AuthCache
  │                     │                    │                │                  │
  │ POST /logout        │                    │                │                  │
  │ Authorization:      │                    │                │                  │
  │  Bearer <access>    │                    │                │                  │
  │ {refresh_token}     │                    │                │                  │
  │────────────────────►│                    │                │                  │
  │                     │ Depends(curr_user) │                │                  │
  │                     │───────────────────►│                │                  │
  │                     │   User (인증됨)     │                │                  │
  │                     │◄───────────────────│                │                  │
  │                     │                    │                │                  │
  │                     │ logout(user_id, refresh_token)     │                  │
  │                     │───────────────────────────────────►│                  │
  │                     │                    │                │ decode → client_id│
  │                     │                    │                │ revoke_refresh_token(uid, cid)
  │                     │                    │                │─────────────────►│
  │                     │                    │                │◄─────────────────│
  │                     │                    │                │                  │
  │                     │ 200 LogoutResp     │                │                  │
  │◄────────────────────│                    │                │                  │
```

### 12.5 인증된 요청 흐름 (JWT 검증 의존성)

```
Client              FastAPI DI          security.py         UserRepo            Guard
  │                     │                    │                  │                  │
  │ GET /auth/me        │                    │                  │                  │
  │ Authorization:      │                    │                  │                  │
  │  Bearer <token>     │                    │                  │                  │
  │────────────────────►│                    │                  │                  │
  │                     │ OAuth2Bearer       │                  │                  │
  │                     │  → token 추출      │                  │                  │
  │                     │                    │                  │                  │
  │                     │ decode_access_token(token)            │                  │
  │                     │───────────────────►│                  │                  │
  │                     │  {sub, type:"access", email}         │                  │
  │                     │◄───────────────────│                  │                  │
  │                     │                    │                  │                  │
  │                     │ get_by_id(sub)     │                  │                  │
  │                     │──────────────────────────────────────►│                  │
  │                     │   User             │                  │                  │
  │                     │◄──────────────────────────────────────│                  │
  │                     │                    │                  │                  │
  │                     │ Guard checks:                         │                  │
  │                     │ ├ User is None? → 401 UNAUTHORIZED    │                  │
  │                     │ ├ soft_deleted_at? → 410 ACCOUNT_DELETED                 │
  │                     │ └ email_verified_at is None? → 403 EMAIL_NOT_VERIFIED    │
  │                     │                    │                  │                  │
  │                     │ → User 객체를 엔드포인트에 주입                            │
  │◄────────────────────│                    │                  │                  │
```

### 12.6 계정 삭제 (30일 유예)

```
Client              auth.py          CurrentUser         AuthService         UserRepo       AuthCache
  │                     │                │                    │                  │               │
  │ DELETE /users/me    │                │                    │                  │               │
  │ Authorization:      │                │                    │                  │               │
  │  Bearer <access>    │                │                    │                  │               │
  │ {refresh_token}     │                │                    │                  │               │
  │────────────────────►│                │                    │                  │               │
  │                     │ Depends        │                    │                  │               │
  │                     │───────────────►│                    │                  │               │
  │                     │   User         │                    │                  │               │
  │                     │◄───────────────│                    │                  │               │
  │                     │                │                    │                  │               │
  │                     │ delete_account(user_id, refresh_token)                │               │
  │                     │───────────────────────────────────►│                  │               │
  │                     │                │                    │ soft_delete(uid) │               │
  │                     │                │                    │─────────────────►│               │
  │                     │                │                    │  soft_deleted_at │               │
  │                     │                │                    │  = now()         │               │
  │                     │                │                    │◄─────────────────│               │
  │                     │                │                    │                  │               │
  │                     │                │                    │ revoke_all_sessions(uid)         │
  │                     │                │                    │─────────────────────────────────►│
  │                     │                │                    │  모든 refresh token 폐기         │
  │                     │                │                    │◄─────────────────────────────────│
  │                     │                │                    │                  │               │
  │                     │ 200 AccountDeleteResp               │                  │               │
  │                     │ {scheduled_delete_at: now+30d}      │                  │               │
  │◄────────────────────│                │                    │                  │               │
  │                     │                │                    │                  │               │
  │   ···30일 후···      │                │                    │                  │               │
  │                     │                │                    │                  │               │
  │             Celery Beat → hard_delete_expired_users()     │                  │               │
  │                     │                │                    │ DELETE FROM users │               │
  │                     │                │                    │ WHERE soft_deleted_at + 30d < now│
  │                     │                │                    │─────────────────►│               │
```

---

## 13. 구현 순서 (서브태스크별)

| ST# | 내용 | 관련 파일 |
|-----|------|---------|
| 1 | User 모델 soft_deleted_at 추가 + 인증 스키마 정의 | `models/user.py`, `schemas/auth.py`, `schemas/common.py` |
| 2 | JWT 유틸리티 + Redis Refresh Token 관리 | `core/security.py` |
| 3 | EmailService 구현 (SMTP + aiosmtplib) | `services/email_service.py`, `core/config.py` |
| 4 | UserRepository + AuthService 구현 | `repositories/user_repository.py`, `services/auth_service.py` |
| 5 | get_current_user 의존성 + deps.py 업데이트 | `core/deps.py` |
| 6 | auth 라우터 (register, verify-email, login, refresh, logout) | `api/v1/auth.py` |
| 7 | users/me 라우터 (GET, PUT, DELETE) | `api/v1/users.py` |
| 8 | AppError 핸들러 등록 + 통합 테스트 | `main.py`, `tests/test_auth.py` |

---

## 14. 코드 컨벤션 체크리스트

- [ ] 모든 I/O 바운드 함수 `async def`
- [ ] `mypy --strict` 통과 (Optional 명시, Union 사용 금지 → `X | Y`)
- [ ] Google 스타일 docstring (Raises 섹션 필수)
- [ ] Repository는 `AsyncSession`만 의존 (서비스 레이어 참조 금지)
- [ ] 서비스는 Repository ABC/인터페이스만 의존
- [ ] `password`, `token` 값은 로그 출력 금지 (v1-4 민감정보 마스킹 준수)
- [ ] bcrypt cost=12 (settings.BCRYPT_ROUNDS 상수화 권장)
- [ ] Refresh Token은 원본 저장 금지 → SHA-256 해시만 Redis 저장
- [ ] 이메일 인증 코드: `secrets.randbelow(10**6)` (암호학적 안전 난수)

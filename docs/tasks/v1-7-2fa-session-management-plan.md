# v1-7 2FA (TOTP) 및 세션 관리 시스템 구현 - 설계서

> **작성**: project-architect (시스템 아키텍처/시퀀스), code-architect (API 스키마/DI/에러코드), db-architect (DB 모델/마이그레이션)
> **대상 태스크**: v1-7 — TOTP 2FA 설정/검증/비활성화, 세션(디바이스) 관리, 새 디바이스 알림, Audit Logging
> **현재 상태**: 설계 완료 (3자 합의)

---

## 1. 개요

TOTP 기반 2차 인증(2FA) 설정·검증·비활성화, 활성 세션(디바이스) 목록 관리, 새 디바이스 로그인 감지·알림, 주요 인증 이벤트 Audit Logging을 구현한다.

**의존성**: v1-5 (JWT 인증), v1-6 (소셜 로그인) 완료.

**기존 코드 활용**:
- `server/app/models/user.py` — `User.totp_secret_encrypted`, `User.is_2fa_enabled` 필드 이미 존재
- `server/app/models/user.py` — `Client` 모델 존재 (확장 필요)
- `server/app/documents/audit_logs.py` — `AuditLog` Beanie Document 이미 정의
- `server/app/services/auth_service.py` — `AuthService.login()` 확장 필요
- `server/app/services/auth_cache_service.py` — Redis 세션 관리 기반
- `server/app/core/security.py` — JWT/bcrypt 유틸리티
- `server/app/core/redis_keys.py` — `RedisKey`, `RedisTTL` 상수

### 1.1 핵심 원칙

- **기존 코드 최대 재사용**: AuthService, AuthCacheService, UserRepository 확장
- **단일 책임 분리**: TwoFactorService (2FA 로직), SessionService (세션 관리), AuditService (감사 로그) 분리
- **암호화 필수**: TOTP secret은 AES-256-GCM으로 암호화 저장, 백업 코드는 SHA-256 해시 저장 (별도 테이블)
- **최소 권한**: 2FA 설정/비활성화 시 현재 TOTP 코드 재검증 필수
- **감사 추적**: 모든 인증 이벤트를 MongoDB audit_logs에 기록

---

## 2. 시스템 아키텍처

### 2.1 전체 흐름

```
Flutter App                        Server (FastAPI)                        Storage
-----------                        ----------------                        -------

[2FA Setup]
  POST /2fa/setup ──────────────> [TwoFactorService]
       (Bearer JWT)                  ├─ pyotp.random_base32()
                                     ├─ secret → Redis pending (10min TTL)
                                     ├─ qrcode → base64 PNG
                                     └─ provisioning_uri 생성
  <── { secret, qr_code_uri,    <────┘
       qr_code_base64 }
       (백업 코드는 verify 성공 시 반환)

[2FA Verify/Activate]
  POST /2fa/verify ─────────────> [TwoFactorService]
       { code: "123456" }           ├─ Redis pending secret 조회
                                     ├─ pyotp.TOTP.verify(code, valid_window=1)
                                     ├─ AES-256-GCM encrypt → users.totp_secret_encrypted
                                     ├─ 백업 코드 10개 생성 → user_totp_backup_codes (SHA-256)
                                     └─ is_2fa_enabled = True           ───> [PostgreSQL]
  <── { message, backup_codes } <────┘

[Login with 2FA]
  POST /login ──────────────────> [AuthService.login()]
       { email, password }           ├─ 기존 자격증명 검증
       Headers:                      ├─ user.is_2fa_enabled?
         X-Device-Name               │   ├─ NO: Client 생성/갱신 → JWT 발급
         X-Device-Fingerprint        │   └─ YES: temp_token → Redis (5min TTL)
  <── { requires_2fa: true,     <───┘
       temp_token: "...",
       temp_token_expires_in: 300 }

  POST /2fa/login-verify ──────> [AuthService.verify_login_2fa()]
       { temp_token, code }          ├─ Redis temp_token 검증 (GETDEL)
                                     ├─ TOTP/백업 코드 검증
                                     ├─ Client 생성/갱신              ───> [PostgreSQL]
                                     ├─ JWT 토큰 쌍 발급
                                     └─ AuditLog 기록                ───> [MongoDB]
  <── { user, tokens }           <───┘

[Session Management]
  GET /sessions ────────────────> [SessionService]
                                     └─ Client WHERE user_id, is_active ──> [PostgreSQL]
  <── { sessions: [...] }        <───┘

  DELETE /sessions/{id} ────────> [SessionService]
                                     ├─ Client.is_active = False      ───> [PostgreSQL]
                                     └─ Redis refresh token 폐기      ───> [Redis]
  <── { message: "종료됨" }      <───┘
```

### 2.2 컴포넌트 의존성

```
api/v1/auth.py ────────┬──> TwoFactorService ──┬──> UserRepository (PostgreSQL)
(2FA + 세션 통합)      │                        ├──> AuthCacheService (Redis)
                       │                        └──> core/encryption.py (AES-256-GCM)
                       │
                       ├──> SessionService ─────┬──> ClientRepository (PostgreSQL)
                       │                        └──> AuthCacheService (Redis)
                       │
                       ├──> AuthService ────────┬──> UserRepository
                       │   (login 2FA 분기)      ├──> AuthCacheService
                       │                        └──> TwoFactorService
                       │
                       └──> AuditService ───────┴──> AuditLog (MongoDB/Beanie)
```

---

## 3. 파일 구조

### 3.1 신규 파일

```
server/app/
├── core/
│   └── encryption.py                # ST2: AES-256-GCM 암/복호화 유틸리티
├── schemas/
│   ├── two_factor.py                # ST6: 2FA 요청/응답 스키마
│   └── session.py                   # ST7: 세션 관리 요청/응답 스키마
├── repositories/
│   └── client_repository.py         # ST1,7: Client CRUD (세션 관리)
├── services/
│   ├── two_factor_service.py        # ST2,3,6: TOTP 설정/검증/비활성화
│   ├── session_service.py           # ST5,7: 디바이스 세션 관리
│   └── audit_service.py             # ST9: Audit Log MongoDB 서비스
└── models/
    └── user.py                      # ST1: UserTotpBackupCode 모델 추가

server/alembic/versions/
└── 003_v1_7_2fa_session.py          # DB 마이그레이션

server/tests/
├── unit/
│   ├── test_encryption.py           # AES-256-GCM 단위 테스트
│   ├── test_two_factor_service.py   # TwoFactorService 단위 테스트
│   ├── test_session_service.py      # SessionService 단위 테스트
│   └── test_audit_service.py        # AuditService 단위 테스트
└── integration/
    └── test_2fa_session_api.py      # ST10: 2FA + 세션 통합 테스트
```

### 3.2 수정 파일

```
server/app/
├── models/user.py                   # ST1: Client 확장 (device_name, user_agent, ip_address, device_fingerprint, is_active)
├── services/auth_service.py         # ST8: login() 2FA 분기 로직 추가
├── schemas/auth.py                  # ST8: LoginResponse 확장 (requires_2fa, temp_token)
├── core/deps.py                     # DI: TwoFactorService, SessionService, AuditService 팩토리 + 타입 별칭
├── core/redis_keys.py               # Redis: 2FA setup, pending, fail_count 키
├── core/exceptions.py               # 에러: 2FA/세션 관련 에러 코드 추가
├── core/config.py                   # 설정: TOTP_ENCRYPTION_KEY, 2FA TTL 등
└── api/v1/auth.py                   # 라우터: 2FA + 세션 엔드포인트 추가
```

---

## 4. DB 스키마 설계

### 4.1 Client 모델 확장 (db-architect 구현 완료)

```python
class Client(Base):
    __tablename__ = "clients"
    __table_args__ = (
        Index("ix_clients_user_id", "user_id"),
        Index("ix_clients_fcm_token", "fcm_token"),
        Index("ix_clients_user_fingerprint", "user_id", "device_fingerprint"),  # 신규
    )

    id: Mapped[uuid.UUID] = mapped_column(pg.UUID(as_uuid=True), primary_key=True, ...)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    device_type: Mapped[str] = mapped_column(String(20))              # ios, android, web
    device_name: Mapped[str | None] = mapped_column(String(200))      # 신규 (200자, 긴 디바이스명 대비)
    user_agent: Mapped[str | None] = mapped_column(String(500))       # 신규
    ip_address: Mapped[str | None] = mapped_column(String(45))        # 신규 (IPv6 지원)
    device_fingerprint: Mapped[str | None] = mapped_column(String(64))  # 신규 (SHA-256 hex)
    is_active: Mapped[bool] = mapped_column(                          # 신규 (세션 soft-delete)
        Boolean, default=True, server_default=text("true"), nullable=False
    )
    fcm_token: Mapped[str | None] = mapped_column(String(500))
    last_active_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

### 4.2 UserTotpBackupCode 모델 (신규)

백업 코드를 별도 테이블로 관리. 코드별 사용 여부 개별 추적 및 감사 로그 지원.

```python
class UserTotpBackupCode(Base):
    __tablename__ = "user_totp_backup_codes"
    __table_args__ = (
        Index("ix_totp_backup_codes_user_id", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(pg.UUID(as_uuid=True), primary_key=True, ...)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)  # SHA-256 hex
    is_used: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

**별도 테이블 선택 이유** (vs LargeBinary):
- 코드별 `is_used`/`used_at` 개별 추적 가능
- 1개 코드 사용 시 해당 행만 UPDATE (전체 파싱/재직렬화 불필요)
- 감사 로그에서 어떤 백업 코드가 언제 사용되었는지 추적 가능

### 4.3 Alembic 마이그레이션

- 파일: `server/alembic/versions/003_v1_7_2fa_session.py`
- revision: `c3d4e5f6a7b2`, down_revision: `b2c3d4e5f6a1`
- `CREATE INDEX CONCURRENTLY` 적용 (무중단 배포)
- 새 컬럼은 모두 `nullable=True`로 추가 (기존 데이터 호환)
- `is_active`는 `server_default=text("true")` (기존 행 자동 활성)
- `downgrade()` 완전 구현

---

## 5. 2FA (TOTP) 상세 설계

### 5.1 TOTP 암호화/복호화 (core/encryption.py)

AES-256-GCM으로 TOTP secret을 암호화하여 DB에 저장한다. 키는 환경변수 `TOTP_ENCRYPTION_KEY`에서 로드.

```python
# core/encryption.py
import os
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

def encrypt_totp_secret(plaintext: str, key: bytes) -> bytes:
    """AES-256-GCM 암호화. 반환: nonce(12) + ciphertext + tag(16)"""
    nonce = os.urandom(12)
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode(), None)
    return nonce + ciphertext  # 12 + len(plaintext) + 16

def decrypt_totp_secret(encrypted: bytes, key: bytes) -> str:
    """AES-256-GCM 복호화."""
    nonce = encrypted[:12]
    ciphertext = encrypted[12:]
    aesgcm = AESGCM(key)
    plaintext = aesgcm.decrypt(nonce, ciphertext, None)
    return plaintext.decode()
```

**설정 (config.py 추가)**:
```python
TOTP_ENCRYPTION_KEY: str  # 32바이트 hex (64자) → bytes.fromhex()
TOTP_SETUP_TTL: int = 600  # 10분 (setup 세션)
TOTP_TEMP_TOKEN_TTL: int = 300  # 5분 (로그인 임시 토큰)
```

### 5.2 백업 코드 생성

```python
import secrets
import hashlib

def generate_backup_codes(count: int = 10) -> list[str]:
    """10자리 영숫자 백업 코드 생성 (10개)."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # 혼동 문자 제외 (0/O, 1/I)
    return ["".join(secrets.choice(alphabet) for _ in range(10)) for _ in range(count)]

def hash_backup_code(code: str) -> str:
    """백업 코드를 SHA-256 해시. user_totp_backup_codes.code_hash에 저장."""
    return hashlib.sha256(code.encode()).hexdigest()
```

**저장**: `user_totp_backup_codes` 테이블에 코드별 행 생성 (10행)

### 5.3 2FA Setup 흐름

```
Client                     TwoFactorService                Redis              DB
  │                              │                           │                 │
  ├── POST /2fa/setup ──────────>│                           │                 │
  │   (Bearer JWT)               │                           │                 │
  │                              ├── user.is_2fa_enabled?    │                 │
  │                              │   YES → raise TOTP_ALREADY_ENABLED          │
  │                              │                           │                 │
  │                              ├── pyotp.random_base32() ──┤                 │
  │                              │   → secret                │                 │
  │                              │                           │                 │
  │                              ├── store pending secret ──>│                 │
  │                              │   key: auth:2fa_setup:{user_id}             │
  │                              │   TTL: 10분               │                 │
  │                              │                           │                 │
  │                              ├── pyotp.TOTP(secret)      │                 │
  │                              │   .provisioning_uri(email, │                │
  │                              │    issuer="CoinTrader")   │                 │
  │                              │                           │                 │
  │                              ├── qrcode.make(uri)        │                 │
  │                              │   → base64 PNG            │                 │
  │                              │                           │                 │
  │<── { secret, qr_code_uri,  <┤                           │                 │
  │      qr_code_base64,        │                           │                 │
  │      expires_in: 600 }      │                           │                 │
  │                              │                           │                 │
  │ (백업 코드는 이 시점에 미반환 — verify 성공 시 반환)       │                 │
```

### 5.4 2FA Verify (활성화) 흐름

```
Client                     TwoFactorService                Redis              DB
  │                              │                           │                 │
  ├── POST /2fa/verify ─────────>│                           │                 │
  │   { code: "123456" }         │                           │                 │
  │                              ├── get pending secret ────>│                 │
  │                              │   key: auth:2fa_setup:{user_id}             │
  │                              │   없으면 → TOTP_SETUP_REQUIRED              │
  │                              │                           │                 │
  │                              ├── pyotp.TOTP(secret)      │                 │
  │                              │   .verify(code, valid_window=1)             │
  │                              │   실패 → INVALID_TOTP_CODE│                 │
  │                              │                           │                 │
  │                              ├── encrypt(secret) ────────────────────────>│
  │                              │   → users.totp_secret_encrypted             │
  │                              │                           │                 │
  │                              ├── generate 10 backup codes ──────────────>│
  │                              │   → user_totp_backup_codes (10행, hash 저장)│
  │                              │                           │                 │
  │                              ├── is_2fa_enabled = True ──────────────────>│
  │                              │                           │                 │
  │                              ├── delete pending secret ─>│                 │
  │                              │                           │                 │
  │                              ├── AuditLog(2fa_enabled) ───────────────> MongoDB
  │                              │                           │                 │
  │<── { message: "활성화됨",   <┤                           │                 │
  │      backup_codes: [...] }   │  (평문 1회 반환, 이후 재조회 불가)           │
```

### 5.5 2FA Disable 흐름

```
Client                     TwoFactorService                              DB
  │                              │                                        │
  ├── POST /2fa/disable ────────>│                                        │
  │   { code: "123456" }         │                                        │
  │   (TOTP 6자리 또는           │                                        │
  │    백업코드 10자리)           │                                        │
  │                              ├── user.is_2fa_enabled?                 │
  │                              │   NO → raise TOTP_NOT_ENABLED          │
  │                              │                                        │
  │                              ├── verify_code(code)                    │
  │                              │   ├─ len==6: TOTP 검증                 │
  │                              │   └─ len>6: 백업 코드 검증             │
  │                              │   실패 → INVALID_TOTP_CODE             │
  │                              │                                        │
  │                              ├── totp_secret_encrypted = None ───────>│
  │                              ├── is_2fa_enabled = False ─────────────>│
  │                              ├── DELETE user_totp_backup_codes ───────>│
  │                              │                                        │
  │                              ├── AuditLog(2fa_disabled) ──────────> MongoDB
  │                              │                                        │
  │<── { message: "비활성화됨" }<┤                                        │
```

---

## 6. 로그인 플로우 확장 (2FA 통합)

### 6.1 확장된 로그인 흐름

기존 `AuthService.login()`을 확장하여 2FA 활성 사용자에게 임시 토큰을 발급하고, `POST /2fa/login-verify`에서 TOTP 검증 후 최종 토큰을 발급한다.

**디바이스 정보 수집**: Request Body가 아닌 **HTTP Header**에서 추출.

```
Headers:
  X-Device-Name: iPhone 15 Pro         (커스텀 헤더, Optional)
  X-Device-Fingerprint: abc123...       (커스텀 헤더, Optional)
  User-Agent: (표준 헤더, FastAPI Request에서 자동 추출)
  → ip_address는 request.client.host에서 추출
```

```
Client                     AuthService                    Redis              DB
  │                              │                           │                 │
  ├── POST /login ──────────────>│                           │                 │
  │   { email, password }        │                           │                 │
  │   Headers: X-Device-*        │                           │                 │
  │                              ├── 기존 자격증명 검증      │                 │
  │                              │   (rate limit, bcrypt 등) │                 │
  │                              │                           │                 │
  │                              ├── user.is_2fa_enabled?    │                 │
  │                              │                           │                 │
  │ [2FA 비활성 사용자]           │   NO ───────────────────  │                 │
  │                              ├── Client 생성/갱신 ───────────────────────>│
  │                              ├── JWT 토큰 발급           │                 │
  │                              ├── AuditLog(login) ──────────────────────> MongoDB
  │<── { user, tokens }         <┤                           │                 │
  │                              │                           │                 │
  │ [2FA 활성 사용자]             │   YES ──────────────────  │                 │
  │                              ├── temp_token 생성 ──────>│                 │
  │                              │   key: auth:2fa_pending:{user_id}:{hash}  │
  │                              │   val: {device_info JSON}  │                │
  │                              │   TTL: 5분                │                 │
  │<── { requires_2fa: true,    <┤                           │                 │
  │      temp_token: "...",      │                           │                 │
  │      temp_token_expires_in } │                           │                 │
  │                              │                           │                 │
  ├── POST /2fa/login-verify ───>│                           │                 │
  │   { temp_token, code }       │                           │                 │
  │                              ├── Redis temp GETDEL ────>│                 │
  │                              │   없으면 → INVALID_TEMP_TOKEN              │
  │                              │                           │                 │
  │                              ├── verify_code(code)       │                 │
  │                              │   ├─ TOTP 또는 백업코드   │                 │
  │                              │   실패 → INVALID_TOTP_CODE│                 │
  │                              │                           │                 │
  │                              ├── Client 생성/갱신 ───────────────────────>│
  │                              ├── JWT 토큰 발급           │                 │
  │                              ├── delete temp_token ────>│                 │
  │                              ├── AuditLog(login) ──────────────────────> MongoDB
  │<── { user, tokens }         <┤                           │                 │
```

### 6.2 임시 토큰 (temp_token) 설계

- **생성**: `secrets.token_urlsafe(32)` (43자 URL-safe Base64)
- **Redis 저장**: `auth:2fa_pending:{user_id}:{token_hash}` → JSON `{ device_fingerprint, device_name, ip_address, user_agent }`
- **TTL**: 5분 (`TOTP_TEMP_TOKEN_TTL`)
- **보안**: SHA-256 해시 후 Redis 키로 사용 (원문 노출 방지)
- **1회 사용**: GETDEL로 원자적 조회+삭제

### 6.3 LoginResponse 확장

```python
# schemas/auth.py — LoginResponse 통합

class LoginResponse(BaseModel):
    """로그인 응답 — 2FA 상태에 따라 필드 분기."""
    # 정상 로그인 (2FA 미활성)
    user: UserResponse | None = None
    tokens: TokenPair | None = None
    # 2FA 필요 시
    requires_2fa: bool = False
    temp_token: str | None = None
    temp_token_expires_in: int | None = None  # 300 (5분)
```

**API 엔드포인트 응답 분기**:
- `POST /login` → 2FA 비활성: `ApiResponse[LoginResponse]` (user + tokens 채움, requires_2fa=False)
- `POST /login` → 2FA 활성: `ApiResponse[LoginResponse]` (user=None, tokens=None, requires_2fa=True, temp_token 채움)
- `POST /2fa/login-verify` → `ApiResponse[LoginResponse]` (user + tokens 채움)

---

## 7. 세션(디바이스) 관리 설계

### 7.1 ClientRepository

```python
# repositories/client_repository.py

class ClientRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def create(self, user_id: UUID, *, device_type: str,
                     device_name: str | None, user_agent: str | None,
                     ip_address: str | None) -> Client: ...

    async def get_by_id(self, client_id: UUID) -> Client | None: ...

    async def get_by_user_and_fingerprint(
        self, user_id: UUID, fingerprint: str
    ) -> Client | None:
        """user_id + device_fingerprint 복합 인덱스 활용."""
        ...

    async def get_by_user(self, user_id: UUID) -> list[Client]:
        """활성 세션 목록 (is_active=True)."""
        ...

    async def delete(self, client_id: UUID) -> None:
        """is_active = False 설정 (soft-delete)."""
        ...

    async def update_last_active(self, client_id: UUID) -> None: ...
```

### 7.2 SessionService

```python
# services/session_service.py

class SessionService:
    def __init__(self, client_repo: ClientRepository, cache: AuthCacheService) -> None:
        self._repo = client_repo
        self._cache = cache

    async def create_or_update_session(
        self, user_id: UUID, device_fingerprint: str | None,
        device_name: str | None, device_type: str,
        ip_address: str, user_agent: str
    ) -> tuple[Client, bool]:
        """세션 생성 또는 갱신. 반환: (client, is_new_device)"""
        is_new_device = True
        if device_fingerprint:
            existing = await self._repo.get_by_user_and_fingerprint(user_id, device_fingerprint)
            if existing and existing.is_active:
                await self._repo.update_last_active(existing.id)
                is_new_device = False
                return existing, is_new_device
        # 새 디바이스 → 생성
        client = await self._repo.create(user_id=user_id, ...)
        return client, is_new_device

    async def list_sessions(self, user_id: UUID) -> list[Client]: ...

    async def revoke_session(self, user_id: UUID, client_id: UUID) -> None:
        """개별 세션 종료 — Client.is_active=False + Redis refresh token 폐기."""
        ...

    async def revoke_all_sessions(self, user_id: UUID, except_client_id: UUID | None = None) -> int:
        """모든 세션 종료 (현재 세션 제외 옵션)."""
        ...
```

### 7.3 Device Fingerprint 설계

**클라이언트 생성 규칙**:
- Flutter: `device_info_plus` 패키지로 디바이스 ID 수집 → SHA-256
- Web: Canvas fingerprint + UA + 화면 해상도 조합 → SHA-256
- fingerprint 없는 요청: `None` 처리 (항상 새 디바이스로 간주)

**전달 방식**: `X-Device-Fingerprint` HTTP 헤더 (Optional)

---

## 8. Audit Logging 설계

### 8.1 AuditService

```python
# services/audit_service.py

class AuditService:
    def __init__(self, mongodb: AsyncIOMotorDatabase) -> None:
        self._db = mongodb

    async def log(
        self,
        action: str,
        ip_address: str,
        user_agent: str,
        user_id: UUID | None = None,
        details: dict | None = None,
    ) -> None:
        """Audit Log 기록. 실패해도 주요 플로우를 차단하지 않음."""
        try:
            audit = AuditLog(
                user_id=user_id,
                action=action,
                ip_address=ip_address,
                user_agent=user_agent,
                details=details,
            )
            await audit.insert()
        except Exception:
            logger.error("audit_log_failed", action=action, exc_info=True)
```

### 8.2 Audit Action 상수

```python
class AuditAction:
    LOGIN_SUCCESS = "login_success"
    LOGIN_FAILED = "login_failed"
    LOGOUT = "logout"
    LOGOUT_ALL = "logout_all"
    PASSWORD_CHANGE = "password_change"
    TWO_FACTOR_ENABLED = "2fa_enabled"
    TWO_FACTOR_DISABLED = "2fa_disabled"
    TWO_FACTOR_LOGIN_SUCCESS = "2fa_login_success"
    TWO_FACTOR_LOGIN_FAILED = "2fa_login_failed"
    TWO_FACTOR_BACKUP_USED = "2fa_backup_used"
    NEW_DEVICE_LOGIN = "new_device_login"
    SESSION_REVOKED = "session_revoked"
```

### 8.3 기록 시점

| 이벤트 | action | details 예시 |
|--------|--------|-------------|
| 로그인 성공 | `login_success` | `{ device_name, ip, is_new_device }` |
| 로그인 실패 | `login_failed` | `{ reason: "invalid_credentials" }` |
| 로그아웃 | `logout` | `{ client_id }` |
| 전체 로그아웃 | `logout_all` | `{ revoked_count: 3 }` |
| 2FA 활성화 | `2fa_enabled` | `{}` |
| 2FA 비활성화 | `2fa_disabled` | `{}` |
| 2FA 로그인 성공 | `2fa_login_success` | `{ device_name }` |
| 2FA 로그인 실패 | `2fa_login_failed` | `{ reason: "invalid_code" }` |
| 백업 코드 사용 | `2fa_backup_used` | `{ remaining_count: 9 }` |
| 새 디바이스 | `new_device_login` | `{ device_name, device_fingerprint }` |
| 세션 종료 | `session_revoked` | `{ revoked_client_id }` |

---

## 9. API 엔드포인트 규격

### 9.1 2FA 엔드포인트

#### POST /api/v1/auth/2fa/setup

> 2FA 설정 시작 — TOTP secret, QR URI, QR 이미지 반환

| 항목 | 값 |
|------|-----|
| 인증 | Bearer JWT 필수 |
| Request Body | 없음 |
| 성공 응답 | `200 ApiResponse[TwoFactorSetupResponse]` |
| 에러 | `409 TOTP_ALREADY_ENABLED` |

```python
class TwoFactorSetupResponse(BaseModel):
    secret: str           # Base32 encoded (앱 수동 입력용)
    qr_code_uri: str      # otpauth://totp/CoinTrader:{email}?secret=...&issuer=CoinTrader
    qr_code_base64: str   # PNG QR 이미지 Base64 (Flutter Image.memory용)
    expires_in: int = 600  # setup 세션 만료 초 (10분)
```

#### POST /api/v1/auth/2fa/verify

> TOTP 코드 검증 → 2FA 활성화 + 백업 코드 반환

| 항목 | 값 |
|------|-----|
| 인증 | Bearer JWT 필수 |
| Request Body | `{ "code": "123456" }` |
| 성공 응답 | `200 ApiResponse[TwoFactorActivateResponse]` |
| 에러 | `400 INVALID_TOTP_CODE`, `400 TOTP_SETUP_REQUIRED` |

```python
class TwoFactorVerifyRequest(BaseModel):
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")

class TwoFactorActivateResponse(BaseModel):
    message: str = "2FA가 활성화되었습니다."
    backup_codes: list[str]  # 10자리 백업 코드 10개 (평문, 1회성 표시)
```

#### POST /api/v1/auth/2fa/disable

> TOTP 코드 또는 백업 코드 검증 → 2FA 비활성화

| 항목 | 값 |
|------|-----|
| 인증 | Bearer JWT 필수 |
| Request Body | `{ "code": "123456" }` |
| 성공 응답 | `200 ApiResponse[TwoFactorDisableResponse]` |
| 에러 | `400 INVALID_TOTP_CODE`, `400 TOTP_NOT_ENABLED` |

```python
class TwoFactorDisableRequest(BaseModel):
    code: str = Field(min_length=6, max_length=10)
    # 6자리 TOTP 또는 10자리 백업 코드 허용

class TwoFactorDisableResponse(BaseModel):
    message: str = "2FA가 비활성화되었습니다."
```

#### GET /api/v1/auth/2fa/status

> 2FA 활성화 상태 조회

| 항목 | 값 |
|------|-----|
| 인증 | Bearer JWT 필수 |
| 성공 응답 | `200 ApiResponse[TwoFactorStatusResponse]` |

```python
class TwoFactorStatusResponse(BaseModel):
    is_enabled: bool
    has_backup_codes: bool  # 잔여 미사용 백업 코드 존재 여부
```

### 9.2 로그인 2FA 엔드포인트

#### POST /api/v1/auth/2fa/login-verify

> 2FA 검증 후 최종 토큰 발급

| 항목 | 값 |
|------|-----|
| 인증 | 없음 (temp_token으로 검증) |
| Request Body | `{ "temp_token": "...", "code": "123456" }` |
| 성공 응답 | `200 ApiResponse[LoginResponse]` |
| 에러 | `401 INVALID_TEMP_TOKEN`, `400 INVALID_TOTP_CODE` |

```python
class TwoFactorLoginVerifyRequest(BaseModel):
    temp_token: str
    code: str = Field(min_length=6, max_length=10)
    # 6자리 TOTP 또는 10자리 백업 코드 허용
```

### 9.3 세션 관리 엔드포인트

#### GET /api/v1/auth/sessions

> 현재 사용자의 활성 세션 목록

| 항목 | 값 |
|------|-----|
| 인증 | Bearer JWT 필수 |
| 성공 응답 | `200 ApiResponse[SessionListResponse]` |

```python
class SessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    client_id: uuid.UUID
    device_type: str
    device_name: str | None
    ip_address: str | None
    user_agent: str | None
    last_active_at: datetime | None
    created_at: datetime
    is_current: bool  # 현재 요청의 client_id와 일치 여부

class SessionListResponse(BaseModel):
    sessions: list[SessionResponse]
```

#### DELETE /api/v1/auth/sessions/{client_id}

> 개별 세션 강제 종료

| 항목 | 값 |
|------|-----|
| 인증 | Bearer JWT 필수 |
| Path Param | `client_id: UUID` |
| 성공 응답 | `200 ApiResponse[dict]` (`{ "message": "세션이 종료되었습니다." }`) |
| 에러 | `404 SESSION_NOT_FOUND` |

#### POST /api/v1/auth/logout-all

> 현재 세션을 제외한 모든 세션 종료

| 항목 | 값 |
|------|-----|
| 인증 | Bearer JWT 필수 |
| 성공 응답 | `200 ApiResponse[LogoutAllResponse]` |

```python
class LogoutAllResponse(BaseModel):
    message: str = "모든 세션에서 로그아웃되었습니다."
    revoked_count: int
```

---

## 10. Redis 키 설계

### 10.1 신규 키 패턴

```python
# core/redis_keys.py 추가

class RedisKey:
    # ── 2FA ──
    @staticmethod
    def two_fa_setup(user_id: str) -> str:
        """2FA 설정 대기 (pending secret)."""
        return f"auth:2fa_setup:{user_id}"

    @staticmethod
    def two_fa_pending(user_id: str, temp_token_hash: str) -> str:
        """2FA 로그인 임시 토큰."""
        return f"auth:2fa_pending:{user_id}:{temp_token_hash}"

    @staticmethod
    def two_fa_fail_count(user_id: str) -> str:
        """2FA 코드 검증 실패 횟수."""
        return f"2fa:fail_count:{user_id}"

class RedisTTL:
    # ── 2FA ──
    TWO_FA_SETUP = 10 * 60    # 10분 (설정 대기)
    TWO_FA_PENDING = 5 * 60   # 5분 (로그인 임시 토큰)
    TWO_FA_FAIL = 15 * 60     # 15분 (실패 카운터 윈도우)
```

### 10.2 Redis 데이터 구조

| 키 | 타입 | 값 | TTL |
|-----|------|-----|------|
| `auth:2fa_setup:{user_id}` | STRING | TOTP secret (Base32 평문) | 10분 |
| `auth:2fa_pending:{user_id}:{token_hash}` | STRING | JSON: `{ device_fingerprint, device_name, ip_address, user_agent }` | 5분 |
| `2fa:fail_count:{user_id}` | STRING | 정수 (실패 횟수) | 15분 |

### 10.3 TOTP 브루트포스 방지

```
2fa:fail_count:{user_id} — 최대 5회/15분 윈도우
초과 시 TOTP 검증 거부 (기존 login rate limit과 별도)
```

---

## 11. DI (Dependency Injection) 설계

### 11.1 신규 DI 팩토리 (deps.py)

```python
# core/deps.py 추가

from app.repositories.client_repository import ClientRepository
from app.services.two_factor_service import TwoFactorService
from app.services.session_service import SessionService
from app.services.audit_service import AuditService

def get_client_repository(db: AsyncSession = Depends(get_db)) -> ClientRepository:
    return ClientRepository(db)

def get_two_factor_service(
    user_repo: UserRepository = Depends(get_user_repository),
    cache: AuthCacheService = Depends(get_auth_cache_service),
    settings: Settings = Depends(get_settings),
) -> TwoFactorService:
    return TwoFactorService(user_repo, cache, settings)

def get_session_service(
    client_repo: ClientRepository = Depends(get_client_repository),
    cache: AuthCacheService = Depends(get_auth_cache_service),
) -> SessionService:
    return SessionService(client_repo, cache)

def get_audit_service(
    mongodb: AsyncIOMotorDatabase = Depends(get_mongodb),
) -> AuditService:
    return AuditService(mongodb)

# ── Type aliases ──
ClientRepoDep = Annotated[ClientRepository, Depends(get_client_repository)]
TwoFactorServiceDep = Annotated[TwoFactorService, Depends(get_two_factor_service)]
SessionServiceDep = Annotated[SessionService, Depends(get_session_service)]
AuditServiceDep = Annotated[AuditService, Depends(get_audit_service)]
```

### 11.2 AuthService DI 확장

AuthService 생성자에 선택적 매개변수로 TwoFactorService, SessionService 추가 (하위 호환).

```python
# AuthService 확장 — login 2FA 분기에서만 사용
def get_auth_service(
    user_repo: UserRepository = Depends(get_user_repository),
    auth_cache: AuthCacheService = Depends(get_auth_cache_service),
    email_svc: EmailService = Depends(get_email_service),
    settings: Settings = Depends(get_settings),
) -> AuthService:
    return AuthService(user_repo, auth_cache, email_svc, settings)
```

> **설계 결정**: AuthService에 TwoFactorService/SessionService를 주입하지 않음.
> 2FA 검증과 세션 생성은 **API 레이어(auth.py)에서 오케스트레이션**하여 서비스 간 순환 의존 방지.

---

## 12. 에러 코드 설계

### 12.1 AuthErrors 확장

```python
# core/exceptions.py — AuthErrors에 추가

@staticmethod
def totp_already_enabled() -> AppError:
    """2FA 이미 활성화 상태에서 setup 시도."""
    return AppError("TOTP_ALREADY_ENABLED", "2FA가 이미 활성화되어 있습니다.", 409)

@staticmethod
def totp_not_enabled() -> AppError:
    """2FA 미활성 상태에서 disable/검증 시도."""
    return AppError("TOTP_NOT_ENABLED", "2FA가 활성화되어 있지 않습니다.", 400)

@staticmethod
def totp_setup_required() -> AppError:
    """setup 없이 verify 호출, 또는 임시 secret 만료."""
    return AppError("TOTP_SETUP_REQUIRED", "2FA 설정이 필요합니다. 다시 시도해주세요.", 400)

@staticmethod
def invalid_totp_code() -> AppError:
    """TOTP 코드 또는 백업 코드 불일치."""
    return AppError("INVALID_TOTP_CODE", "유효하지 않은 인증 코드입니다.", 400)

@staticmethod
def invalid_temp_token() -> AppError:
    """2FA 로그인 임시 토큰 만료/불일치."""
    return AppError("INVALID_TEMP_TOKEN", "유효하지 않은 임시 토큰입니다.", 401)

@staticmethod
def session_not_found() -> AppError:
    """세션(client_id) 없음."""
    return AppError("SESSION_NOT_FOUND", "세션을 찾을 수 없습니다.", 404)
```

> **에러 통합 결정**: `INVALID_BACKUP_CODE`를 `invalid_totp_code()`로 통합. 클라이언트에 백업 코드 존재 여부 힌트를 주지 않음 (보안). `TOTP_SETUP_EXPIRED`도 `totp_setup_required()`로 통합 (만료든 미시작이든 동일 처리).

---

## 13. 서비스 클래스 상세 설계

### 13.1 TwoFactorService

```python
class TwoFactorService:
    def __init__(self, user_repo: UserRepository, cache: AuthCacheService, settings: Settings):
        self._repo = user_repo
        self._cache = cache
        self._settings = settings
        self._key = bytes.fromhex(settings.TOTP_ENCRYPTION_KEY)

    async def generate_setup(self, user_id: uuid.UUID, email: str) -> TwoFactorSetupResponse:
        """TOTP 비밀키 생성 → Redis 임시 저장 → QR URI/이미지 반환."""
        # 1. is_2fa_enabled 확인 → TOTP_ALREADY_ENABLED
        # 2. pyotp.random_base32() → secret
        # 3. Redis auth:2fa_setup:{user_id} 저장 (10분 TTL)
        # 4. provisioning_uri + qrcode base64 생성
        # 5. TwoFactorSetupResponse 반환

    async def activate(self, user_id: uuid.UUID, code: str) -> list[str]:
        """Redis 임시 secret 조회 → TOTP 검증 → DB 저장 → 백업 코드 반환."""
        # 1. Redis pending secret 조회 → TOTP_SETUP_REQUIRED
        # 2. pyotp.TOTP(secret).verify(code, valid_window=1) → INVALID_TOTP_CODE
        # 3. encrypt_totp_secret(secret) → users.totp_secret_encrypted
        # 4. generate_backup_codes(10) → user_totp_backup_codes 10행 INSERT
        # 5. is_2fa_enabled = True
        # 6. Redis pending secret 삭제
        # 7. 평문 백업 코드 리스트 반환

    async def disable(self, user_id: uuid.UUID, code: str) -> None:
        """TOTP/백업 코드 검증 → 2FA 비활성화."""
        # 1. is_2fa_enabled 확인 → TOTP_NOT_ENABLED
        # 2. verify_code(user_id, code) → INVALID_TOTP_CODE
        # 3. totp_secret_encrypted = None, is_2fa_enabled = False
        # 4. user_totp_backup_codes DELETE

    async def verify_code(self, user_id: uuid.UUID, code: str) -> bool:
        """TOTP 코드 또는 백업 코드 검증 (로그인 2단계 + disable 공용)."""
        # 1. 2fa:fail_count 확인 → 5회 초과 시 거부
        # 2. len(code) <= 6: TOTP 검증 (decrypt → pyotp.verify)
        # 3. len(code) > 6: 백업 코드 검증 (SHA-256 → DB 조회 → is_used=True)
        # 4. 실패 시 fail_count 증가
        # 5. 성공 시 fail_count 리셋

    async def get_status(self, user_id: uuid.UUID) -> TwoFactorStatusResponse:
        """2FA 상태 조회."""
        # is_enabled, has_backup_codes (미사용 코드 존재 여부)
```

---

## 14. 보안 고려사항

### 14.1 TOTP 보안

- **AES-256-GCM**: 각 암호화마다 고유 nonce(12바이트) 사용, 인증 태그로 무결성 보장
- **키 관리**: `TOTP_ENCRYPTION_KEY`는 환경변수로만 제공, 코드/로그에 절대 노출 금지
- **valid_window=1**: 현재 + 이전 시간 간격(30초) 허용 (시계 오차 대응)
- **브루트포스 방지**: `2fa:fail_count:{user_id}` — 5회/15분 실패 시 검증 거부

### 14.2 백업 코드 보안

- SHA-256 해시 저장 (원문 복원 불가)
- `user_totp_backup_codes` 테이블에서 개별 행으로 관리
- 사용 시 `is_used=True`, `used_at=now()` 업데이트 (재사용 불가)
- verify 성공 시 1회만 평문 반환 (이후 재조회 불가)

### 14.3 임시 토큰 보안

- `secrets.token_urlsafe(32)`: 256비트 암호학적 난수
- SHA-256 해시를 Redis 키로 사용 (원문을 Redis에 저장하지 않음)
- GETDEL 원자적 사용으로 재사용 방지
- 5분 TTL 자동 만료

### 14.4 세션 보안

- Client 비활성화(`is_active=False`) 시 해당 Redis refresh token 즉시 폐기
- 전체 로그아웃 시 모든 Redis refresh token 폐기
- device_fingerprint는 클라이언트 제공 값 수용 (서버 미생성)
- 세션 기록은 soft-delete (감사 추적 보존)

---

## 15. 서브태스크 의존성 그래프

```
ST1: Client 모델 확장 ──────────────────────────────────────┐
     + UserTotpBackupCode 신규                               │
                                                             │
ST2: TOTP 암호화 유틸리티 ──────────────────┐               │
                                             │               │
ST3: QR/백업 코드 생성 ────────────┐        │               │
                                    │        │               │
ST9: Audit Log 서비스 ─────────────│────────│───────────────│──┐
                                    │        │               │   │
                           ┌────────┴────────┴───┐           │   │
                           │ ST4: User Repo 2FA  │           │   │
                           └─────────┬───────────┘           │   │
                                     │                       │   │
                           ┌─────────┴───────────┐           │   │
                           │ ST5: Device FP 감지  │──────────┤   │
                           └─────────┬───────────┘           │   │
                                     │                       │   │
                    ┌────────────────┴────────────┐          │   │
                    │                              │          │   │
           ┌────────┴────────┐           ┌────────┴─────────┴┐  │
           │ ST6: 2FA API    │           │ ST7: 세션 관리 API │  │
           └────────┬────────┘           └────────┬──────────┘  │
                    │                              │             │
                    └──────────────┬───────────────┘             │
                                   │                             │
                           ┌───────┴────────────────────────────┴┐
                           │ ST8: 로그인 2FA + Client 통합       │
                           └───────┬─────────────────────────────┘
                                   │
                           ┌───────┴───────────┐
                           │ ST10: E2E 통합 테스트│
                           └───────────────────┘
```

### 병렬 작업 가능 그룹

| 그룹 | 태스크 | 선행 조건 |
|------|--------|-----------|
| Phase 1 | ST1, ST2, ST3, ST9 | 없음 (병렬 가능) |
| Phase 2 | ST4, ST5 | ST1, ST2 |
| Phase 3 | ST6, ST7 | ST4, ST5 |
| Phase 4 | ST8 | ST5, ST6, ST7 |
| Phase 5 | ST10 | ST6, ST7, ST8, ST9 |

---

## 16. 의존 라이브러리

| 패키지 | 용도 | 버전 |
|--------|------|------|
| `pyotp` | TOTP 생성/검증 | >=2.9 |
| `qrcode[pil]` | QR 코드 이미지 생성 | >=7.4 |
| `cryptography` | AES-256-GCM 암/복호화 | >=42.0 (이미 python-jose 의존) |

> `pyotp`, `qrcode[pil]` 신규 추가 필요. `cryptography`는 v1-6에서 이미 추가됨.

---

## 17. 구현 시 주의사항

1. **AuthService 하위 호환**: 생성자 시그니처 변경 없이 2FA 분기는 API 레이어에서 오케스트레이션. 기존 `test_auth_service.py` mock 수정 최소화.

2. **Login 응답 타입 분기**: `LoginResponse`에 nullable 필드로 통합. `requires_2fa=True`이면 `user=None`, `tokens=None`. OpenAPI 문서에 주석으로 분기 조건 명시.

3. **AuditLog fire-and-forget**: Audit 로그 실패가 주요 비즈니스 로직을 차단하면 안 됨. try-except로 감싸되 로그는 반드시 남김.

4. **TOTP valid_window**: `pyotp.TOTP.verify(code, valid_window=1)` — 현재 시간 ± 30초 허용. 네트워크 지연 고려.

5. **Alembic 마이그레이션**: Client 확장 컬럼은 `nullable=True`로 추가 (기존 데이터 호환). `is_active`는 `server_default=text("true")`. `CREATE INDEX CONCURRENTLY` 적용.

6. **소셜 로그인과 2FA**: 소셜 로그인 사용자도 2FA 설정 가능. `SocialAuthService` 로그인 흐름에 2FA 분기 추가 필요 (v1-8 또는 별도 태스크로 분리 가능).

7. **device_fingerprint 없는 요청**: fingerprint가 없으면 항상 새 Client 생성. 기존 디바이스 매칭 불가.

8. **코드 길이 기반 자동 구분**: TOTP 코드 `^\d{6}$` (6자리 숫자), 백업 코드 10자리 영숫자. `verify_code()`에서 길이로 자동 구분.

9. **DELETE 엔드포인트 URL 설계**: `POST /2fa/disable`은 body에 code 필요 → DELETE에 body는 일부 클라이언트/프록시 호환 문제 → POST 채택.

---

## 18. 구현 현재 상태

**상태: 구현 완료 (2026-03-06)**

### 18.1 구현 파일 목록

| 파일 | 설명 |
|------|------|
| `server/app/core/encryption.py` | AES-256-GCM TOTP 암/복호화 + QR 생성 + 백업 코드 |
| `server/app/services/two_factor_service.py` | TwoFactorService: setup/verify/disable/status |
| `server/app/services/session_service.py` | SessionService: 세션 CRUD + device fingerprint |
| `server/app/services/audit_service.py` | AuditService: MongoDB audit_logs fire-and-forget |
| `server/app/repositories/client_repository.py` | ClientRepository: Client CRUD |
| `server/app/schemas/two_factor.py` | 2FA 요청/응답 스키마 |
| `server/app/schemas/session.py` | 세션 관리 요청/응답 스키마 |
| `server/alembic/versions/003_v1_7_2fa_session.py` | DB 마이그레이션 |
| `server/tests/integration/test_2fa_session_api.py` | 통합 테스트 37케이스 |
| `server/tests/integration/conftest.py` | 테스트 fixtures |

### 18.2 수정된 기존 파일

| 파일 | 변경 내용 |
|------|----------|
| `server/app/models/user.py` | Client 확장 (device_name, user_agent, ip_address, device_fingerprint, is_active) + UserTotpBackupCode 신규 |
| `server/app/services/auth_service.py` | login() 2FA 분기, verify_login_2fa() 추가 |
| `server/app/services/auth_cache_service.py` | 2FA pending/fail_count Redis 메서드 추가 |
| `server/app/api/v1/auth.py` | 2FA + 세션 엔드포인트 9개 추가 |
| `server/app/schemas/auth.py` | LoginResponse 확장 (requires_2fa, temp_token) |
| `server/app/core/deps.py` | TwoFactorService, SessionService, AuditService DI 팩토리 + 타입 별칭 |
| `server/app/core/exceptions.py` | AuthErrors 6개 에러 추가 |
| `server/app/core/redis_keys.py` | 2FA Redis 키/TTL 추가 |
| `server/app/core/config.py` | TOTP_ENCRYPTION_KEY, 2FA TTL 설정 |
| `server/app/core/security.py` | Access Token client_id 클레임 추가 |
| `server/app/repositories/user_repository.py` | 2FA 관련 메서드 확장 |
| `server/tests/integration/test_auth_api.py` | POST /login API 변경 반영 (28케이스) |

### 18.3 코드 리뷰 결과

- CRITICAL 3건 수정 완료 (AuthService 캡슐화, Redis 키 설계서 준수, bulk UPDATE)
- WARNING 3건 수정 완료
- INFO 2건 수정 완료
- 최종 승인 완료

### 18.4 테스트 결과

- 통합 테스트: 65/65 통과 (test_auth_api 28 + test_2fa_session_api 37)

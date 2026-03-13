# v1-11 거래소 계정 관리 API 구현 — 설계서

> **작성**: project-architect (시스템 아키텍처/흐름/구현계획), code-architect (코드 구조/스키마/인터페이스 설계)
> **대상 태스크**: v1-11 — 거래소 API 키 등록/수정/삭제, AES-256-GCM 암호화 저장, 권한 검증, API 키 테스트
> **현재 상태**: 구현 완료 — 전체 서브태스크(ST1~ST10) 완료, 코드 리뷰 LGTM, 58/58 테스트 PASS

---

## 1. 개요

사용자가 거래소(Upbit, CoinOne 등)의 API 키를 안전하게 등록·관리할 수 있는 CRUD API를 구현한다. API 키는 AES-256-GCM으로 암호화하여 DB에 저장하고, 등록 시 거래소 API를 호출하여 키 유효성과 권한을 검증한다.

**의존성**: v1-8 (Exchange Abstraction Layer), v1-9 (Upbit Provider), v1-10 (CoinOne Provider)

**핵심 요구사항**:
- AES-256-GCM 암호화 저장 (`cryptography` 라이브러리 — 이미 설치됨)
- 등록 시 `verify_api_key()` 호출로 키 유효성 + 권한 검증
- 출금(WITHDRAW) 권한 감지 시 경고
- API 키 마스킹 반환 (secret은 절대 반환하지 않음)
- 사용자당 거래소별 1개 계정 제한 (UniqueConstraint 활용)

---

## 2. 전체 아키텍처

### 2.1 암호화 흐름

```
[등록 요청]
    │
    ▼
Flutter App ──POST /api/v1/exchanges──▶ FastAPI Server
                                            │
                                            ▼
                                    ┌──────────────────┐
                                    │ 1. 중복 계정 확인   │
                                    │ 2. API 키 검증     │
                                    │    (verify_api_key) │
                                    │ 3. AES-256-GCM    │
                                    │    암호화           │
                                    │ 4. DB 저장         │
                                    └──────────────────┘
                                            │
                                            ▼
                                    ┌──────────────────┐
                                    │ PostgreSQL        │
                                    │ api_key_encrypted │
                                    │ api_secret_encrypted│
                                    │ (LargeBinary)     │
                                    └──────────────────┘
```

### 2.2 API 키 암호화/복호화 상세

```
암호화 (encrypt_value):
  plaintext → os.urandom(12) nonce → AESGCM.encrypt() → nonce(12) + ciphertext + tag(16)

복호화 (decrypt_value):
  encrypted[:12] = nonce, encrypted[12:] = ciphertext+tag → AESGCM.decrypt() → plaintext

키 소스: settings.EXCHANGE_API_KEY_SECRET (64자 hex → bytes.fromhex() → 32바이트 AES키)
```

**기존 구현 활용**: `server/app/core/encryption.py`에 `encrypt_value()`, `decrypt_value()` 함수가 이미 구현되어 있으므로 그대로 사용한다. TOTP 암호화와 동일한 AES-256-GCM 알고리즘이지만 별도 키(`EXCHANGE_API_KEY_SECRET`)를 사용한다.

### 2.3 API 흐름도

```
[등록] POST /api/v1/exchanges
  JWT 인증 → 중복 확인 → ExchangeProviderFactory.create() → provider.verify_api_key()
  → 출금 권한 경고 판단 → encrypt_value(api_key) → encrypt_value(api_secret) → DB INSERT

[목록] GET /api/v1/exchanges
  JWT 인증 → DB SELECT (user_id) → api_key 마스킹 → 응답

[수정] PUT /api/v1/exchanges/{id}
  JWT 인증 → 소유권 확인 → (api_key 변경 시) verify_api_key() → 암호화 → DB UPDATE

[삭제] DELETE /api/v1/exchanges/{id}
  JWT 인증 → 소유권 확인 → DB DELETE (CASCADE로 관련 데이터 정리)

[검증] POST /api/v1/exchanges/{id}/verify
  JWT 인증 → 소유권 확인 → decrypt → ExchangeProviderFactory.create() → verify_api_key()
  → DB UPDATE (is_verified, permissions, warning_level, last_verified_at)
```

---

## 3. 파일 구조

### 3.1 신규 파일

```
server/app/schemas/exchange.py          # ✅ 구현 완료 (code-architect, ST5)
server/app/repositories/exchange_account_repository.py  # DB 접근 계층
server/app/services/exchange_account_service.py         # 비즈니스 로직
server/app/api/v1/exchanges.py          # API 엔드포인트
server/alembic/versions/004_v1_11_exchange_account_extension.py  # ✅ 구현 완료 (code-architect, ST4)
server/tests/unit/test_exchange_account_service.py      # 서비스 단위 테스트
server/tests/api/test_exchanges_api.py  # API 통합 테스트
```

### 3.2 수정 파일

```
server/app/models/exchange.py           # ✅ 구현 완료 (code-architect, ST3)
server/app/core/exceptions.py           # ExchangeErrors에 에러 코드 추가
server/app/core/config.py               # EXCHANGE_API_KEY_SECRET 검증 추가
server/app/core/deps.py                 # DI 팩토리 추가
server/app/api/v1/__init__.py           # exchanges 라우터 등록
```

---

## 4. 데이터 모델 변경사항

> **ST3 구현 완료** (code-architect)

### 4.1 UserExchangeAccount 모델 확장

**파일**: `server/app/models/exchange.py`

추가된 컬럼:

```python
nickname: Mapped[str | None] = mapped_column(String(50), nullable=True)
is_verified: Mapped[bool] = mapped_column(
    pg.BOOLEAN, default=False, server_default=text("false")
)
warning_level: Mapped[str] = mapped_column(
    String(10), default="none", server_default=text("'none'"), nullable=False
)
verified_at: Mapped[datetime | None] = mapped_column(
    DateTime(timezone=True), nullable=True
)
```

추가된 제약조건:
```python
CheckConstraint(
    "warning_level IN ('none', 'warning', 'critical')",
    name="ck_exchange_account_warning_level",
)
```

| 컬럼 | 타입 | 기본값 | 용도 |
|------|------|--------|------|
| `nickname` | String(50), nullable | NULL | 사용자 지정 계정 별칭 (예: "메인 업비트") |
| `is_verified` | BOOLEAN | false | API 키 검증 완료 여부 |
| `warning_level` | String(10), NOT NULL | "none" | "none" \| "warning" \| "critical" (DB CHECK 제약) |
| `verified_at` | DateTime(tz), nullable | NULL | 마지막 검증 시각 |

### 4.2 UniqueConstraint 활용

기존 `uq_exchange_account_user_type` 제약조건이 `(user_id, exchange_type)` 조합의 유니크를 보장하므로 별도 추가 없이 사용자당 거래소별 1개 계정 제한이 적용된다.

### 4.3 warning_level 값 매핑

| DB 값 | 의미 | 설정 조건 |
|--------|------|----------|
| `none` | 정상 | 출금 권한 미포함 |
| `warning` | 경고 | `has_withdraw_permission == True` (출금 권한 감지) |
| `critical` | 위험 | 향후 확장 (비정상 활동 감지 등) |

---

## 5. API 엔드포인트 상세

### 5.1 POST /api/v1/exchanges — API 키 등록

**인증**: Bearer JWT (필수)

**요청 바디**:
```json
{
  "exchange_type": "upbit",
  "api_key": "xxxxxxxx",
  "api_secret": "yyyyyyyy",
  "nickname": "메인 업비트"
}
```

**요청 스키마**: `RegisterExchangeRequest` (ST5 구현 완료)

**성공 응답** (201):
```json
{
  "data": {
    "id": "uuid",
    "exchange_type": "upbit",
    "nickname": "메인 업비트",
    "api_key_masked": "****123456",
    "permissions": ["view_balance", "trade"],
    "is_active": true,
    "is_verified": true,
    "warning_level": "none",
    "verified_at": "2026-03-13T10:00:00Z",
    "created_at": "2026-03-13T10:00:00Z",
    "updated_at": "2026-03-13T10:00:00Z"
  },
  "error": null,
  "meta": {"timestamp": "..."}
}
```

**에러 응답**:
| HTTP | 코드 | 상황 |
|------|------|------|
| 409 | EXCHANGE_DUPLICATE_ACCOUNT | 이미 해당 거래소 계정 등록됨 |
| 422 | EXCHANGE_INVALID_API_KEY | API 키 검증 실패 |
| 500 | EXCHANGE_ENCRYPTION_NOT_CONFIGURED | EXCHANGE_API_KEY_SECRET 미설정 |
| 503 | EXCHANGE_UNAVAILABLE | 거래소 연결 불가 |

**처리 흐름**:
1. JWT에서 user_id 추출
2. `EXCHANGE_API_KEY_SECRET` 설정 여부 확인
3. `(user_id, exchange_type)` 중복 확인
4. `ExchangeProviderFactory.create()` → `provider.verify_api_key()` 호출
5. `ApiKeyInfo.is_valid == False`이면 422 반환
6. `has_withdraw_permission == True`이면 `warning_level = "warning"`
7. `encrypt_value(api_key)`, `encrypt_value(api_secret)` → DB INSERT
8. 마스킹된 응답 반환

### 5.2 GET /api/v1/exchanges — 등록된 거래소 계정 목록

**인증**: Bearer JWT (필수)

**응답 형식**: `ApiResponse[list[ExchangeAccountResponse]]` — 별도 `ExchangeAccountListResponse` wrapper 불필요. `ApiResponse`가 `data` 필드로 래핑하므로 `list[ExchangeAccountResponse]`를 직접 반환한다.

**성공 응답** (200):
```json
{
  "data": [
    {
      "id": "uuid",
      "exchange_type": "upbit",
      "nickname": "메인 업비트",
      "api_key_masked": "****123456",
      "permissions": ["view_balance", "trade"],
      "is_active": true,
      "is_verified": true,
      "warning_level": "none",
      "verified_at": "2026-03-13T10:00:00Z",
      "created_at": "...",
      "updated_at": "..."
    }
  ],
  "error": null,
  "meta": {"timestamp": "..."}
}
```

### 5.3 PUT /api/v1/exchanges/{id} — API 키 수정

**인증**: Bearer JWT (필수)

**요청 바디** (모두 선택적):
```json
{
  "api_key": "new-key",
  "api_secret": "new-secret",
  "nickname": "변경된 별칭"
}
```

**요청 스키마**: `UpdateExchangeRequest` (ST5 구현 완료, 빈 문자열 validator 포함)

**처리 흐름**:
1. 소유권 확인 (`account.user_id == current_user.id`)
2. `api_key` 또는 `api_secret` 변경 시:
   - 둘 다 필수 (하나만 변경 불가 — 검증 시 쌍으로 필요)
   - `verify_api_key()` 재호출
   - 암호화 후 DB UPDATE
3. `nickname`만 변경 시 직접 UPDATE

**에러 응답**:
| HTTP | 코드 | 상황 |
|------|------|------|
| 400 | EXCHANGE_KEY_PAIR_REQUIRED | api_key/api_secret 중 하나만 제공 |
| 404 | EXCHANGE_ACCOUNT_NOT_FOUND | 계정 없음 또는 타 사용자 소유 |
| 422 | EXCHANGE_INVALID_API_KEY | 새 API 키 검증 실패 |

### 5.4 DELETE /api/v1/exchanges/{id} — API 키 삭제

**인증**: Bearer JWT (필수)

**성공 응답** (200):
```json
{
  "data": {
    "message": "거래소 계정이 삭제되었습니다."
  },
  "error": null,
  "meta": {"timestamp": "..."}
}
```

**처리 흐름**:
1. 소유권 확인
2. DB DELETE (CASCADE로 watchlist_coins, trade_orders, price_alerts 자동 정리)

**에러 응답**:
| HTTP | 코드 | 상황 |
|------|------|------|
| 404 | EXCHANGE_ACCOUNT_NOT_FOUND | 계정 없음 |

### 5.5 POST /api/v1/exchanges/{id}/verify — API 키 테스트

**인증**: Bearer JWT (필수)

**응답 스키마**: `ExchangeVerifyResponse` (ST5 구현 완료)

**성공 응답** (200):
```json
{
  "data": {
    "is_valid": true,
    "permissions": ["view_balance", "trade"],
    "has_withdraw_permission": false,
    "warning_level": "none",
    "message": null
  },
  "error": null,
  "meta": {"timestamp": "..."}
}
```

**처리 흐름**:
1. 소유권 확인
2. `decrypt_value()` → 평문 API 키 복원
3. `ExchangeProviderFactory.create()` → `verify_api_key()` 호출
4. DB UPDATE: `is_verified`, `permissions`, `warning_level`, `verified_at`
5. 결과 반환

---

## 6. API 키 마스킹 규칙

> ST5에서 `mask_api_key()` 함수로 구현 완료 (code-architect)

```python
def mask_api_key(key: str) -> str:
    """API 키를 마스킹하여 반환.

    규칙:
    - 마지막 6자 노출, 앞부분 '****'로 대체
    - 6자 이하 → '****'
    - 예: "abcdef123456" → "****123456"
    """
    if len(key) <= 6:
        return "****"
    return "****" + key[-6:]
```

- `api_secret`은 절대 클라이언트에 반환하지 않음
- 마스킹은 서비스 레이어에서 수행 (복호화 후 마스킹 → 즉시 평문 폐기)

---

## 7. 서비스 레이어 설계

### 7.1 ExchangeAccountService

**파일**: `server/app/services/exchange_account_service.py`

```python
class ExchangeAccountService:
    def __init__(
        self,
        repo: ExchangeAccountRepository,
        factory: ExchangeProviderFactory,
        settings: Settings,
    ) -> None: ...

    async def register(self, user_id: UUID, req: RegisterExchangeRequest) -> ExchangeAccountResponse: ...
    async def list_accounts(self, user_id: UUID) -> list[ExchangeAccountResponse]: ...
    async def update(self, user_id: UUID, account_id: UUID, req: UpdateExchangeRequest) -> ExchangeAccountResponse: ...
    async def delete(self, user_id: UUID, account_id: UUID) -> None: ...
    async def verify(self, user_id: UUID, account_id: UUID) -> ExchangeVerifyResponse: ...

    def _get_encryption_key(self) -> bytes: ...
```

### 7.2 ExchangeAccountRepository

**파일**: `server/app/repositories/exchange_account_repository.py`

```python
class ExchangeAccountRepository:
    def __init__(self, db: AsyncSession) -> None: ...

    async def create(self, **kwargs) -> UserExchangeAccount: ...
    async def get_by_id(self, account_id: UUID) -> UserExchangeAccount | None: ...
    async def get_by_user_id(self, user_id: UUID) -> list[UserExchangeAccount]: ...
    async def get_by_user_and_exchange(self, user_id: UUID, exchange_type: str) -> UserExchangeAccount | None: ...
    async def update(self, account_id: UUID, **kwargs) -> UserExchangeAccount: ...
    async def delete(self, account_id: UUID) -> None: ...
```

---

## 8. DI (Dependency Injection) 설계

**파일**: `server/app/core/deps.py` 수정

```python
# 추가할 DI 팩토리
from app.repositories.exchange_account_repository import ExchangeAccountRepository
from app.services.exchange_account_service import ExchangeAccountService

def get_exchange_account_repository(db: AsyncSession = Depends(get_db)) -> ExchangeAccountRepository:
    return ExchangeAccountRepository(db)

def get_exchange_account_service(
    repo: ExchangeAccountRepository = Depends(get_exchange_account_repository),
    factory: ExchangeProviderFactory = Depends(get_exchange_factory),
    settings: Settings = Depends(get_settings),
) -> ExchangeAccountService:
    return ExchangeAccountService(repo, factory, settings)

# Type alias
ExchangeAccountServiceDep = Annotated[ExchangeAccountService, Depends(get_exchange_account_service)]
ExchangeAccountRepoDep = Annotated[ExchangeAccountRepository, Depends(get_exchange_account_repository)]
```

---

## 9. 에러 코드 추가

**파일**: `server/app/core/exceptions.py` — `ExchangeErrors` 클래스 확장

```python
@staticmethod
def duplicate_exchange_account(exchange: str) -> AppError:
    """이미 등록된 거래소 계정."""
    return AppError(
        "EXCHANGE_DUPLICATE_ACCOUNT",
        f"{exchange} 거래소 계정이 이미 등록되어 있습니다.",
        409,
    )

@staticmethod
def encryption_key_not_configured() -> AppError:
    """암호화 키 미설정."""
    return AppError(
        "EXCHANGE_ENCRYPTION_NOT_CONFIGURED",
        "거래소 API 키 암호화 설정이 완료되지 않았습니다.",
        500,
    )

@staticmethod
def key_pair_required() -> AppError:
    """API 키 쌍 불완전 제공."""
    return AppError(
        "EXCHANGE_KEY_PAIR_REQUIRED",
        "API 키와 시크릿은 함께 변경해야 합니다.",
        400,
    )
```

---

## 10. 설정 변경

**파일**: `server/app/core/config.py`

`EXCHANGE_API_KEY_SECRET`은 이미 선언되어 있다 (line 39). 추가 검증 로직을 `model_validator`에 포함한다:

```python
@model_validator(mode="after")
def _validate_encryption_keys(self) -> "Settings":
    """TOTP_ENCRYPTION_KEY, EXCHANGE_API_KEY_SECRET 형식 검증."""
    for key_name in ("TOTP_ENCRYPTION_KEY", "EXCHANGE_API_KEY_SECRET"):
        key = getattr(self, key_name)
        if key:
            if len(key) != 64:
                raise ValueError(f"{key_name} must be 64 hex characters (32 bytes). Got {len(key)} characters.")
            try:
                bytes.fromhex(key)
            except ValueError:
                raise ValueError(f"{key_name} must be a valid hex string.")
    return self
```

---

## 11. 라우터 등록

**파일**: `server/app/api/v1/__init__.py`

```python
from app.api.v1.exchanges import router as exchanges_router
router.include_router(exchanges_router, prefix="/exchanges", tags=["exchanges"])
```

---

## 12. 의존성 그래프 (서브태스크 간)

```
ST1: 암호화 유틸리티 모듈 (이미 구현됨 — encrypt_value/decrypt_value)
     └─ config.py 검증 로직 추가만 필요

ST3: 모델 확장 ──────────────────────────┐
     │                                   │
     ▼                                   │
ST4: 마이그레이션 생성                      │
                                         │
ST5: API 스키마 정의 ◄───────────────────┘
     │
     ▼
ST6: Repository 구현 ◄── ST3
     │
     ├──────────────────────────┐
     ▼                          ▼
ST7: 등록 엔드포인트 ◄── ST1,ST2  ST8: 조회 엔드포인트
     │
     ▼
ST9: 수정/삭제 엔드포인트

ST2: API 검증 서비스 ◄── (providers/base.py의 verify_api_key 활용)

ST10: E2E 테스트 ◄── ST7, ST8, ST9
```

### 의존성 요약

| 서브태스크 | 의존 | 담당 | 상태 |
|-----------|------|------|------|
| ST1: 암호화 유틸리티 | 없음 (이미 구현됨, 설정 검증만 추가) | python-backend-expert | 대기 |
| ST2: API 검증 서비스 | ST1 | python-backend-expert | 대기 |
| ST3: 모델 확장 | 없음 | code-architect | ✅ 완료 |
| ST4: 마이그레이션 | ST3 | code-architect | ✅ 완료 |
| ST5: API 스키마 | ST3 | code-architect | ✅ 완료 |
| ST6: Repository | ST3, ST5 | python-backend-expert | 대기 |
| ST7: 등록 엔드포인트 | ST1, ST2, ST5, ST6 | python-backend-expert | 대기 |
| ST8: 조회 엔드포인트 | ST5, ST6 | python-backend-expert | 대기 |
| ST9: 수정/삭제 엔드포인트 | ST1, ST2, ST5, ST6, ST7 | python-backend-expert | 대기 |
| ST10: E2E 테스트 | ST2, ST5~ST9 | e2e-test-expert | 대기 |

---

## 13. 테스트 전략

### 13.1 단위 테스트 (`server/tests/unit/`)

- **test_encryption.py**: `encrypt_value` / `decrypt_value` 라운드트립, 잘못된 키로 복호화 실패
- **test_exchange_account_service.py**:
  - 등록: 정상 흐름, 중복 계정, 검증 실패, 출금 권한 경고
  - 수정: API 키 쌍 변경, 닉네임만 변경, 소유권 검증
  - 삭제: 정상, 없는 계정
  - 검증: 성공, 실패, Provider 네트워크 오류
  - 마스킹: 다양한 길이 API 키

### 13.2 API 통합 테스트 (`server/tests/api/`)

- **test_exchanges_api.py**:
  - 인증 없이 접근 → 401
  - 등록 → 201 + 마스킹 확인
  - 목록 조회 → 200
  - 수정 (닉네임만) → 200
  - 수정 (API 키 쌍) → 200 + 재검증
  - 삭제 → 200
  - 중복 등록 → 409
  - 타 사용자 계정 접근 → 404

### 13.3 테스트 인프라

- `ExchangeProviderFactory` mock: `verify_api_key()`가 정상 `ApiKeyInfo` 반환하도록 설정
- 테스트용 `EXCHANGE_API_KEY_SECRET` 환경변수 설정
- `conftest.py`에 인증된 사용자 fixture 활용 (기존 auth 테스트에서 사용 중인 패턴)

---

## 14. 보안 고려사항

1. **암호화 키 관리**: `EXCHANGE_API_KEY_SECRET`은 환경변수로만 주입, `.env.example`에 플레이스홀더만 기재
2. **평문 노출 최소화**: 복호화된 API 키는 verify 호출 직후 즉시 폐기 (변수 스코프 제한)
3. **API 키 마스킹**: 모든 응답에서 `api_key_masked`만 반환, `api_secret`은 절대 반환하지 않음
4. **소유권 검증**: 모든 조작에서 `account.user_id == current_user.id` 확인
5. **출금 권한 경고**: `has_withdraw_permission == True`인 키 등록 시 `warning_level = "warning"` 설정 + 클라이언트에 경고 표시
6. **감사 로그**: 등록/삭제 시 MongoDB `audit_logs`에 기록 (기존 AuditService 활용)

---

## 15. 구현 순서 권장

1. ~~**Phase 1** (병렬 가능): ST1 (설정 검증) + ST3 (모델 확장)~~ — ST3 ✅ 완료
2. ~~**Phase 2** (ST3 완료 후 병렬): ST4 (마이그레이션) + ST5 (스키마)~~ — ST4, ST5 ✅ 완료
3. ~~**Phase 3** (즉시 착수 가능): ST1 (설정 검증) + ST6 (Repository) + ST2 (검증 서비스)~~ — ✅ 완료
4. ~~**Phase 4** (ST6 완료 후 병렬): ST7 (등록) + ST8 (조회)~~ — ✅ 완료
5. ~~**Phase 5**: ST9 (수정/삭제)~~ — ✅ 완료
6. ~~**Phase 6**: ST10 (E2E 테스트)~~ — ✅ 완료 (35/35 PASS)

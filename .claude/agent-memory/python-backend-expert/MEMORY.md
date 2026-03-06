# python-backend-expert Memory

## 팀 에이전트 이름 (정확한 recipient)
- 코드 리뷰어: **code-review-expert** (code-reviewer 아님 — 잘못된 이름으로 보내면 미전달)

## 프로젝트 구조 (server/app/)

- **models/**: SQLAlchemy ORM (PostgreSQL)
- **documents/**: Beanie ODM (MongoDB)
- **repositories/**: AsyncSession 기반 Repository
- **services/**: 비즈니스 로직 서비스
- **api/v1/**: FastAPI 라우터
- **core/**: config, deps, security, exceptions 등 공통 모듈
- **schemas/**: Pydantic v2 요청/응답 모델

## 핵심 패턴

### 에러 처리
- `AppError(code, message, http_status)` 베이스 예외
- `AuthErrors` 정적 팩토리 메서드로 도메인 에러 생성
- `register_error_handlers()` 에서 `@app.exception_handler(AppError)` 등록
- 에러 응답: `{"error": {"code": ..., "message": ..., "correlation_id": ...}}`
- `model_dump(exclude_none=True)` 사용하여 null 필드 제외

### 인증 시스템 (v1-5)
- **JWT**: python-jose, HS256, access 30분 / refresh 14일
- **Refresh Token**: SHA-256 해시만 Redis 저장 (원본 금지)
- **bcrypt**: passlib CryptContext, rounds=12
- **인증 코드**: `secrets.randbelow(10**6)` → zfill(6)
- **deps.py**: `CurrentUser`, `AuthServiceDep`, `CurrentUserOptional` 타입 별칭
- **oauth2_scheme**: `OAuth2PasswordBearer(tokenUrl="...", auto_error=False)` — auto_error=False로 토큰 없을 때 None 반환

### 표준 응답
- `ApiResponse[T]` 제네릭 래퍼: `data`, `error: None`, `meta.timestamp`
- 성공 응답은 `ApiResponse` 래핑, 에러는 `{"error": ...}` 직접 반환

### 의존성 주입 체인
```
Router → get_auth_service() → AuthService(UserRepository, AuthCacheService, EmailService, Settings)
Router → get_current_user() → decode_access_token() → UserRepository.get_by_id()
```

### 테스트 패턴
- `@pytest.mark.anyio` 데코레이터
- `httpx.AsyncClient(transport=ASGITransport(app=...))` 사용
- `app.dependency_overrides[get_auth_service] = lambda: mock_svc` 로 서비스 모킹
- `app.dependency_overrides[get_current_user] = lambda: mock_user` 로 인증 바이패스

### 2FA 시스템 (v1-7)
- **TOTP 암호화**: `core/encryption.py` — AES-256-GCM, nonce(12)+ciphertext+tag
- **백업 코드**: 10자리 × 10개, SHA-256 해시 저장, `user_totp_backup_codes` 테이블
- **temp_token**: `secrets.token_urlsafe(32)`, SHA-256 해시를 Redis 키로, GETDEL 1회 사용
- **브루트포스 방지**: `auth:2fa_fail:{user_id}` — 5회/15분 고정 윈도우
- **AuthService 확장**: `verify_credentials()` (자격증명만), `issue_tokens_with_store()` (토큰발급+Redis저장) 분리
- **Login 2FA 분기**: API 레이어(auth.py)에서 오케스트레이션 (AuthService에 미주입)
- **LoginResponse**: nullable 필드로 통합 — `requires_2fa`, `temp_token`, `user`, `tokens`
- **AuthCacheService 2FA 메서드**: `store_2fa_setup_secret`, `get_2fa_setup_secret`, `delete_2fa_setup_secret`, `store_2fa_login_pending`, `get_and_delete_2fa_login_pending`

### 세션 관리 (v1-7)
- **ClientRepository**: `repositories/client_repository.py` — fingerprint 기반 중복 감지
- **SessionService**: `services/session_service.py` — create_or_update_session 반환 `(Client, is_new_device)`
- **디바이스 타입 추론**: `extract_device_type(user_agent)` → ios/android/web
- **세션 종료**: Client.is_active=False (soft-delete) + Redis refresh token 즉시 폐기

### Audit Logging (v1-7)
- **AuditService**: `services/audit_service.py` — fire-and-forget, try-except 격리
- **AuditAction**: 상수 클래스 — login_success, 2fa_enabled 등 12개 액션
- **MongoDB**: `documents/audit_logs.py` Beanie Document에 `await audit.insert()`

## 완료된 태스크

- **v1-5**: JWT 인증 시스템 전체 구현
  - ST1: User soft_deleted_at 필드 + schemas/auth.py + schemas/common.py
  - ST2: core/security.py (JWT/bcrypt/hash_token/email_code)
  - ST3: services/email_service.py + config.py SMTP 설정
  - ST4: core/exceptions.py + repositories/user_repository.py + services/auth_service.py
  - ST5: core/deps.py CurrentUser/AuthServiceDep 추가
  - ST6: api/v1/auth.py + __init__.py 라우터 등록
  - ST7: api/v1/users.py (GET/PUT/DELETE /users/me)
  - ST8: middleware/error_handler.py AppError 핸들러 + tests/integration/test_auth_api.py

- **v1-7**: 2FA + 세션 관리 + Audit Logging 구현
  - ST2+ST3: core/encryption.py
  - ST4: repositories/user_repository.py 2FA 메서드 추가
  - ST5: repositories/client_repository.py + services/session_service.py
  - ST6: services/two_factor_service.py + schemas/two_factor.py
  - ST7: schemas/session.py + api/v1/auth.py 세션 엔드포인트
  - ST8: auth_service.py verify_credentials/issue_tokens_with_store + auth.py 로그인 분기
  - ST9: services/audit_service.py
  - **리뷰 반영**: AuthService 캡슐화(위임 메서드), Redis 키 설계서 준수(인덱스 키 패턴), Access Token client_id 클레임, bulk UPDATE, 파이프라인
  - **65/65 테스트 통과**, 코드 리뷰 승인 완료

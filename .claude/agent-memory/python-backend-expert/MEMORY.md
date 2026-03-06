# python-backend-expert Memory

## 팀 에이전트 이름 (정확한 recipient)
- 코드 리뷰어: **code-reviewer** (code-review-expert 아님 — 잘못된 이름으로 보내면 미전달)

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

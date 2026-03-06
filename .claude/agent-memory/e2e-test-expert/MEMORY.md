# e2e-test-expert 메모리

## 프로젝트 환경

- **Python**: Homebrew Python 3.14 (`/opt/homebrew/bin/python3.14`)
- **venv 위치**: `server/.venv/` (직접 생성 필요, 프로젝트에 기본 포함 안 됨)
- **테스트 실행**: `PYTHONPATH=. .venv/bin/python -m pytest tests/ -v` (server/ 디렉토리에서)
- **pytest 설정**: `asyncio_mode = "auto"`, `asyncio_default_fixture_loop_scope = "session"`
- **async 마커**: 기존 테스트는 `@pytest.mark.anyio` 사용 (asyncio_mode=auto와 호환)

## 핵심 패턴

### FastAPI 테스트 앱 픽스처
```python
@pytest.fixture
def test_app() -> FastAPI:
    app = FastAPI()
    register_error_handlers(app)
    app.add_middleware(CorrelationIdMiddleware)
    # 테스트 엔드포인트 추가
    return app

@pytest.fixture
async def client(test_app: FastAPI):
    async with AsyncClient(
        transport=ASGITransport(app=test_app), base_url="http://test"
    ) as ac:
        yield ac
```

### Prometheus 중복 등록 방지
- `scope="module"` fixture 사용 → 모듈당 한 번만 Instrumentator 생성
- `Instrumentator`는 `registry` 파라미터 없음 (prometheus_fastapi_instrumentator 기준)

## Starlette ServerErrorMiddleware 동작 (중요!)

**발견**: `@app.exception_handler(Exception)` 핸들러는 `ExceptionMiddleware`가 아닌 `ServerErrorMiddleware`에 등록됨.

```python
# starlette/applications.py build_middleware_stack()
for key, value in self.exception_handlers.items():
    if key in (500, Exception):
        error_handler = value  # → ServerErrorMiddleware
    else:
        exception_handlers[key] = value  # → ExceptionMiddleware
```

**핵심**: `ServerErrorMiddleware`는 핸들러 실행 후 **항상 예외를 re-raise**함 (로깅 목적).
```python
# starlette/middleware/errors.py
# We always continue to raise the exception.
# This allows servers to log the error, or allows test clients to optionally raise.
raise exc
```

**테스트 해결책**: `ASGITransport(raise_app_exceptions=False)` 사용
```python
@pytest.fixture
async def bare_client(app):
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as ac:
        yield ac
```

**Production 영향**: uvicorn은 re-raise를 로깅용으로 처리하고 500 응답은 정상 전송됨.

## BaseHTTPMiddleware + Exception Handler 주의사항

`BaseHTTPMiddleware`(CorrelationIdMiddleware 등)가 체인에 있을 때:
- `HTTPException` → `ExceptionMiddleware`에서 정상 처리됨
- `RuntimeError` 등 unhandled exception → `ServerErrorMiddleware`에서 처리 후 re-raise

unhandled exception 테스트는 BaseHTTPMiddleware 없는 별도 fixture로 격리할 것.

## 완료된 테스트 파일

- `server/tests/test_correlation_id.py` — 7개 (Correlation ID 미들웨어) [v1-4]
- `server/tests/test_error_handler.py` — 14개 (에러 핸들러 포맷) [v1-4]
- `server/tests/test_middleware_chain.py` — 11개 (CORS, 미들웨어 순서, 헬스체크, Prometheus) [v1-4]
- `server/tests/integration/test_auth_api.py` — 28개 (회원가입, 로그인, 토큰갱신 등) [v1-5/7]
- `server/tests/integration/test_2fa_session_api.py` — 37개 (2FA setup/verify/disable/status, login-verify, 세션관리) [v1-7]

## AsyncMock 의존성 Mock 패턴 (중요!)

**원칙**: 엔드포인트가 `svc.method()` 직접 호출 시, `mock_svc.method.return_value`로 설정.
`svc._cache.method()` 등 내부 속성으로 위임하더라도, 반드시 **실제 엔드포인트 코드**를 읽고 어떤 객체의 어떤 메서드를 호출하는지 확인 후 Mock 설정.

```python
# ❌ 잘못: auth.py가 auth_svc.get_and_delete_2fa_login_pending() 직접 호출하는데
mock_auth_service._cache.get_and_delete_2fa_login_pending.return_value = data

# ✅ 올바름:
mock_auth_service.get_and_delete_2fa_login_pending.return_value = data
```

**AsyncMock 자동 메서드 생성**: `AsyncMock()` 인스턴스는 접근 시 자동으로 async 메서드 생성. 별도로 `AsyncMock(return_value=...)` 지정 필요.

## integration/conftest.py 패턴

MongoDB 모듈을 `sys.modules`에 mock 등록 (Pydantic v2 + bson.Decimal128 + Beanie 비호환 우회):
- `ModuleType` 인스턴스 사용 (MagicMock 사용 시 'is not a package' 에러)
- 서브모듈을 명시적으로 등록해야 함

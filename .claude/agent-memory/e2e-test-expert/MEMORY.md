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

## 완료된 테스트 파일 (v1-4)

- `server/tests/test_correlation_id.py` — 7개 (Correlation ID 미들웨어)
- `server/tests/test_error_handler.py` — 14개 (에러 핸들러 포맷)
- `server/tests/test_middleware_chain.py` — 11개 (CORS, 미들웨어 순서, 헬스체크, Prometheus)

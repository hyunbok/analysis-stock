"""글로벌 에러 핸들러 통합 테스트.

테스트 대상:
- 422 Validation Error 통일 포맷 (details 배열 포함)
- HTTP 4xx 에러 코드 매핑 (404 NOT_FOUND, 401 UNAUTHORIZED 등)
- 500 Internal Error (스택트레이스 미노출)
- 에러 응답 구조 검증 ({"error": {"code", "message", ...}})
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.exceptions import HTTPException
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel

from app.middleware.correlation_id import CorrelationIdMiddleware
from app.middleware.error_handler import register_error_handlers


class _Item(BaseModel):
    name: str
    price: float


@pytest.fixture
def test_app() -> FastAPI:
    """에러 핸들러 + Correlation ID 미들웨어 포함 테스트 앱 (HTTPException 테스트용)."""
    app = FastAPI()
    register_error_handlers(app)
    app.add_middleware(CorrelationIdMiddleware)

    @app.get("/ok")
    async def ok():
        return {"status": "ok"}

    @app.post("/items")
    async def create_item(item: _Item):
        return item

    @app.get("/http-error/{status_code}")
    async def http_error(status_code: int):
        raise HTTPException(status_code=status_code, detail=f"Error {status_code}")

    return app


@pytest.fixture
def test_app_no_middleware() -> FastAPI:
    """에러 핸들러만 등록한 테스트 앱 (exception_handler(Exception) 단독 테스트용).

    BaseHTTPMiddleware(CorrelationIdMiddleware) 없이 exception_handler(Exception)을
    직접 검증한다. BaseHTTPMiddleware + call_next()를 통과하는 RuntimeError는
    Starlette 내부에서 재전파되어 exception_handler에 도달하지 못하는 특성이 있음.
    """
    app = FastAPI()
    register_error_handlers(app)

    @app.get("/http-error/{status_code}")
    async def http_error(status_code: int):
        raise HTTPException(status_code=status_code, detail=f"Error {status_code}")

    @app.get("/unhandled-error")
    async def unhandled_error():
        raise RuntimeError("Unexpected internal error")

    return app


@pytest.fixture
async def client(test_app: FastAPI):
    async with AsyncClient(
        transport=ASGITransport(app=test_app), base_url="http://test"
    ) as ac:
        yield ac


@pytest.fixture
async def bare_client(test_app_no_middleware: FastAPI):
    """raise_app_exceptions=False: ServerErrorMiddleware의 의도적 raise exc 무시.

    Starlette의 ServerErrorMiddleware는 핸들러 실행 후 항상 예외를 re-raise한다.
    (서버 로깅 및 테스트 클라이언트 옵셔널 재전파를 위한 설계)
    ASGITransport에서 이를 억제하고 응답만 반환받는다.
    """
    async with AsyncClient(
        transport=ASGITransport(app=test_app_no_middleware, raise_app_exceptions=False),
        base_url="http://test",
    ) as ac:
        yield ac


# ── 422 Validation Error ──────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_422_validation_error_unified_format(client: AsyncClient):
    """422 Validation Error → 통일 포맷, error.code == VALIDATION_ERROR."""
    response = await client.post("/items", json={"name": "test"})  # price 누락

    assert response.status_code == 422
    body = response.json()
    assert "error" in body
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["message"] == "Request validation failed"


@pytest.mark.anyio
async def test_422_validation_error_has_details_array(client: AsyncClient):
    """422 에러 → details 배열 포함, 각 항목에 field·message·type 존재."""
    response = await client.post("/items", json={})  # name, price 모두 누락

    assert response.status_code == 422
    details = response.json()["error"]["details"]

    assert isinstance(details, list)
    assert len(details) >= 2  # name, price 두 필드 에러

    for detail in details:
        assert "field" in detail
        assert "message" in detail
        assert "type" in detail


@pytest.mark.anyio
async def test_422_validation_error_field_names(client: AsyncClient):
    """422 에러 details의 field 값에 누락된 필드명 포함."""
    response = await client.post("/items", json={})

    details = response.json()["error"]["details"]
    fields = " ".join(d["field"] for d in details)

    assert "name" in fields
    assert "price" in fields


# ── HTTP 4xx 에러 코드 매핑 ────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_404_not_found_code_mapping(client: AsyncClient):
    """404 HTTPException → error.code == NOT_FOUND."""
    response = await client.get("/http-error/404")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


@pytest.mark.anyio
async def test_401_unauthorized_code_mapping(client: AsyncClient):
    """401 HTTPException → error.code == UNAUTHORIZED."""
    response = await client.get("/http-error/401")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


@pytest.mark.anyio
async def test_403_forbidden_code_mapping(client: AsyncClient):
    """403 HTTPException → error.code == FORBIDDEN."""
    response = await client.get("/http-error/403")

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


@pytest.mark.anyio
async def test_400_bad_request_code_mapping(client: AsyncClient):
    """400 HTTPException → error.code == BAD_REQUEST."""
    response = await client.get("/http-error/400")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "BAD_REQUEST"


@pytest.mark.anyio
async def test_409_conflict_code_mapping(client: AsyncClient):
    """409 HTTPException → error.code == CONFLICT."""
    response = await client.get("/http-error/409")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONFLICT"


@pytest.mark.anyio
async def test_http_exception_detail_as_message(client: AsyncClient):
    """HTTPException.detail이 error.message에 그대로 반영."""
    response = await client.get("/http-error/404")

    assert response.status_code == 404
    assert response.json()["error"]["message"] == "Error 404"


@pytest.mark.anyio
async def test_http_exception_has_no_details_array(client: AsyncClient):
    """HTTPException 응답에는 details 배열 없음 (exclude_none=True)."""
    response = await client.get("/http-error/404")

    error = response.json()["error"]
    assert "details" not in error


# ── 500 Internal Error ────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_500_internal_error_code(bare_client: AsyncClient):
    """Unhandled Exception → 500 응답, error.code == INTERNAL_ERROR.

    BaseHTTPMiddleware 없이 exception_handler(Exception)만으로 검증한다.
    """
    response = await bare_client.get("/unhandled-error")

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"


@pytest.mark.anyio
async def test_500_internal_error_generic_message(bare_client: AsyncClient):
    """500 응답 → 서버 내부 에러 일반 메시지, 예외 내용 미노출."""
    response = await bare_client.get("/unhandled-error")

    body = response.json()
    assert body["error"]["message"] == "An unexpected error occurred"


@pytest.mark.anyio
async def test_500_internal_error_no_stacktrace(bare_client: AsyncClient):
    """500 응답 → 스택트레이스, 예외 클래스명 미노출."""
    response = await bare_client.get("/unhandled-error")

    body_str = str(response.json())
    assert "Traceback" not in body_str
    assert "RuntimeError" not in body_str
    assert "traceback" not in body_str
    assert "Unexpected internal error" not in body_str  # 실제 예외 메시지 미노출


# ── 에러 응답 공통 구조 ──────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_error_response_top_level_key(client: AsyncClient, bare_client: AsyncClient):
    """모든 에러 응답의 최상위 키는 'error'."""
    r1 = await client.get("/http-error/404")
    assert list(r1.json().keys()) == ["error"], "/http-error/404: 최상위 키가 'error'가 아님"

    r2 = await bare_client.get("/unhandled-error")
    assert list(r2.json().keys()) == ["error"], "/unhandled-error: 최상위 키가 'error'가 아님"


@pytest.mark.anyio
async def test_error_body_has_required_fields(client: AsyncClient):
    """에러 바디에 code, message 필드 존재."""
    response = await client.get("/http-error/404")

    error = response.json()["error"]
    assert "code" in error
    assert "message" in error

"""Correlation ID 미들웨어 통합 테스트.

테스트 대상:
- X-Correlation-ID 자동 생성 (UUID4 포맷)
- 클라이언트 제공 ID 전파 (요청 헤더 → 응답 헤더)
- 에러 응답 바디에 correlation_id 포함
- Validation Error에도 correlation_id 포함
"""
from __future__ import annotations

import re

import pytest
from fastapi import FastAPI
from fastapi.exceptions import HTTPException
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel

from app.middleware.correlation_id import CORRELATION_ID_HEADER, CorrelationIdMiddleware
from app.middleware.error_handler import register_error_handlers

UUID4_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


class _ValidateBody(BaseModel):
    name: str


@pytest.fixture
def test_app() -> FastAPI:
    """CorrelationIdMiddleware + 에러 핸들러만 포함한 최소 테스트 앱."""
    app = FastAPI()
    register_error_handlers(app)
    app.add_middleware(CorrelationIdMiddleware)

    @app.get("/ping")
    async def ping():
        return {"ok": True}

    @app.get("/not-found")
    async def not_found():
        raise HTTPException(status_code=404, detail="Resource not found")

    @app.get("/server-error")
    async def server_error():
        raise HTTPException(status_code=500, detail="Internal error via HTTPException")

    @app.post("/validate")
    async def validate(body: _ValidateBody):
        return body

    return app


@pytest.fixture
async def client(test_app: FastAPI):
    async with AsyncClient(
        transport=ASGITransport(app=test_app), base_url="http://test"
    ) as ac:
        yield ac


@pytest.mark.anyio
async def test_auto_generates_uuid4_correlation_id(client: AsyncClient):
    """X-Correlation-ID 없이 요청 시 UUID4 자동 생성 후 응답 헤더에 포함."""
    response = await client.get("/ping")

    assert response.status_code == 200
    cid = response.headers.get(CORRELATION_ID_HEADER)
    assert cid is not None, "X-Correlation-ID 헤더가 응답에 없음"
    assert UUID4_RE.match(cid), f"UUID4 형식 아님: {cid}"


@pytest.mark.anyio
async def test_requests_get_different_correlation_ids(client: AsyncClient):
    """독립된 요청은 서로 다른 Correlation ID를 가진다."""
    r1 = await client.get("/ping")
    r2 = await client.get("/ping")

    cid1 = r1.headers.get(CORRELATION_ID_HEADER)
    cid2 = r2.headers.get(CORRELATION_ID_HEADER)
    assert cid1 != cid2


@pytest.mark.anyio
async def test_client_provided_id_propagated(client: AsyncClient):
    """클라이언트 제공 X-Correlation-ID가 응답 헤더에 그대로 반환."""
    custom_id = "my-custom-trace-id"

    response = await client.get("/ping", headers={CORRELATION_ID_HEADER: custom_id})

    assert response.status_code == 200
    assert response.headers.get(CORRELATION_ID_HEADER) == custom_id


@pytest.mark.anyio
async def test_error_response_contains_correlation_id(client: AsyncClient):
    """404 에러 응답 JSON 바디에 correlation_id 포함 (헤더와 동일)."""
    response = await client.get("/not-found")

    assert response.status_code == 404
    body = response.json()
    cid_in_header = response.headers.get(CORRELATION_ID_HEADER)
    cid_in_body = body["error"].get("correlation_id")

    assert cid_in_body is not None, "에러 바디에 correlation_id 없음"
    assert cid_in_body == cid_in_header, "바디와 헤더의 correlation_id 불일치"


@pytest.mark.anyio
async def test_client_provided_id_in_error_body(client: AsyncClient):
    """클라이언트 제공 ID가 에러 응답 바디에도 반영."""
    custom_id = "client-trace-xyz"

    response = await client.get("/not-found", headers={CORRELATION_ID_HEADER: custom_id})

    assert response.status_code == 404
    assert response.json()["error"]["correlation_id"] == custom_id


@pytest.mark.anyio
async def test_validation_error_contains_correlation_id(client: AsyncClient):
    """422 Validation Error 바디에도 correlation_id 포함."""
    response = await client.post("/validate", json={})  # name 필드 누락

    assert response.status_code == 422
    body = response.json()
    cid = body["error"].get("correlation_id")

    assert cid is not None, "422 에러 바디에 correlation_id 없음"
    assert UUID4_RE.match(cid), f"UUID4 형식 아님: {cid}"


@pytest.mark.anyio
async def test_500_http_exception_contains_correlation_id(client: AsyncClient):
    """500 HTTPException 응답 바디에도 correlation_id 포함 (헤더와 일치)."""
    response = await client.get("/server-error")

    assert response.status_code == 500
    body = response.json()
    cid_in_header = response.headers.get(CORRELATION_ID_HEADER)
    cid_in_body = body["error"].get("correlation_id")

    assert cid_in_body is not None
    assert cid_in_body == cid_in_header

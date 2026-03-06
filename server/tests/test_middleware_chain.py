"""미들웨어 체인 통합 테스트.

테스트 대상:
- CORS Preflight (OPTIONS) 응답 헤더 검증
- expose_headers에 X-Correlation-ID 포함
- 미들웨어 실행 순서 (Correlation ID → Error Handler)
- Rate Limit 429 응답 통일 포맷
- 헬스체크 정상 응답
- Prometheus /metrics 엔드포인트 응답

참고: Prometheus 메트릭 중복 등록 방지를 위해 chain_app fixture를 module scope로 설정.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.exceptions import HTTPException
from fastapi.middleware.cors import CORSMiddleware
from httpx import ASGITransport, AsyncClient
from prometheus_fastapi_instrumentator import Instrumentator

from app.core.rate_limiter import RateLimitResult
from app.middleware.correlation_id import CORRELATION_ID_HEADER, CorrelationIdMiddleware
from app.middleware.error_handler import register_error_handlers
from app.middleware.rate_limit import RateLimitMiddleware

TEST_ORIGIN = "http://localhost:3000"


@pytest.fixture(scope="module")
def chain_app() -> FastAPI:
    """실제 main.py 미들웨어 체인을 재현한 테스트 앱.

    등록 순서 (LIFO — 마지막 등록이 가장 외부 실행):
      1. Prometheus instrumentator (가장 내부)
      2. CorrelationIdMiddleware
      3. CORSMiddleware (가장 외부)
    """
    _app = FastAPI()

    # 에러 핸들러 등록
    register_error_handlers(_app)

    # 테스트 엔드포인트
    @_app.get("/api/v1/health")
    async def health():
        return {
            "status": "healthy",
            "components": {"postgres": "up", "mongodb": "up", "redis": "up"},
        }

    @_app.get("/raise-error")
    async def raise_error():
        raise HTTPException(status_code=404, detail="Not here")

    # Prometheus — module scope fixture로 한 번만 등록 (중복 방지)
    _instrumentator = Instrumentator(
        should_group_status_codes=True,
        excluded_handlers=["/metrics", "/api/v1/health"],
    )
    _instrumentator.instrument(_app).expose(_app, endpoint="/metrics")

    # 미들웨어 등록 (LIFO)
    _app.add_middleware(CorrelationIdMiddleware)
    _app.add_middleware(
        CORSMiddleware,
        allow_origins=[TEST_ORIGIN],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=[
            "X-Correlation-ID",
            "X-RateLimit-Remaining",
            "X-RateLimit-Retry-After-Ms",
        ],
    )

    return _app


@pytest.fixture(scope="module")
async def client(chain_app: FastAPI):
    async with AsyncClient(
        transport=ASGITransport(app=chain_app), base_url="http://test"
    ) as ac:
        yield ac


# ── CORS Preflight ────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_cors_preflight_returns_allow_origin(client: AsyncClient):
    """OPTIONS Preflight → Access-Control-Allow-Origin 헤더 포함."""
    response = await client.options(
        "/api/v1/health",
        headers={
            "Origin": TEST_ORIGIN,
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code in (200, 204)
    assert response.headers.get("access-control-allow-origin") == TEST_ORIGIN


@pytest.mark.anyio
async def test_cors_preflight_returns_allow_methods(client: AsyncClient):
    """OPTIONS Preflight → Access-Control-Allow-Methods 헤더 포함."""
    response = await client.options(
        "/api/v1/health",
        headers={
            "Origin": TEST_ORIGIN,
            "Access-Control-Request-Method": "POST",
        },
    )

    assert response.status_code in (200, 204)
    assert "access-control-allow-methods" in response.headers


@pytest.mark.anyio
async def test_cors_preflight_allows_correlation_id_header(client: AsyncClient):
    """OPTIONS Preflight → X-Correlation-ID가 허용 헤더에 포함 가능."""
    response = await client.options(
        "/api/v1/health",
        headers={
            "Origin": TEST_ORIGIN,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "X-Correlation-ID",
        },
    )

    assert response.status_code in (200, 204)
    # allow_headers=["*"]이므로 모든 헤더 허용
    allowed = response.headers.get("access-control-allow-headers", "")
    assert allowed == "*" or "X-Correlation-ID" in allowed or "x-correlation-id" in allowed


@pytest.mark.anyio
async def test_cors_expose_headers_includes_correlation_id(client: AsyncClient):
    """일반 요청 응답에 access-control-expose-headers에 X-Correlation-ID 포함."""
    response = await client.get(
        "/api/v1/health",
        headers={"Origin": TEST_ORIGIN},
    )

    assert response.status_code == 200
    expose = response.headers.get("access-control-expose-headers", "")
    assert "X-Correlation-ID" in expose


# ── 미들웨어 순서 검증 ─────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_correlation_id_present_in_error_response_body(client: AsyncClient):
    """미들웨어 순서 검증: CorrelationId가 에러 핸들러보다 외부에서 실행.

    에러 응답 바디의 correlation_id와 응답 헤더의 X-Correlation-ID가 일치해야 한다.
    즉, 에러 핸들러 실행 시점에 contextvars에 correlation_id가 설정되어 있어야 함.
    """
    custom_id = "middleware-order-test"

    response = await client.get(
        "/raise-error",
        headers={CORRELATION_ID_HEADER: custom_id},
    )

    assert response.status_code == 404
    body = response.json()
    assert body["error"]["correlation_id"] == custom_id
    assert response.headers.get(CORRELATION_ID_HEADER) == custom_id


@pytest.mark.anyio
async def test_error_response_without_client_id_has_auto_id(client: AsyncClient):
    """Correlation ID 없는 에러 요청 → 자동 생성 ID가 헤더·바디 모두에 포함."""
    import re
    UUID4_RE = re.compile(
        r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
        re.IGNORECASE,
    )

    response = await client.get("/raise-error")

    assert response.status_code == 404
    cid_header = response.headers.get(CORRELATION_ID_HEADER)
    cid_body = response.json()["error"].get("correlation_id")

    assert UUID4_RE.match(cid_header)
    assert cid_header == cid_body


# ── 헬스체크 ─────────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_health_check_returns_200(client: AsyncClient):
    """GET /api/v1/health → 200 OK."""
    response = await client.get("/api/v1/health")

    assert response.status_code == 200


@pytest.mark.anyio
async def test_health_check_response_structure(client: AsyncClient):
    """헬스체크 응답에 status 필드 포함."""
    response = await client.get("/api/v1/health")

    body = response.json()
    assert "status" in body
    assert body["status"] in ("healthy", "unhealthy")


# ── Prometheus /metrics ────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_prometheus_metrics_endpoint_returns_200(client: AsyncClient):
    """GET /metrics → 200 OK."""
    response = await client.get("/metrics")

    assert response.status_code == 200


@pytest.mark.anyio
async def test_prometheus_metrics_content_type(client: AsyncClient):
    """GET /metrics → text/plain 형식 응답."""
    response = await client.get("/metrics")

    assert response.status_code == 200
    content_type = response.headers.get("content-type", "")
    assert "text/plain" in content_type


# ── Rate Limit 429 응답 포맷 ───────────────────────────────────────────────────

@pytest.mark.anyio
async def test_rate_limit_429_unified_error_format():
    """429 Rate Limit 응답이 통일 에러 포맷 준수.

    RateLimitMiddleware를 포함한 별도 앱에서 Rate Limit 초과를 강제하여
    응답 포맷을 검증한다. APIRateLimiter.check를 Mock하여 항상 초과 상태 반환.
    """
    _app = FastAPI()
    register_error_handlers(_app)
    _app.add_middleware(CorrelationIdMiddleware)
    _app.add_middleware(RateLimitMiddleware)

    @_app.get("/ping")
    async def ping():
        return {"ok": True}

    exceeded = RateLimitResult(allowed=False, remaining=0.0, retry_after_ms=5000)

    with patch("app.middleware.rate_limit.get_redis", return_value=MagicMock()):
        with patch("app.middleware.rate_limit.APIRateLimiter") as mock_cls:
            mock_limiter = AsyncMock()
            mock_limiter.check = AsyncMock(return_value=exceeded)
            mock_cls.return_value = mock_limiter

            async with AsyncClient(
                transport=ASGITransport(app=_app), base_url="http://test"
            ) as ac:
                response = await ac.get("/ping")

    assert response.status_code == 429
    body = response.json()
    assert "error" in body
    assert body["error"]["code"] == "RATE_LIMIT_EXCEEDED"
    assert body["error"]["message"] == "Too many requests"


@pytest.mark.anyio
async def test_rate_limit_429_response_headers():
    """429 Rate Limit 응답에 Retry-After, X-RateLimit-Remaining 헤더 포함."""
    _app = FastAPI()
    register_error_handlers(_app)
    _app.add_middleware(CorrelationIdMiddleware)
    _app.add_middleware(RateLimitMiddleware)

    @_app.get("/ping")
    async def ping():
        return {"ok": True}

    exceeded = RateLimitResult(allowed=False, remaining=0.0, retry_after_ms=3000)

    with patch("app.middleware.rate_limit.get_redis", return_value=MagicMock()):
        with patch("app.middleware.rate_limit.APIRateLimiter") as mock_cls:
            mock_limiter = AsyncMock()
            mock_limiter.check = AsyncMock(return_value=exceeded)
            mock_cls.return_value = mock_limiter

            async with AsyncClient(
                transport=ASGITransport(app=_app), base_url="http://test"
            ) as ac:
                response = await ac.get("/ping")

    assert response.status_code == 429
    assert "retry-after" in response.headers
    assert "x-ratelimit-remaining" in response.headers

"""Correlation ID 미들웨어 — 요청 추적용 고유 ID 생성 및 전파.

흐름: 요청 헤더 → contextvars → structlog → 응답 헤더
"""
from __future__ import annotations

import uuid
from contextvars import ContextVar

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

CORRELATION_ID_HEADER = "X-Correlation-ID"

# contextvars — 비동기 안전
correlation_id_ctx: ContextVar[str] = ContextVar("correlation_id", default="")


def get_correlation_id() -> str:
    """현재 요청의 Correlation ID 반환 (미들웨어 외부에서 사용)."""
    return correlation_id_ctx.get()


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """요청마다 Correlation ID를 생성/전파하는 미들웨어.

    1. 요청 헤더 X-Correlation-ID가 있으면 사용, 없으면 UUID4 생성
    2. structlog contextvars에 바인딩 → 모든 로그에 자동 포함
    3. 응답 헤더 X-Correlation-ID에 포함
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        raw = request.headers.get(CORRELATION_ID_HEADER, "")
        cid = raw[:128] if raw else str(uuid.uuid4())

        # contextvars에 저장
        token = correlation_id_ctx.set(cid)

        # structlog contextvars에 바인딩
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            correlation_id=cid,
            method=request.method,
            path=request.url.path,
        )

        try:
            response = await call_next(request)
            response.headers[CORRELATION_ID_HEADER] = cid
            return response
        finally:
            correlation_id_ctx.reset(token)
            structlog.contextvars.clear_contextvars()

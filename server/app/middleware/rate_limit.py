"""FastAPI Rate Limit 미들웨어 — 전역 API Rate Limiting."""
from __future__ import annotations

import json
import logging

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.core.rate_limiter import APIRateLimiter, RateLimitResult
from app.core.redis import get_redis

logger = logging.getLogger(__name__)

# Rate Limit을 건너뛸 경로 접두사
_SKIP_PREFIXES = ("/docs", "/redoc", "/openapi", "/metrics", "/health")


def _get_client_ip(request: Request) -> str:
    """X-Forwarded-For 헤더 우선, 없으면 직접 IP."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _too_many_response(result: RateLimitResult) -> JSONResponse:
    retry_after_sec = max(1, result.retry_after_ms // 1000)
    return JSONResponse(
        status_code=429,
        content={"error": {"code": "RATE_LIMIT_EXCEEDED", "message": "Too many requests"}},
        headers={
            "Retry-After": str(retry_after_sec),
            "X-RateLimit-Remaining": str(int(result.remaining)),
            "X-RateLimit-Retry-After-Ms": str(result.retry_after_ms),
        },
    )


class RateLimitMiddleware(BaseHTTPMiddleware):
    """전역 API Rate Limiting 미들웨어"""

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path
        if any(path.startswith(p) for p in _SKIP_PREFIXES):
            return await call_next(request)

        try:
            redis = get_redis()
            limiter = APIRateLimiter(redis)

            # 인증 여부 판단 — Authorization 헤더 존재 여부로 간단히 판별
            auth_header = request.headers.get("Authorization", "")
            authenticated = auth_header.startswith("Bearer ")

            if authenticated:
                # Bearer 토큰에서 user_id 추출은 비용이 크므로
                # 여기서는 토큰 자체를 식별자로 사용 (검증은 라우터에서)
                identifier = auth_header.removeprefix("Bearer ").strip()[:64]
            else:
                identifier = _get_client_ip(request)

            result = await limiter.check(identifier, authenticated)

            if not result.allowed:
                return _too_many_response(result)

            response = await call_next(request)
            response.headers["X-RateLimit-Remaining"] = str(int(result.remaining))
            return response

        except Exception:
            # Redis 장애 시 graceful degradation — 요청 허용
            logger.exception("Rate limit middleware error; allowing request")
            return await call_next(request)

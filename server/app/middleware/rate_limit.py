"""FastAPI Rate Limit 미들웨어 — 전역 API Rate Limiting.

미들웨어는 IP 기반 Rate Limit만 적용한다.
user_id 기반 Rate Limit은 라우터 레벨에서 ApiRateLimiter 의존성으로 처리.

IP 주소는 request.client.host를 사용한다. 역방향 프록시 환경에서는
starlette.middleware.trustedhost.TrustedHostMiddleware 또는
uvicorn --proxy-headers 옵션으로 X-Forwarded-For를 안전하게 처리해야 한다.
"""
from __future__ import annotations

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
    """클라이언트 IP 반환.

    request.client.host 사용 — 역방향 프록시 환경에서는 Starlette의
    ProxyHeadersMiddleware(또는 uvicorn --proxy-headers)가 X-Forwarded-For를
    검증 후 client.host를 올바르게 설정해 주어야 한다.
    """
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
    """전역 IP 기반 Rate Limiting 미들웨어.

    user_id 기반 Rate Limit은 JWT 디코딩 비용 때문에 라우터 레벨에서 처리.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path
        if any(path.startswith(p) for p in _SKIP_PREFIXES):
            return await call_next(request)

        try:
            redis = get_redis()
            limiter = APIRateLimiter(redis)

            # IP 기반 비인증 Rate Limit만 적용
            identifier = _get_client_ip(request)
            result = await limiter.check(identifier, authenticated=False)

            if not result.allowed:
                return _too_many_response(result)

            response = await call_next(request)
            response.headers["X-RateLimit-Remaining"] = str(int(result.remaining))
            return response

        except Exception:
            # Redis 장애 시 graceful degradation — 요청 허용
            logger.exception("Rate limit middleware error; allowing request")
            return await call_next(request)

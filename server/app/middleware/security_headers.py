"""보안 헤더 미들웨어 — HTTP 응답에 보안 관련 헤더 추가."""
from __future__ import annotations

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """모든 HTTP 응답에 보안 헤더를 추가하는 미들웨어.

    추가 헤더:
    - X-Content-Type-Options: MIME 스니핑 방지
    - X-Frame-Options: 클릭재킹 방지
    - X-XSS-Protection: XSS 필터 (구형 브라우저)
    - Strict-Transport-Security: HTTPS 강제 (1년, 서브도메인 포함)
    - Referrer-Policy: Referrer 정보 최소화
    - Permissions-Policy: 불필요한 브라우저 기능 비활성화
    - Content-Security-Policy: 리소스 로드 출처 제한
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self'; "
            "img-src 'self' data:; "
            "connect-src 'self'; "
            "frame-ancestors 'none'"
        )
        return response

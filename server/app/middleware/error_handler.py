"""글로벌 에러 핸들러 — 모든 예외를 통일 에러 응답으로 변환.

FastAPI의 exception_handler 데코레이터를 사용하여 등록.
미들웨어가 아닌 exception_handler로 구현하여 Starlette 미들웨어 체인과 분리.
"""
from __future__ import annotations

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse

from app.middleware.correlation_id import get_correlation_id
from app.schemas.error import ErrorBody, ErrorDetail

logger = structlog.get_logger(__name__)


def register_error_handlers(app: FastAPI) -> None:
    """앱에 글로벌 에러 핸들러 등록."""

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        details = [
            ErrorDetail(
                field=".".join(str(loc) for loc in err["loc"]),
                message=err["msg"],
                type=err["type"],
            )
            for err in exc.errors()
        ]
        body = ErrorBody(
            code="VALIDATION_ERROR",
            message="Request validation failed",
            details=details,
            correlation_id=get_correlation_id() or None,
        )
        logger.warning("validation_error", errors=exc.errors())
        return JSONResponse(
            status_code=422,
            content={"error": body.model_dump(exclude_none=True)},
        )

    @app.exception_handler(HTTPException)
    async def http_error_handler(
        request: Request, exc: HTTPException
    ) -> JSONResponse:
        code_map = {
            400: "BAD_REQUEST",
            401: "UNAUTHORIZED",
            403: "FORBIDDEN",
            404: "NOT_FOUND",
            409: "CONFLICT",
            429: "RATE_LIMIT_EXCEEDED",
        }
        body = ErrorBody(
            code=code_map.get(exc.status_code, f"HTTP_{exc.status_code}"),
            message=str(exc.detail),
            correlation_id=get_correlation_id() or None,
        )
        if exc.status_code >= 500:
            logger.error("http_error", status=exc.status_code, detail=exc.detail)
        else:
            logger.warning("http_error", status=exc.status_code, detail=exc.detail)
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": body.model_dump(exclude_none=True)},
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        logger.exception("unhandled_error", error=str(exc))
        # Sentry가 활성화되어 있으면 자동 캡처됨
        body = ErrorBody(
            code="INTERNAL_ERROR",
            message="An unexpected error occurred",
            correlation_id=get_correlation_id() or None,
        )
        return JSONResponse(
            status_code=500,
            content={"error": body.model_dump(exclude_none=True)},
        )

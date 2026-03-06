"""통일 에러 응답 스키마."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ErrorDetail(BaseModel):
    """개별 검증 에러 상세."""

    model_config = ConfigDict(from_attributes=True)

    field: str
    message: str
    type: str  # e.g., "value_error", "missing"


class ErrorBody(BaseModel):
    """에러 응답 바디."""

    model_config = ConfigDict(from_attributes=True)

    code: str            # e.g., "VALIDATION_ERROR", "NOT_FOUND", "INTERNAL_ERROR"
    message: str         # 사람이 읽을 수 있는 메시지
    details: list[ErrorDetail] | None = None  # 검증 에러 시 상세 목록
    correlation_id: str | None = None          # 요청 추적 ID


class ErrorResponse(BaseModel):
    """통일 에러 응답 포맷."""

    model_config = ConfigDict(from_attributes=True)

    error: ErrorBody

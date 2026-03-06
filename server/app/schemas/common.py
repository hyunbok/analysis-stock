"""표준 API 응답 래퍼 스키마."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    """표준 API 성공 응답 포맷."""

    data: T
    error: None = None
    meta: dict = Field(
        default_factory=lambda: {"timestamp": datetime.now(timezone.utc).isoformat()}
    )

"""거래소 계정 관리 API Pydantic 스키마 — 요청/응답 모델 정의."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.providers.enums import ExchangeType

# ── 헬퍼 ──────────────────────────────────────────────────────────────────────


def mask_api_key(key: str) -> str:
    """API 키를 ****{suffix} 형식으로 마스킹.

    마지막 6자를 노출하고 앞부분을 ****로 대체한다.
    키 길이가 6자 이하이면 전체를 ****로 대체한다.

    Examples:
        >>> mask_api_key("abcdef123456")
        '****123456'
        >>> mask_api_key("short")
        '****'
    """
    if len(key) <= 6:
        return "****"
    return f"****{key[-6:]}"


# ── 요청 스키마 ───────────────────────────────────────────────────────────────


class RegisterExchangeRequest(BaseModel):
    """거래소 API 키 등록 요청."""

    exchange_type: ExchangeType
    api_key: str = Field(min_length=1, max_length=500)
    api_secret: str = Field(min_length=1, max_length=500)
    nickname: str | None = Field(default=None, min_length=1, max_length=50)


class UpdateExchangeRequest(BaseModel):
    """거래소 API 키 수정 요청 — 모든 필드 선택적."""

    api_key: str | None = Field(default=None, min_length=1, max_length=500)
    api_secret: str | None = Field(default=None, min_length=1, max_length=500)
    nickname: str | None = Field(default=None, min_length=1, max_length=50)

    @field_validator("api_key", "api_secret", mode="before")
    @classmethod
    def _reject_empty_string(cls, v: str | None) -> str | None:
        """빈 문자열을 None으로 처리하지 않고 유효성 오류 반환."""
        if v is not None and v.strip() == "":
            raise ValueError("빈 문자열은 허용되지 않습니다.")
        return v


# ── 응답 스키마 ───────────────────────────────────────────────────────────────


class ExchangeAccountResponse(BaseModel):
    """거래소 계정 응답 — API 키는 마스킹 처리."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    exchange_type: str
    nickname: str | None
    api_key_masked: str  # mask_api_key() 적용 결과
    permissions: list[str] | None
    is_active: bool
    is_verified: bool
    warning_level: str  # 'none' | 'warning' | 'critical'
    verified_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ExchangeVerifyResponse(BaseModel):
    """API 키 검증 결과 응답."""

    is_valid: bool
    permissions: list[str]
    has_withdraw_permission: bool
    warning_level: str  # 'none' | 'warning' | 'critical'
    message: str | None = None

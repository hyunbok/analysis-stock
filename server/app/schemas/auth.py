"""인증 관련 Pydantic 스키마 — 요청/응답 모델 정의."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


# ── 요청 스키마 ───────────────────────────────────────────────────────────────


class RegisterRequest(BaseModel):
    """회원가입 요청."""

    email: EmailStr
    password: str = Field(min_length=8, max_length=100)
    nickname: str = Field(min_length=2, max_length=50)


class VerifyEmailRequest(BaseModel):
    """이메일 인증 코드 확인 요청."""

    email: EmailStr
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


class LoginRequest(BaseModel):
    """로그인 요청."""

    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    """토큰 갱신 요청."""

    refresh_token: str


class LogoutRequest(BaseModel):
    """로그아웃 요청."""

    refresh_token: str


class UpdateProfileRequest(BaseModel):
    """프로필 수정 요청 — 모든 필드 선택적."""

    nickname: str | None = Field(default=None, min_length=2, max_length=50)
    language: str | None = Field(default=None, pattern=r"^(ko|en)$")
    theme: str | None = Field(default=None, pattern=r"^(light|dark|system)$")
    price_color_style: str | None = Field(default=None, pattern=r"^(korean|western)$")


class DeleteAccountRequest(BaseModel):
    """계정 삭제 요청."""

    refresh_token: str


# ── 응답 스키마 ───────────────────────────────────────────────────────────────


class TokenPair(BaseModel):
    """Access + Refresh 토큰 쌍."""

    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_in: int  # access token 만료까지 초


class UserResponse(BaseModel):
    """사용자 정보 응답."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    nickname: str | None
    avatar_url: str | None
    language: str
    theme: str
    price_color_style: str
    ai_trading_enabled: bool
    is_2fa_enabled: bool
    email_verified: bool  # email_verified_at IS NOT NULL
    created_at: datetime

    @classmethod
    def from_user(cls, user: object) -> "UserResponse":
        """User ORM 모델에서 응답 스키마 생성."""
        return cls(
            id=user.id,  # type: ignore[attr-defined]
            email=user.email,  # type: ignore[attr-defined]
            nickname=user.nickname,  # type: ignore[attr-defined]
            avatar_url=user.avatar_url,  # type: ignore[attr-defined]
            language=user.language,  # type: ignore[attr-defined]
            theme=user.theme,  # type: ignore[attr-defined]
            price_color_style=user.price_color_style,  # type: ignore[attr-defined]
            ai_trading_enabled=user.ai_trading_enabled,  # type: ignore[attr-defined]
            is_2fa_enabled=user.is_2fa_enabled,  # type: ignore[attr-defined]
            email_verified=user.email_verified_at is not None,  # type: ignore[attr-defined]
            created_at=user.created_at,  # type: ignore[attr-defined]
        )


class RegisterResponse(BaseModel):
    """회원가입 응답."""

    message: str = "인증 코드가 이메일로 발송되었습니다."
    email: str


class VerifyEmailResponse(BaseModel):
    """이메일 인증 완료 응답."""

    message: str = "이메일 인증이 완료되었습니다."


class LoginResponse(BaseModel):
    """로그인 응답 — 2FA 상태에 따라 필드 분기.

    - 2FA 미활성: user + tokens 채움, requires_2fa=False
    - 2FA 활성: requires_2fa=True + temp_token 채움, user=None, tokens=None
    """

    user: UserResponse | None = None
    tokens: TokenPair | None = None
    requires_2fa: bool = False
    temp_token: str | None = None
    temp_token_expires_in: int | None = None  # 300 (5분)


class RefreshResponse(BaseModel):
    """토큰 갱신 응답."""

    tokens: TokenPair


class LogoutResponse(BaseModel):
    """로그아웃 응답."""

    message: str = "로그아웃되었습니다."


class ProfileResponse(BaseModel):
    """프로필 조회/수정 응답."""

    user: UserResponse


class AccountDeleteResponse(BaseModel):
    """계정 삭제 예약 응답."""

    message: str = "계정 삭제가 예약되었습니다. 30일 후 영구 삭제됩니다."
    scheduled_delete_at: datetime

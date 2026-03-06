"""2FA (TOTP) 관련 Pydantic 스키마."""
from __future__ import annotations

from pydantic import BaseModel, Field


# ── 요청 스키마 ───────────────────────────────────────────────────────────────


class TwoFactorVerifyRequest(BaseModel):
    """2FA 활성화 요청 — TOTP 코드 검증."""

    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


class TwoFactorDisableRequest(BaseModel):
    """2FA 비활성화 요청 — TOTP 6자리 또는 백업 코드 10자리."""

    code: str = Field(min_length=6, max_length=10)


class TwoFactorLoginVerifyRequest(BaseModel):
    """2FA 로그인 2단계 검증 — 임시 토큰 + TOTP or 백업 코드."""

    temp_token: str
    code: str = Field(min_length=6, max_length=10)


# ── 응답 스키마 ───────────────────────────────────────────────────────────────


class TwoFactorSetupResponse(BaseModel):
    """2FA 설정 시작 응답."""

    secret: str           # Base32 encoded (앱 수동 입력용)
    qr_code_uri: str      # otpauth://totp/CoinTrader:{email}?secret=...
    qr_code_base64: str   # PNG QR 이미지 Base64 (Flutter Image.memory용)
    expires_in: int = 600  # setup 세션 만료 초 (10분)


class TwoFactorActivateResponse(BaseModel):
    """2FA 활성화 완료 응답."""

    message: str = "2FA가 활성화되었습니다."
    backup_codes: list[str]  # 평문 10자리 코드 10개 (1회성 — 이후 재조회 불가)


class TwoFactorDisableResponse(BaseModel):
    """2FA 비활성화 완료 응답."""

    message: str = "2FA가 비활성화되었습니다."


class TwoFactorStatusResponse(BaseModel):
    """2FA 상태 조회 응답."""

    is_enabled: bool
    has_backup_codes: bool  # 잔여 미사용 백업 코드 존재 여부

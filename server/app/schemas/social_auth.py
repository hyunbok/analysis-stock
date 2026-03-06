"""소셜 로그인 관련 Pydantic 스키마."""
from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, Field

from app.schemas.auth import TokenPair, UserResponse


# ── 요청 스키마 ───────────────────────────────────────────────────────────────


class AppleUserName(BaseModel):
    """Apple 최초 로그인 시 전달되는 이름 정보.

    Apple 클라이언트 SDK는 snake_case로 전달하지 않으므로
    model_config alias 설정으로 camelCase 요청도 허용.
    """

    model_config = {"populate_by_name": True}

    first_name: str | None = Field(default=None, alias="firstName", max_length=50)
    last_name: str | None = Field(default=None, alias="lastName", max_length=50)


class AppleUserData(BaseModel):
    """Apple 최초 로그인 시 클라이언트가 함께 전달하는 사용자 데이터.

    Apple은 최초 로그인 시에만 이 데이터를 클라이언트에 전달하므로
    서버는 즉시 저장해야 함. 이후 로그인에서는 null.
    """

    name: AppleUserName | None = None


class GoogleSocialLoginRequest(BaseModel):
    """Google 소셜 로그인 요청."""

    id_token: str = Field(min_length=1, description="Google OAuth2 id_token (JWT)")


class AppleSocialLoginRequest(BaseModel):
    """Apple 소셜 로그인 요청."""

    id_token: str = Field(min_length=1, description="Apple Sign In id_token (JWT)")
    user: AppleUserData | None = Field(
        default=None,
        description="최초 로그인 시에만 Apple이 클라이언트에 전달하는 사용자 정보",
    )


# ── 응답 스키마 ───────────────────────────────────────────────────────────────


class SocialLoginResponse(BaseModel):
    """소셜 로그인 응답.

    LoginResponse와 동일 구조에 is_new_user 플래그 추가.
    클라이언트는 is_new_user=true 시 닉네임 설정 온보딩 화면으로 안내.
    """

    user: UserResponse
    tokens: TokenPair
    is_new_user: bool = Field(
        description="True: 소셜 계정으로 최초 가입, False: 기존 계정 로그인 또는 병합"
    )


# ── 내부 DTO ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class OAuthUserInfo:
    """OAuth 공급자 JWT 검증 후 추출된 표준화된 사용자 정보.

    서비스 레이어는 provider 종류와 무관하게 이 DTO만 다룬다.
    """

    provider: str            # "google" | "apple"
    provider_id: str         # JWT sub claim (공급자 내 고유 ID)
    email: str | None        # 이메일 (Apple private relay 가능, 없을 수도 있음)
    display_name: str | None  # 표시 이름 (없으면 None)
    avatar_url: str | None   # 프로필 이미지 URL (Google만 picture 클레임 제공)

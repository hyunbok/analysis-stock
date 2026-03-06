"""소셜 로그인 API 통합 테스트 — Google/Apple OAuth2 엔드포인트."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.exceptions import AuthErrors
from app.middleware.correlation_id import CorrelationIdMiddleware
from app.middleware.error_handler import register_error_handlers
from app.models.user import User
from app.schemas.auth import TokenPair
from app.schemas.social_auth import OAuthUserInfo


# ── 헬퍼 ─────────────────────────────────────────────────────────────────────


def _make_user(
    email: str = "user@gmail.com",
    nickname: str = "GoogleUser",
) -> User:
    user = MagicMock(spec=User)
    user.id = uuid.uuid4()
    user.email = email
    user.nickname = nickname
    user.avatar_url = "https://lh3.googleusercontent.com/photo.jpg"
    user.language = "ko"
    user.theme = "system"
    user.price_color_style = "korean"
    user.ai_trading_enabled = False
    user.is_2fa_enabled = False
    user.email_verified_at = datetime.now(timezone.utc)
    user.soft_deleted_at = None
    user.created_at = datetime.now(timezone.utc)
    return user


def _make_token_pair() -> TokenPair:
    return TokenPair(
        access_token="access.token.here",
        refresh_token="refresh.token.here",
        expires_in=1800,
    )


def _make_oauth_info(provider: str = "google") -> OAuthUserInfo:
    return OAuthUserInfo(
        provider=provider,
        provider_id="google-sub-123456",
        email="user@gmail.com",
        display_name="Google User",
        avatar_url="https://lh3.googleusercontent.com/photo.jpg",
    )


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_oauth_svc() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def mock_social_auth_svc() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def test_app(mock_oauth_svc: AsyncMock, mock_social_auth_svc: AsyncMock) -> FastAPI:
    """소셜 로그인 테스트용 FastAPI 앱."""
    from app.api.v1.social_auth import router as social_auth_router
    from app.core.deps import get_oauth_verification_service, get_social_auth_service

    app = FastAPI()
    register_error_handlers(app)
    app.add_middleware(CorrelationIdMiddleware)

    app.include_router(social_auth_router, prefix="/auth/social")

    app.dependency_overrides[get_oauth_verification_service] = lambda: mock_oauth_svc
    app.dependency_overrides[get_social_auth_service] = lambda: mock_social_auth_svc
    return app


@pytest.fixture
async def client(test_app: FastAPI) -> AsyncClient:
    async with AsyncClient(
        transport=ASGITransport(app=test_app), base_url="http://test"
    ) as c:
        yield c


# ── POST /auth/social/google ──────────────────────────────────────────────────


@pytest.mark.anyio
async def test_google_login_existing_user(
    client: AsyncClient,
    mock_oauth_svc: AsyncMock,
    mock_social_auth_svc: AsyncMock,
):
    """기존 소셜 사용자 → 200, is_new_user=false."""
    user = _make_user()
    tokens = _make_token_pair()
    oauth_info = _make_oauth_info("google")

    mock_oauth_svc.verify_google_token.return_value = oauth_info
    mock_social_auth_svc.social_login.return_value = (user, tokens, False)

    resp = await client.post(
        "/auth/social/google",
        json={"id_token": "valid.google.id.token"},
    )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["is_new_user"] is False
    assert "user" in data
    assert "tokens" in data
    assert data["tokens"]["token_type"] == "Bearer"
    assert data["tokens"]["expires_in"] == 1800


@pytest.mark.anyio
async def test_google_login_new_user(
    client: AsyncClient,
    mock_oauth_svc: AsyncMock,
    mock_social_auth_svc: AsyncMock,
):
    """신규 사용자 가입 → 200, is_new_user=true."""
    user = _make_user()
    tokens = _make_token_pair()
    oauth_info = _make_oauth_info("google")

    mock_oauth_svc.verify_google_token.return_value = oauth_info
    mock_social_auth_svc.social_login.return_value = (user, tokens, True)

    resp = await client.post(
        "/auth/social/google",
        json={"id_token": "valid.google.id.token"},
    )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["is_new_user"] is True
    assert data["user"]["email"] == "user@gmail.com"


@pytest.mark.anyio
async def test_google_login_invalid_token(
    client: AsyncClient,
    mock_oauth_svc: AsyncMock,
    mock_social_auth_svc: AsyncMock,
):
    """유효하지 않은 id_token → 401 INVALID_OAUTH_TOKEN."""
    mock_oauth_svc.verify_google_token.side_effect = AuthErrors.invalid_oauth_token()

    resp = await client.post(
        "/auth/social/google",
        json={"id_token": "expired.or.invalid.token"},
    )

    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "INVALID_OAUTH_TOKEN"


@pytest.mark.anyio
async def test_google_login_email_required(
    client: AsyncClient,
    mock_oauth_svc: AsyncMock,
    mock_social_auth_svc: AsyncMock,
):
    """Google 이메일 미제공 → 422 OAUTH_EMAIL_REQUIRED."""
    mock_oauth_svc.verify_google_token.side_effect = AuthErrors.oauth_email_required()

    resp = await client.post(
        "/auth/social/google",
        json={"id_token": "no.email.token"},
    )

    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "OAUTH_EMAIL_REQUIRED"


@pytest.mark.anyio
async def test_google_login_provider_unavailable(
    client: AsyncClient,
    mock_oauth_svc: AsyncMock,
    mock_social_auth_svc: AsyncMock,
):
    """JWKS 서버 응답 실패 → 502 OAUTH_PROVIDER_UNAVAILABLE."""
    mock_oauth_svc.verify_google_token.side_effect = AuthErrors.oauth_provider_unavailable()

    resp = await client.post(
        "/auth/social/google",
        json={"id_token": "any.token"},
    )

    assert resp.status_code == 502
    assert resp.json()["error"]["code"] == "OAUTH_PROVIDER_UNAVAILABLE"


@pytest.mark.anyio
async def test_google_login_account_deleted(
    client: AsyncClient,
    mock_oauth_svc: AsyncMock,
    mock_social_auth_svc: AsyncMock,
):
    """삭제 예약된 계정과 이메일 일치 → 410 ACCOUNT_DELETED."""
    oauth_info = _make_oauth_info("google")
    mock_oauth_svc.verify_google_token.return_value = oauth_info
    mock_social_auth_svc.social_login.side_effect = AuthErrors.account_deleted()

    resp = await client.post(
        "/auth/social/google",
        json={"id_token": "valid.token"},
    )

    assert resp.status_code == 410
    assert resp.json()["error"]["code"] == "ACCOUNT_DELETED"


@pytest.mark.anyio
async def test_google_login_missing_id_token(
    client: AsyncClient,
    mock_oauth_svc: AsyncMock,
    mock_social_auth_svc: AsyncMock,
):
    """id_token 누락 → 422."""
    resp = await client.post(
        "/auth/social/google",
        json={},
    )

    assert resp.status_code == 422


@pytest.mark.anyio
async def test_google_login_empty_id_token(
    client: AsyncClient,
    mock_oauth_svc: AsyncMock,
    mock_social_auth_svc: AsyncMock,
):
    """id_token 빈 문자열 → 422 (min_length=1 검증)."""
    resp = await client.post(
        "/auth/social/google",
        json={"id_token": ""},
    )

    assert resp.status_code == 422


# ── POST /auth/social/apple ───────────────────────────────────────────────────


@pytest.mark.anyio
async def test_apple_login_existing_user(
    client: AsyncClient,
    mock_oauth_svc: AsyncMock,
    mock_social_auth_svc: AsyncMock,
):
    """기존 Apple 사용자 → 200, is_new_user=false."""
    user = _make_user(email="user@privaterelay.appleid.com", nickname="AppleUser")
    tokens = _make_token_pair()
    oauth_info = OAuthUserInfo(
        provider="apple",
        provider_id="apple-sub-654321",
        email="user@privaterelay.appleid.com",
        display_name=None,
        avatar_url=None,
    )

    mock_oauth_svc.verify_apple_token.return_value = oauth_info
    mock_social_auth_svc.social_login.return_value = (user, tokens, False)

    resp = await client.post(
        "/auth/social/apple",
        json={"id_token": "valid.apple.id.token"},
    )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["is_new_user"] is False


@pytest.mark.anyio
async def test_apple_login_new_user_with_name(
    client: AsyncClient,
    mock_oauth_svc: AsyncMock,
    mock_social_auth_svc: AsyncMock,
):
    """Apple 최초 로그인 + 이름 정보 포함 → 200, is_new_user=true."""
    user = _make_user(email="user@privaterelay.appleid.com", nickname="홍길동")
    tokens = _make_token_pair()
    oauth_info = OAuthUserInfo(
        provider="apple",
        provider_id="apple-sub-654321",
        email="user@privaterelay.appleid.com",
        display_name=None,
        avatar_url=None,
    )

    mock_oauth_svc.verify_apple_token.return_value = oauth_info
    mock_social_auth_svc.social_login.return_value = (user, tokens, True)

    resp = await client.post(
        "/auth/social/apple",
        json={
            "id_token": "valid.apple.id.token",
            "user": {
                "name": {
                    "firstName": "길동",
                    "lastName": "홍",
                }
            },
        },
    )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["is_new_user"] is True
    # social_auth_svc.social_login에 apple_user 전달 여부 검증
    call_kwargs = mock_social_auth_svc.social_login.call_args
    apple_user_arg = call_kwargs.kwargs.get("apple_user") or (
        call_kwargs.args[1] if len(call_kwargs.args) > 1 else None
    )
    assert apple_user_arg is not None
    assert apple_user_arg.name is not None


@pytest.mark.anyio
async def test_apple_login_without_user_data(
    client: AsyncClient,
    mock_oauth_svc: AsyncMock,
    mock_social_auth_svc: AsyncMock,
):
    """Apple 재로그인 (user 필드 null) → 200 정상 처리."""
    user = _make_user(email="user@privaterelay.appleid.com", nickname="AppleUser")
    tokens = _make_token_pair()
    oauth_info = OAuthUserInfo(
        provider="apple",
        provider_id="apple-sub-654321",
        email="user@privaterelay.appleid.com",
        display_name=None,
        avatar_url=None,
    )

    mock_oauth_svc.verify_apple_token.return_value = oauth_info
    mock_social_auth_svc.social_login.return_value = (user, tokens, False)

    resp = await client.post(
        "/auth/social/apple",
        json={"id_token": "valid.apple.id.token", "user": None},
    )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["is_new_user"] is False


@pytest.mark.anyio
async def test_apple_login_invalid_token(
    client: AsyncClient,
    mock_oauth_svc: AsyncMock,
    mock_social_auth_svc: AsyncMock,
):
    """유효하지 않은 Apple id_token → 401."""
    mock_oauth_svc.verify_apple_token.side_effect = AuthErrors.invalid_oauth_token()

    resp = await client.post(
        "/auth/social/apple",
        json={"id_token": "invalid.apple.token"},
    )

    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "INVALID_OAUTH_TOKEN"


@pytest.mark.anyio
async def test_apple_login_provider_unavailable(
    client: AsyncClient,
    mock_oauth_svc: AsyncMock,
    mock_social_auth_svc: AsyncMock,
):
    """Apple JWKS 서버 실패 → 502."""
    mock_oauth_svc.verify_apple_token.side_effect = AuthErrors.oauth_provider_unavailable()

    resp = await client.post(
        "/auth/social/apple",
        json={"id_token": "any.token"},
    )

    assert resp.status_code == 502
    assert resp.json()["error"]["code"] == "OAUTH_PROVIDER_UNAVAILABLE"


@pytest.mark.anyio
async def test_apple_login_account_deleted(
    client: AsyncClient,
    mock_oauth_svc: AsyncMock,
    mock_social_auth_svc: AsyncMock,
):
    """Apple - 삭제 예약된 계정과 이메일 일치 → 410 ACCOUNT_DELETED."""
    oauth_info = OAuthUserInfo(
        provider="apple",
        provider_id="apple-sub-654321",
        email="deleted@privaterelay.appleid.com",
        display_name=None,
        avatar_url=None,
    )
    mock_oauth_svc.verify_apple_token.return_value = oauth_info
    mock_social_auth_svc.social_login.side_effect = AuthErrors.account_deleted()

    resp = await client.post(
        "/auth/social/apple",
        json={"id_token": "valid.token"},
    )

    assert resp.status_code == 410
    assert resp.json()["error"]["code"] == "ACCOUNT_DELETED"


# ── Rate Limiting ─────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_google_login_rate_limited(
    client: AsyncClient,
    mock_oauth_svc: AsyncMock,
    mock_social_auth_svc: AsyncMock,
):
    """소셜 로그인 Rate Limit 초과 → 429."""
    from app.core.exceptions import AppError

    mock_oauth_svc.verify_google_token.side_effect = AppError(
        "RATE_LIMIT_EXCEEDED", "요청 횟수를 초과했습니다.", 429
    )

    resp = await client.post(
        "/auth/social/google",
        json={"id_token": "any.token"},
    )

    assert resp.status_code == 429


# ── 응답 포맷 공통 검증 ───────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_social_login_response_format(
    client: AsyncClient,
    mock_oauth_svc: AsyncMock,
    mock_social_auth_svc: AsyncMock,
):
    """응답 포맷: data, error=null, meta.timestamp 검증."""
    user = _make_user()
    tokens = _make_token_pair()
    oauth_info = _make_oauth_info("google")

    mock_oauth_svc.verify_google_token.return_value = oauth_info
    mock_social_auth_svc.social_login.return_value = (user, tokens, False)

    resp = await client.post(
        "/auth/social/google",
        json={"id_token": "valid.token"},
    )

    body = resp.json()
    assert body["error"] is None
    assert "meta" in body
    assert "timestamp" in body["meta"]
    data = body["data"]
    assert "user" in data
    assert "tokens" in data
    assert "is_new_user" in data


@pytest.mark.anyio
async def test_social_login_user_response_fields(
    client: AsyncClient,
    mock_oauth_svc: AsyncMock,
    mock_social_auth_svc: AsyncMock,
):
    """UserResponse 필드 전체 검증."""
    user = _make_user(email="test@gmail.com", nickname="테스터")
    tokens = _make_token_pair()
    oauth_info = _make_oauth_info("google")

    mock_oauth_svc.verify_google_token.return_value = oauth_info
    mock_social_auth_svc.social_login.return_value = (user, tokens, False)

    resp = await client.post(
        "/auth/social/google",
        json={"id_token": "valid.token"},
    )

    user_data = resp.json()["data"]["user"]
    required_fields = [
        "id", "email", "nickname", "avatar_url", "language", "theme",
        "price_color_style", "ai_trading_enabled", "is_2fa_enabled",
        "email_verified", "created_at",
    ]
    for field in required_fields:
        assert field in user_data, f"필드 누락: {field}"

    assert user_data["email"] == "test@gmail.com"
    assert user_data["email_verified"] is True

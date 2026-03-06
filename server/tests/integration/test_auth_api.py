"""인증 API 통합 테스트 — register, verify-email, login, refresh, logout, /users/me."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.exceptions import AppError, AuthErrors
from app.middleware.correlation_id import CorrelationIdMiddleware
from app.middleware.error_handler import register_error_handlers
from app.models.user import User
from app.schemas.auth import TokenPair


# ── 헬퍼 ─────────────────────────────────────────────────────────────────────


def _make_user(
    email: str = "test@example.com",
    nickname: str = "테스터",
    email_verified: bool = True,
    soft_deleted: bool = False,
    is_2fa_enabled: bool = False,
) -> User:
    user = MagicMock(spec=User)
    user.id = uuid.uuid4()
    user.email = email
    user.nickname = nickname
    user.avatar_url = None
    user.language = "ko"
    user.theme = "system"
    user.price_color_style = "korean"
    user.ai_trading_enabled = False
    user.is_2fa_enabled = is_2fa_enabled
    user.totp_secret_encrypted = None
    user.email_verified_at = datetime.now(timezone.utc) if email_verified else None
    user.soft_deleted_at = datetime.now(timezone.utc) if soft_deleted else None
    user.created_at = datetime.now(timezone.utc)
    return user


def _make_token_pair() -> TokenPair:
    return TokenPair(
        access_token="access.token.here",
        refresh_token="refresh.token.here",
        expires_in=1800,
    )


def _make_client() -> MagicMock:
    client = MagicMock()
    client.id = uuid.uuid4()
    return client


# ── Fixture: 테스트 앱 ────────────────────────────────────────────────────────


@pytest.fixture
def mock_auth_service() -> AsyncMock:
    svc = AsyncMock()
    svc._cache = AsyncMock()  # 2FA pending 저장/조회용
    return svc


@pytest.fixture
def mock_session_service() -> AsyncMock:
    svc = AsyncMock()
    svc.create_or_update_session.return_value = (_make_client(), False)
    return svc


@pytest.fixture
def mock_audit_service() -> AsyncMock:
    svc = AsyncMock()
    svc.log.return_value = None
    return svc


@pytest.fixture
def test_app(
    mock_auth_service: AsyncMock,
    mock_session_service: AsyncMock,
    mock_audit_service: AsyncMock,
) -> FastAPI:
    """에러 핸들러 포함 테스트 FastAPI 앱."""
    from app.api.v1.auth import router as auth_router
    from app.api.v1.users import router as users_router
    from app.core.deps import get_audit_service, get_auth_service, get_session_service

    app = FastAPI()
    register_error_handlers(app)
    app.add_middleware(CorrelationIdMiddleware)

    app.include_router(auth_router, prefix="/auth")
    app.include_router(users_router, prefix="/users")

    app.dependency_overrides[get_auth_service] = lambda: mock_auth_service
    app.dependency_overrides[get_session_service] = lambda: mock_session_service
    app.dependency_overrides[get_audit_service] = lambda: mock_audit_service
    return app


@pytest.fixture
def test_app_authed(
    mock_auth_service: AsyncMock,
    mock_session_service: AsyncMock,
    mock_audit_service: AsyncMock,
) -> FastAPI:
    """인증된 사용자가 필요한 엔드포인트 테스트용 앱."""
    from app.api.v1.auth import router as auth_router
    from app.api.v1.users import router as users_router
    from app.core.deps import get_audit_service, get_auth_service, get_current_user, get_session_service

    mock_user = _make_user()

    app = FastAPI()
    register_error_handlers(app)
    app.add_middleware(CorrelationIdMiddleware)

    app.include_router(auth_router, prefix="/auth")
    app.include_router(users_router, prefix="/users")

    app.dependency_overrides[get_auth_service] = lambda: mock_auth_service
    app.dependency_overrides[get_session_service] = lambda: mock_session_service
    app.dependency_overrides[get_audit_service] = lambda: mock_audit_service
    app.dependency_overrides[get_current_user] = lambda: mock_user
    return app


@pytest.fixture
async def client(test_app: FastAPI) -> AsyncClient:
    async with AsyncClient(
        transport=ASGITransport(app=test_app), base_url="http://test"
    ) as c:
        yield c


@pytest.fixture
async def auth_client(test_app_authed: FastAPI) -> AsyncClient:
    async with AsyncClient(
        transport=ASGITransport(app=test_app_authed), base_url="http://test"
    ) as c:
        yield c


# ── POST /auth/register ───────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_register_success(client: AsyncClient, mock_auth_service: AsyncMock):
    mock_auth_service.register.return_value = None

    resp = await client.post(
        "/auth/register",
        json={"email": "new@example.com", "password": "Str0ng!Pw", "nickname": "뉴유저"},
    )

    assert resp.status_code == 201
    body = resp.json()
    assert body["data"]["email"] == "new@example.com"
    assert "인증 코드" in body["data"]["message"]
    assert body["error"] is None


@pytest.mark.anyio
async def test_register_duplicate_email(client: AsyncClient, mock_auth_service: AsyncMock):
    mock_auth_service.register.side_effect = AuthErrors.email_already_exists()

    resp = await client.post(
        "/auth/register",
        json={"email": "dup@example.com", "password": "Str0ng!Pw", "nickname": "뉴유저"},
    )

    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "EMAIL_ALREADY_EXISTS"


@pytest.mark.anyio
async def test_register_duplicate_nickname(client: AsyncClient, mock_auth_service: AsyncMock):
    mock_auth_service.register.side_effect = AuthErrors.nickname_taken()

    resp = await client.post(
        "/auth/register",
        json={"email": "new@example.com", "password": "Str0ng!Pw", "nickname": "중복닉"},
    )

    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "NICKNAME_TAKEN"


@pytest.mark.anyio
async def test_register_short_password(client: AsyncClient, mock_auth_service: AsyncMock):
    """비밀번호 최소 길이 미만 → 422."""
    resp = await client.post(
        "/auth/register",
        json={"email": "new@example.com", "password": "short", "nickname": "닉"},
    )

    assert resp.status_code == 422


@pytest.mark.anyio
async def test_register_email_send_failed(client: AsyncClient, mock_auth_service: AsyncMock):
    mock_auth_service.register.side_effect = AuthErrors.email_send_failed()

    resp = await client.post(
        "/auth/register",
        json={"email": "new@example.com", "password": "Str0ng!Pw", "nickname": "뉴유저"},
    )

    assert resp.status_code == 502
    assert resp.json()["error"]["code"] == "EMAIL_SEND_FAILED"


# ── POST /auth/verify-email ───────────────────────────────────────────────────


@pytest.mark.anyio
async def test_verify_email_success(client: AsyncClient, mock_auth_service: AsyncMock):
    mock_auth_service.verify_email.return_value = None

    resp = await client.post(
        "/auth/verify-email",
        json={"email": "test@example.com", "code": "123456"},
    )

    assert resp.status_code == 200
    assert "인증이 완료" in resp.json()["data"]["message"]


@pytest.mark.anyio
async def test_verify_email_invalid_code(client: AsyncClient, mock_auth_service: AsyncMock):
    mock_auth_service.verify_email.side_effect = AuthErrors.invalid_verify_code()

    resp = await client.post(
        "/auth/verify-email",
        json={"email": "test@example.com", "code": "000000"},
    )

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "INVALID_VERIFY_CODE"


@pytest.mark.anyio
async def test_verify_email_already_verified(client: AsyncClient, mock_auth_service: AsyncMock):
    mock_auth_service.verify_email.side_effect = AuthErrors.email_already_verified()

    resp = await client.post(
        "/auth/verify-email",
        json={"email": "test@example.com", "code": "123456"},
    )

    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "EMAIL_ALREADY_VERIFIED"


@pytest.mark.anyio
async def test_verify_email_user_not_found(client: AsyncClient, mock_auth_service: AsyncMock):
    mock_auth_service.verify_email.side_effect = AuthErrors.user_not_found()

    resp = await client.post(
        "/auth/verify-email",
        json={"email": "ghost@example.com", "code": "123456"},
    )

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "USER_NOT_FOUND"


@pytest.mark.anyio
async def test_verify_email_invalid_code_format(client: AsyncClient, mock_auth_service: AsyncMock):
    """코드 형식 오류 (숫자가 아닌 경우) → 422."""
    resp = await client.post(
        "/auth/verify-email",
        json={"email": "test@example.com", "code": "ABCDEF"},
    )

    assert resp.status_code == 422


# ── POST /auth/login ──────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_login_success(
    client: AsyncClient,
    mock_auth_service: AsyncMock,
    mock_session_service: AsyncMock,
):
    """2FA 비활성 사용자 → 정상 토큰 발급."""
    user = _make_user(is_2fa_enabled=False)
    tokens = _make_token_pair()
    mock_auth_service.verify_credentials.return_value = user
    mock_auth_service.issue_tokens_with_store.return_value = tokens

    resp = await client.post(
        "/auth/login",
        json={"email": "test@example.com", "password": "Str0ng!Pw"},
    )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "user" in data
    assert "tokens" in data
    assert data["tokens"]["token_type"] == "Bearer"
    assert data["tokens"]["expires_in"] == 1800
    assert data["requires_2fa"] is False


@pytest.mark.anyio
async def test_login_invalid_credentials(client: AsyncClient, mock_auth_service: AsyncMock):
    mock_auth_service.verify_credentials.side_effect = AuthErrors.invalid_credentials()

    resp = await client.post(
        "/auth/login",
        json={"email": "test@example.com", "password": "WrongPass1"},
    )

    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "INVALID_CREDENTIALS"


@pytest.mark.anyio
async def test_login_email_not_verified(client: AsyncClient, mock_auth_service: AsyncMock):
    mock_auth_service.verify_credentials.side_effect = AuthErrors.email_not_verified()

    resp = await client.post(
        "/auth/login",
        json={"email": "test@example.com", "password": "Str0ng!Pw"},
    )

    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "EMAIL_NOT_VERIFIED"


@pytest.mark.anyio
async def test_login_account_deleted(client: AsyncClient, mock_auth_service: AsyncMock):
    mock_auth_service.verify_credentials.side_effect = AuthErrors.account_deleted()

    resp = await client.post(
        "/auth/login",
        json={"email": "deleted@example.com", "password": "Str0ng!Pw"},
    )

    assert resp.status_code == 410
    assert resp.json()["error"]["code"] == "ACCOUNT_DELETED"


@pytest.mark.anyio
async def test_login_rate_limit(client: AsyncClient, mock_auth_service: AsyncMock):
    """로그인 시도 횟수 초과 → 429 LOGIN_RATE_LIMIT."""
    mock_auth_service.verify_credentials.side_effect = AuthErrors.login_rate_limit()

    resp = await client.post(
        "/auth/login",
        json={"email": "test@example.com", "password": "Str0ng!Pw"},
    )

    assert resp.status_code == 429
    assert resp.json()["error"]["code"] == "LOGIN_RATE_LIMIT"


# ── POST /auth/refresh ────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_refresh_tokens_success(client: AsyncClient, mock_auth_service: AsyncMock):
    tokens = _make_token_pair()
    mock_auth_service.refresh_tokens.return_value = tokens

    resp = await client.post(
        "/auth/refresh",
        json={"refresh_token": "old.refresh.token"},
    )

    assert resp.status_code == 200
    assert "tokens" in resp.json()["data"]


@pytest.mark.anyio
async def test_refresh_tokens_invalid(client: AsyncClient, mock_auth_service: AsyncMock):
    mock_auth_service.refresh_tokens.side_effect = AuthErrors.invalid_refresh_token()

    resp = await client.post(
        "/auth/refresh",
        json={"refresh_token": "expired.or.revoked"},
    )

    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "INVALID_REFRESH_TOKEN"


# ── POST /auth/logout ─────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_logout_success(auth_client: AsyncClient, mock_auth_service: AsyncMock):
    mock_auth_service.logout.return_value = None

    resp = await auth_client.post(
        "/auth/logout",
        json={"refresh_token": "valid.refresh.token"},
        headers={"Authorization": "Bearer valid.access.token"},
    )

    assert resp.status_code == 200
    assert "로그아웃" in resp.json()["data"]["message"]


@pytest.mark.anyio
async def test_logout_no_token(client: AsyncClient):
    """Authorization 헤더 없이 logout → 401."""
    resp = await client.post(
        "/auth/logout",
        json={"refresh_token": "some.token"},
    )

    assert resp.status_code == 401


# ── GET /users/me ─────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_get_me_success(auth_client: AsyncClient):
    resp = await auth_client.get(
        "/users/me",
        headers={"Authorization": "Bearer valid.access.token"},
    )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "user" in data
    assert data["user"]["email"] == "test@example.com"
    assert data["user"]["email_verified"] is True


@pytest.mark.anyio
async def test_get_me_unauthorized(client: AsyncClient):
    """토큰 없이 /users/me → 401."""
    resp = await client.get("/users/me")

    assert resp.status_code == 401


# ── PUT /users/me ─────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_update_profile_success(
    auth_client: AsyncClient, mock_auth_service: AsyncMock
):
    updated_user = _make_user(nickname="새닉네임")
    mock_auth_service.update_profile.return_value = updated_user

    resp = await auth_client.put(
        "/users/me",
        json={"nickname": "새닉네임", "theme": "dark"},
        headers={"Authorization": "Bearer valid.access.token"},
    )

    assert resp.status_code == 200
    assert resp.json()["data"]["user"]["nickname"] == "새닉네임"


@pytest.mark.anyio
async def test_update_profile_nickname_taken(
    auth_client: AsyncClient, mock_auth_service: AsyncMock
):
    mock_auth_service.update_profile.side_effect = AuthErrors.nickname_taken()

    resp = await auth_client.put(
        "/users/me",
        json={"nickname": "중복닉"},
        headers={"Authorization": "Bearer valid.access.token"},
    )

    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "NICKNAME_TAKEN"


@pytest.mark.anyio
async def test_update_profile_invalid_theme(auth_client: AsyncClient):
    """허용되지 않는 theme 값 → 422."""
    resp = await auth_client.put(
        "/users/me",
        json={"theme": "invalid_theme"},
        headers={"Authorization": "Bearer valid.access.token"},
    )

    assert resp.status_code == 422


# ── DELETE /users/me ──────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_delete_account_success(
    auth_client: AsyncClient, mock_auth_service: AsyncMock
):
    future_date = datetime.now(timezone.utc).replace(microsecond=0)
    mock_auth_service.logout.return_value = None
    mock_auth_service.delete_account.return_value = future_date

    resp = await auth_client.request(
        "DELETE",
        "/users/me",
        json={"refresh_token": "valid.refresh.token"},
        headers={"Authorization": "Bearer valid.access.token"},
    )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "scheduled_delete_at" in data
    assert "30일" in data["message"]


@pytest.mark.anyio
async def test_delete_account_invalid_token(
    auth_client: AsyncClient, mock_auth_service: AsyncMock
):
    mock_auth_service.logout.side_effect = AuthErrors.invalid_refresh_token()

    resp = await auth_client.request(
        "DELETE",
        "/users/me",
        json={"refresh_token": "bad.refresh.token"},
        headers={"Authorization": "Bearer valid.access.token"},
    )

    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "INVALID_REFRESH_TOKEN"


# ── AppError 핸들러 검증 ──────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_app_error_response_format(client: AsyncClient, mock_auth_service: AsyncMock):
    """AppError → error 포맷 검증 (code, message 필드 존재)."""
    mock_auth_service.verify_credentials.side_effect = AppError("TEST_ERROR", "테스트 에러", 400)

    resp = await client.post(
        "/auth/login",
        json={"email": "test@example.com", "password": "Str0ng!Pw"},
    )

    assert resp.status_code == 400
    error = resp.json()["error"]
    assert error["code"] == "TEST_ERROR"
    assert error["message"] == "테스트 에러"


@pytest.mark.anyio
async def test_api_response_has_meta(client: AsyncClient, mock_auth_service: AsyncMock):
    """성공 응답에 meta.timestamp 포함 검증."""
    mock_auth_service.register.return_value = None

    resp = await client.post(
        "/auth/register",
        json={"email": "new@example.com", "password": "Str0ng!Pw", "nickname": "뉴유저"},
    )

    assert resp.status_code == 201
    body = resp.json()
    assert "meta" in body
    assert "timestamp" in body["meta"]

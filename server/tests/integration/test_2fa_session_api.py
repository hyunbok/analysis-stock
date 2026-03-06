"""2FA 및 세션 관리 API 통합 테스트 — ST10."""
from __future__ import annotations

import json
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
from app.schemas.two_factor import TwoFactorStatusResponse


# ── 헬퍼 ─────────────────────────────────────────────────────────────────────


def _make_user(
    email: str = "test@example.com",
    is_2fa_enabled: bool = False,
    totp_secret_encrypted: bytes | None = None,
) -> User:
    user = MagicMock(spec=User)
    user.id = uuid.uuid4()
    user.email = email
    user.nickname = "테스터"
    user.avatar_url = None
    user.language = "ko"
    user.theme = "system"
    user.price_color_style = "korean"
    user.ai_trading_enabled = False
    user.is_2fa_enabled = is_2fa_enabled
    user.totp_secret_encrypted = totp_secret_encrypted or (b"encrypted" if is_2fa_enabled else None)
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


def _make_client() -> MagicMock:
    client = MagicMock()
    client.id = uuid.uuid4()
    client.device_type = "ios"
    client.device_name = "iPhone 15 Pro"
    client.ip_address = "127.0.0.1"
    client.user_agent = "TestAgent/1.0"
    client.last_active_at = datetime.now(timezone.utc)
    client.created_at = datetime.now(timezone.utc)
    return client


BACKUP_CODES_10 = [f"ABCD{i:06d}" for i in range(10)]


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_auth_service() -> AsyncMock:
    svc = AsyncMock()
    # 엔드포인트는 auth_svc.store_2fa_login_pending / get_and_delete_2fa_login_pending 직접 호출
    # AsyncMock이 자동 생성하므로 기본값만 설정
    svc.store_2fa_login_pending.return_value = None
    svc.get_and_delete_2fa_login_pending.return_value = None
    return svc


@pytest.fixture
def mock_two_factor_service() -> AsyncMock:
    return AsyncMock()


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
def mock_user_2fa_disabled() -> User:
    return _make_user(is_2fa_enabled=False)


@pytest.fixture
def mock_user_2fa_enabled() -> User:
    return _make_user(is_2fa_enabled=True)


@pytest.fixture
def test_app(
    mock_auth_service: AsyncMock,
    mock_two_factor_service: AsyncMock,
    mock_session_service: AsyncMock,
    mock_audit_service: AsyncMock,
) -> FastAPI:
    """2FA + 세션 관리 테스트용 FastAPI 앱 (비인증 엔드포인트)."""
    from app.api.v1.auth import router as auth_router
    from app.core.deps import (
        get_audit_service,
        get_auth_service,
        get_session_service,
        get_two_factor_service,
    )

    app = FastAPI()
    register_error_handlers(app)
    app.add_middleware(CorrelationIdMiddleware)
    app.include_router(auth_router, prefix="/auth")

    app.dependency_overrides[get_auth_service] = lambda: mock_auth_service
    app.dependency_overrides[get_two_factor_service] = lambda: mock_two_factor_service
    app.dependency_overrides[get_session_service] = lambda: mock_session_service
    app.dependency_overrides[get_audit_service] = lambda: mock_audit_service
    return app


@pytest.fixture
def test_app_authed(
    mock_auth_service: AsyncMock,
    mock_two_factor_service: AsyncMock,
    mock_session_service: AsyncMock,
    mock_audit_service: AsyncMock,
    mock_user_2fa_disabled: User,
) -> FastAPI:
    """인증된 사용자(2FA 비활성) 기반 테스트 앱."""
    from app.api.v1.auth import router as auth_router
    from app.core.deps import (
        get_audit_service,
        get_auth_service,
        get_current_user,
        get_session_service,
        get_two_factor_service,
    )

    app = FastAPI()
    register_error_handlers(app)
    app.add_middleware(CorrelationIdMiddleware)
    app.include_router(auth_router, prefix="/auth")

    app.dependency_overrides[get_auth_service] = lambda: mock_auth_service
    app.dependency_overrides[get_two_factor_service] = lambda: mock_two_factor_service
    app.dependency_overrides[get_session_service] = lambda: mock_session_service
    app.dependency_overrides[get_audit_service] = lambda: mock_audit_service
    app.dependency_overrides[get_current_user] = lambda: mock_user_2fa_disabled
    return app


@pytest.fixture
def test_app_authed_2fa(
    mock_auth_service: AsyncMock,
    mock_two_factor_service: AsyncMock,
    mock_session_service: AsyncMock,
    mock_audit_service: AsyncMock,
    mock_user_2fa_enabled: User,
) -> FastAPI:
    """인증된 사용자(2FA 활성) 기반 테스트 앱."""
    from app.api.v1.auth import router as auth_router
    from app.core.deps import (
        get_audit_service,
        get_auth_service,
        get_current_user,
        get_session_service,
        get_two_factor_service,
    )

    app = FastAPI()
    register_error_handlers(app)
    app.add_middleware(CorrelationIdMiddleware)
    app.include_router(auth_router, prefix="/auth")

    app.dependency_overrides[get_auth_service] = lambda: mock_auth_service
    app.dependency_overrides[get_two_factor_service] = lambda: mock_two_factor_service
    app.dependency_overrides[get_session_service] = lambda: mock_session_service
    app.dependency_overrides[get_audit_service] = lambda: mock_audit_service
    app.dependency_overrides[get_current_user] = lambda: mock_user_2fa_enabled
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


@pytest.fixture
async def auth_client_2fa(test_app_authed_2fa: FastAPI) -> AsyncClient:
    """2FA 활성 사용자로 인증된 클라이언트."""
    async with AsyncClient(
        transport=ASGITransport(app=test_app_authed_2fa), base_url="http://test"
    ) as c:
        yield c


# ── POST /auth/2fa/setup ──────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_2fa_setup_success(
    auth_client: AsyncClient,
    mock_two_factor_service: AsyncMock,
):
    """2FA 미활성 사용자 → setup 성공: secret, qr_code_uri, qr_code_base64 반환."""
    from app.schemas.two_factor import TwoFactorSetupResponse

    mock_two_factor_service.generate_setup.return_value = TwoFactorSetupResponse(
        secret="JBSWY3DPEHPK3PXP",
        qr_code_uri="otpauth://totp/CoinTrader:test@example.com?secret=JBSWY3DPEHPK3PXP&issuer=CoinTrader",
        qr_code_base64="base64encodedpng==",
        expires_in=600,
    )

    resp = await auth_client.post(
        "/auth/2fa/setup",
        headers={"Authorization": "Bearer valid.access.token"},
    )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "secret" in data
    assert "qr_code_uri" in data
    assert "qr_code_base64" in data
    assert data["expires_in"] == 600


@pytest.mark.anyio
async def test_2fa_setup_already_enabled(
    auth_client_2fa: AsyncClient,
    mock_two_factor_service: AsyncMock,
):
    """이미 2FA 활성화된 사용자 → 409 TOTP_ALREADY_ENABLED."""
    mock_two_factor_service.generate_setup.side_effect = AuthErrors.totp_already_enabled()

    resp = await auth_client_2fa.post(
        "/auth/2fa/setup",
        headers={"Authorization": "Bearer valid.access.token"},
    )

    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "TOTP_ALREADY_ENABLED"


@pytest.mark.anyio
async def test_2fa_setup_unauthorized(client: AsyncClient):
    """인증 없이 setup 요청 → 401."""
    resp = await client.post("/auth/2fa/setup")
    assert resp.status_code == 401


# ── POST /auth/2fa/verify ─────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_2fa_verify_success(
    auth_client: AsyncClient,
    mock_two_factor_service: AsyncMock,
    mock_audit_service: AsyncMock,
):
    """올바른 TOTP 코드 → 2FA 활성화 + 백업 코드 10개 반환."""
    mock_two_factor_service.activate.return_value = BACKUP_CODES_10

    resp = await auth_client.post(
        "/auth/2fa/verify",
        json={"code": "123456"},
        headers={"Authorization": "Bearer valid.access.token"},
    )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "message" in data
    assert "backup_codes" in data
    assert len(data["backup_codes"]) == 10
    mock_audit_service.log.assert_called_once()


@pytest.mark.anyio
async def test_2fa_verify_invalid_code(
    auth_client: AsyncClient,
    mock_two_factor_service: AsyncMock,
):
    """잘못된 TOTP 코드 → 400 INVALID_TOTP_CODE."""
    mock_two_factor_service.activate.side_effect = AuthErrors.invalid_totp_code()

    resp = await auth_client.post(
        "/auth/2fa/verify",
        json={"code": "000000"},
        headers={"Authorization": "Bearer valid.access.token"},
    )

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "INVALID_TOTP_CODE"


@pytest.mark.anyio
async def test_2fa_verify_setup_required(
    auth_client: AsyncClient,
    mock_two_factor_service: AsyncMock,
):
    """setup 없이 verify 호출 (Redis pending 없음) → 400 TOTP_SETUP_REQUIRED."""
    mock_two_factor_service.activate.side_effect = AuthErrors.totp_setup_required()

    resp = await auth_client.post(
        "/auth/2fa/verify",
        json={"code": "123456"},
        headers={"Authorization": "Bearer valid.access.token"},
    )

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "TOTP_SETUP_REQUIRED"


@pytest.mark.anyio
async def test_2fa_verify_invalid_code_format(auth_client: AsyncClient):
    """코드 형식 오류 (6자리 숫자가 아닌 경우) → 422."""
    resp = await auth_client.post(
        "/auth/2fa/verify",
        json={"code": "ABCDEF"},
        headers={"Authorization": "Bearer valid.access.token"},
    )
    assert resp.status_code == 422


@pytest.mark.anyio
async def test_2fa_verify_short_code(auth_client: AsyncClient):
    """5자리 코드 → 422 (min_length=6)."""
    resp = await auth_client.post(
        "/auth/2fa/verify",
        json={"code": "12345"},
        headers={"Authorization": "Bearer valid.access.token"},
    )
    assert resp.status_code == 422


# ── POST /auth/2fa/disable ────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_2fa_disable_with_totp_code(
    auth_client_2fa: AsyncClient,
    mock_two_factor_service: AsyncMock,
    mock_audit_service: AsyncMock,
):
    """TOTP 6자리 코드로 2FA 비활성화 성공."""
    mock_two_factor_service.disable.return_value = None

    resp = await auth_client_2fa.post(
        "/auth/2fa/disable",
        json={"code": "123456"},
        headers={"Authorization": "Bearer valid.access.token"},
    )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "message" in data
    assert "비활성화" in data["message"]
    mock_audit_service.log.assert_called_once()


@pytest.mark.anyio
async def test_2fa_disable_with_backup_code(
    auth_client_2fa: AsyncClient,
    mock_two_factor_service: AsyncMock,
):
    """백업 코드(10자리)로 2FA 비활성화 성공."""
    mock_two_factor_service.disable.return_value = None

    resp = await auth_client_2fa.post(
        "/auth/2fa/disable",
        json={"code": "ABCD123456"},
        headers={"Authorization": "Bearer valid.access.token"},
    )

    assert resp.status_code == 200
    assert "비활성화" in resp.json()["data"]["message"]


@pytest.mark.anyio
async def test_2fa_disable_not_enabled(
    auth_client: AsyncClient,
    mock_two_factor_service: AsyncMock,
):
    """2FA 미활성 사용자가 disable 시도 → 400 TOTP_NOT_ENABLED."""
    mock_two_factor_service.disable.side_effect = AuthErrors.totp_not_enabled()

    resp = await auth_client.post(
        "/auth/2fa/disable",
        json={"code": "123456"},
        headers={"Authorization": "Bearer valid.access.token"},
    )

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "TOTP_NOT_ENABLED"


@pytest.mark.anyio
async def test_2fa_disable_invalid_code(
    auth_client_2fa: AsyncClient,
    mock_two_factor_service: AsyncMock,
):
    """잘못된 코드로 disable 시도 → 400 INVALID_TOTP_CODE."""
    mock_two_factor_service.disable.side_effect = AuthErrors.invalid_totp_code()

    resp = await auth_client_2fa.post(
        "/auth/2fa/disable",
        json={"code": "999999"},
        headers={"Authorization": "Bearer valid.access.token"},
    )

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "INVALID_TOTP_CODE"


# ── GET /auth/2fa/status ──────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_2fa_status_enabled(
    auth_client_2fa: AsyncClient,
    mock_two_factor_service: AsyncMock,
):
    """2FA 활성 사용자 → is_enabled=True."""
    mock_two_factor_service.get_status.return_value = TwoFactorStatusResponse(
        is_enabled=True,
        has_backup_codes=True,
    )

    resp = await auth_client_2fa.get(
        "/auth/2fa/status",
        headers={"Authorization": "Bearer valid.access.token"},
    )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["is_enabled"] is True
    assert data["has_backup_codes"] is True


@pytest.mark.anyio
async def test_2fa_status_disabled(
    auth_client: AsyncClient,
    mock_two_factor_service: AsyncMock,
):
    """2FA 비활성 사용자 → is_enabled=False."""
    mock_two_factor_service.get_status.return_value = TwoFactorStatusResponse(
        is_enabled=False,
        has_backup_codes=False,
    )

    resp = await auth_client.get(
        "/auth/2fa/status",
        headers={"Authorization": "Bearer valid.access.token"},
    )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["is_enabled"] is False
    assert data["has_backup_codes"] is False


@pytest.mark.anyio
async def test_2fa_status_unauthorized(client: AsyncClient):
    """인증 없이 status 조회 → 401."""
    resp = await client.get("/auth/2fa/status")
    assert resp.status_code == 401


# ── POST /auth/login (2FA 분기) ───────────────────────────────────────────────


@pytest.mark.anyio
async def test_login_with_2fa_disabled_user(
    client: AsyncClient,
    mock_auth_service: AsyncMock,
    mock_session_service: AsyncMock,
):
    """2FA 비활성 사용자 로그인 → requires_2fa=False, tokens 즉시 발급."""
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
    assert data["requires_2fa"] is False
    assert data["user"] is not None
    assert data["tokens"] is not None
    assert data["temp_token"] is None


@pytest.mark.anyio
async def test_login_with_2fa_enabled_user(
    client: AsyncClient,
    mock_auth_service: AsyncMock,
):
    """2FA 활성 사용자 로그인 → requires_2fa=True, temp_token 반환."""
    user = _make_user(is_2fa_enabled=True)
    mock_auth_service.verify_credentials.return_value = user
    mock_auth_service.store_2fa_login_pending.return_value = None

    resp = await client.post(
        "/auth/login",
        json={"email": "test@example.com", "password": "Str0ng!Pw"},
        headers={
            "X-Device-Name": "iPhone 15 Pro",
            "X-Device-Fingerprint": "abc123fingerprint",
        },
    )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["requires_2fa"] is True
    assert data["temp_token"] is not None
    assert data["temp_token_expires_in"] == 300
    assert data["user"] is None
    assert data["tokens"] is None


@pytest.mark.anyio
async def test_login_2fa_stores_device_info_in_redis(
    client: AsyncClient,
    mock_auth_service: AsyncMock,
):
    """2FA 활성 로그인 시 Redis에 디바이스 정보(device_name) 포함 저장."""
    user = _make_user(is_2fa_enabled=True)
    mock_auth_service.verify_credentials.return_value = user
    mock_auth_service.store_2fa_login_pending.return_value = None

    await client.post(
        "/auth/login",
        json={"email": "test@example.com", "password": "Str0ng!Pw"},
        headers={"X-Device-Name": "Samsung Galaxy S24"},
    )

    mock_auth_service.store_2fa_login_pending.assert_called_once()
    call_kwargs = mock_auth_service.store_2fa_login_pending.call_args
    # data 인수 파싱 (JSON string)
    data_arg = call_kwargs.kwargs.get("data") or call_kwargs.args[1]
    stored = json.loads(data_arg)
    assert stored["device_name"] == "Samsung Galaxy S24"


# ── POST /auth/2fa/login-verify ───────────────────────────────────────────────


def _pending_json(user: User, device_name: str = "iPhone 15 Pro") -> str:
    """2FA pending Redis 값 생성 헬퍼."""
    return json.dumps({
        "user_id": str(user.id),
        "device_name": device_name,
        "device_fingerprint": "abc123",
        "ip_address": "127.0.0.1",
        "user_agent": "TestAgent/1.0",
        "device_type": "ios",
    })


@pytest.mark.anyio
async def test_login_verify_totp_success(
    client: AsyncClient,
    mock_auth_service: AsyncMock,
    mock_two_factor_service: AsyncMock,
    mock_session_service: AsyncMock,
):
    """올바른 temp_token + TOTP 코드 → 최종 토큰 발급."""
    user = _make_user(is_2fa_enabled=True)
    tokens = _make_token_pair()

    mock_auth_service.get_and_delete_2fa_login_pending.return_value = _pending_json(user)
    mock_auth_service.get_user_by_id.return_value = user
    mock_two_factor_service.verify_code.return_value = True
    mock_auth_service.issue_tokens_with_store.return_value = tokens

    resp = await client.post(
        "/auth/2fa/login-verify",
        json={"temp_token": "valid-temp-token-value", "code": "123456"},
    )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["user"] is not None
    assert data["tokens"] is not None
    assert data["requires_2fa"] is False


@pytest.mark.anyio
async def test_login_verify_backup_code_success(
    client: AsyncClient,
    mock_auth_service: AsyncMock,
    mock_two_factor_service: AsyncMock,
    mock_session_service: AsyncMock,
):
    """올바른 temp_token + 백업 코드(10자리) → 최종 토큰 발급."""
    user = _make_user(is_2fa_enabled=True)
    tokens = _make_token_pair()

    mock_auth_service.get_and_delete_2fa_login_pending.return_value = _pending_json(user)
    mock_auth_service.get_user_by_id.return_value = user
    mock_two_factor_service.verify_code.return_value = True
    mock_two_factor_service.count_remaining_backup_codes.return_value = 9
    mock_auth_service.issue_tokens_with_store.return_value = tokens

    resp = await client.post(
        "/auth/2fa/login-verify",
        json={"temp_token": "valid-temp-token-value", "code": "ABCD123456"},
    )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["user"] is not None
    assert data["tokens"] is not None
    # 백업 코드 사용 시 audit 로그 추가 기록 확인
    from unittest.mock import call
    mock_two_factor_service.count_remaining_backup_codes.assert_called_once()


@pytest.mark.anyio
async def test_login_verify_invalid_temp_token(
    client: AsyncClient,
    mock_auth_service: AsyncMock,
):
    """만료/잘못된 temp_token → 401 INVALID_TEMP_TOKEN."""
    mock_auth_service.get_and_delete_2fa_login_pending.return_value = None

    resp = await client.post(
        "/auth/2fa/login-verify",
        json={"temp_token": "expired-or-invalid-token", "code": "123456"},
    )

    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "INVALID_TEMP_TOKEN"


@pytest.mark.anyio
async def test_login_verify_invalid_totp_code(
    client: AsyncClient,
    mock_auth_service: AsyncMock,
    mock_two_factor_service: AsyncMock,
    mock_audit_service: AsyncMock,
):
    """올바른 temp_token + 잘못된 TOTP 코드 → 400 INVALID_TOTP_CODE."""
    user = _make_user(is_2fa_enabled=True)

    mock_auth_service.get_and_delete_2fa_login_pending.return_value = _pending_json(user)
    mock_auth_service.get_user_by_id.return_value = user
    mock_two_factor_service.verify_code.return_value = False

    resp = await client.post(
        "/auth/2fa/login-verify",
        json={"temp_token": "valid-temp-token", "code": "000000"},
    )

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "INVALID_TOTP_CODE"
    # 실패 audit 로그 기록 확인
    mock_audit_service.log.assert_called()


@pytest.mark.anyio
async def test_login_verify_temp_token_single_use(
    client: AsyncClient,
    mock_auth_service: AsyncMock,
    mock_two_factor_service: AsyncMock,
    mock_session_service: AsyncMock,
):
    """temp_token은 1회 사용 후 무효화 (GETDEL 방식)."""
    user = _make_user(is_2fa_enabled=True)
    tokens = _make_token_pair()

    # 첫 번째 호출: 유효, 이후 None (1회 사용)
    mock_auth_service.get_and_delete_2fa_login_pending.side_effect = [
        _pending_json(user),  # 첫 번째: 유효
        None,                  # 두 번째: 이미 삭제됨
    ]
    mock_auth_service.get_user_by_id.return_value = user
    mock_two_factor_service.verify_code.return_value = True
    mock_auth_service.issue_tokens_with_store.return_value = tokens

    resp1 = await client.post(
        "/auth/2fa/login-verify",
        json={"temp_token": "one-time-token", "code": "123456"},
    )
    resp2 = await client.post(
        "/auth/2fa/login-verify",
        json={"temp_token": "one-time-token", "code": "123456"},
    )

    assert resp1.status_code == 200
    assert resp2.status_code == 401
    assert resp2.json()["error"]["code"] == "INVALID_TEMP_TOKEN"


# ── GET /auth/sessions ────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_list_sessions_success(
    auth_client: AsyncClient,
    mock_session_service: AsyncMock,
):
    """활성 세션 목록 조회 → 200, sessions 리스트 반환."""
    mock_client = _make_client()
    mock_session_service.list_sessions.return_value = [mock_client]

    resp = await auth_client.get(
        "/auth/sessions",
        headers={"Authorization": "Bearer valid.access.token"},
    )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "sessions" in data
    assert len(data["sessions"]) == 1
    session = data["sessions"][0]
    assert "client_id" in session
    assert "device_type" in session
    assert "device_name" in session
    assert "is_current" in session


@pytest.mark.anyio
async def test_list_sessions_empty(
    auth_client: AsyncClient,
    mock_session_service: AsyncMock,
):
    """활성 세션 없음 → 빈 리스트 반환."""
    mock_session_service.list_sessions.return_value = []

    resp = await auth_client.get(
        "/auth/sessions",
        headers={"Authorization": "Bearer valid.access.token"},
    )

    assert resp.status_code == 200
    assert resp.json()["data"]["sessions"] == []


@pytest.mark.anyio
async def test_list_sessions_unauthorized(client: AsyncClient):
    """인증 없이 세션 목록 조회 → 401."""
    resp = await client.get("/auth/sessions")
    assert resp.status_code == 401


# ── DELETE /auth/sessions/{client_id} ─────────────────────────────────────────


@pytest.mark.anyio
async def test_revoke_session_success(
    auth_client: AsyncClient,
    mock_session_service: AsyncMock,
    mock_audit_service: AsyncMock,
):
    """개별 세션 종료 → 200, 종료 메시지 반환."""
    target_client_id = uuid.uuid4()
    mock_session_service.revoke_session.return_value = None

    resp = await auth_client.delete(
        f"/auth/sessions/{target_client_id}",
        headers={"Authorization": "Bearer valid.access.token"},
    )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "message" in data
    assert "종료" in data["message"]
    mock_session_service.revoke_session.assert_called_once()
    mock_audit_service.log.assert_called_once()


@pytest.mark.anyio
async def test_revoke_session_not_found(
    auth_client: AsyncClient,
    mock_session_service: AsyncMock,
):
    """존재하지 않는 세션 종료 시도 → 404 SESSION_NOT_FOUND."""
    mock_session_service.revoke_session.side_effect = AuthErrors.session_not_found()

    resp = await auth_client.delete(
        f"/auth/sessions/{uuid.uuid4()}",
        headers={"Authorization": "Bearer valid.access.token"},
    )

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "SESSION_NOT_FOUND"


@pytest.mark.anyio
async def test_revoke_session_invalid_uuid(auth_client: AsyncClient):
    """잘못된 UUID 형식 → 422."""
    resp = await auth_client.delete(
        "/auth/sessions/not-a-valid-uuid",
        headers={"Authorization": "Bearer valid.access.token"},
    )
    assert resp.status_code == 422


# ── POST /auth/logout-all ─────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_logout_all_success(
    auth_client: AsyncClient,
    mock_session_service: AsyncMock,
    mock_audit_service: AsyncMock,
):
    """전체 세션 로그아웃 → 200, revoked_count 반환."""
    mock_session_service.revoke_all_sessions.return_value = 3

    resp = await auth_client.post(
        "/auth/logout-all",
        headers={"Authorization": "Bearer valid.access.token"},
    )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["revoked_count"] == 3
    assert "로그아웃" in data["message"]
    mock_session_service.revoke_all_sessions.assert_called_once()
    mock_audit_service.log.assert_called_once()


@pytest.mark.anyio
async def test_logout_all_no_sessions(
    auth_client: AsyncClient,
    mock_session_service: AsyncMock,
):
    """종료할 세션이 없는 경우 → 200, revoked_count=0."""
    mock_session_service.revoke_all_sessions.return_value = 0

    resp = await auth_client.post(
        "/auth/logout-all",
        headers={"Authorization": "Bearer valid.access.token"},
    )

    assert resp.status_code == 200
    assert resp.json()["data"]["revoked_count"] == 0


@pytest.mark.anyio
async def test_logout_all_unauthorized(client: AsyncClient):
    """인증 없이 전체 로그아웃 시도 → 401."""
    resp = await client.post("/auth/logout-all")
    assert resp.status_code == 401


# ── 응답 포맷 공통 검증 ───────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_2fa_setup_response_format(
    auth_client: AsyncClient,
    mock_two_factor_service: AsyncMock,
):
    """응답 포맷: data, error=null, meta.timestamp 검증."""
    from app.schemas.two_factor import TwoFactorSetupResponse

    mock_two_factor_service.generate_setup.return_value = TwoFactorSetupResponse(
        secret="JBSWY3DPEHPK3PXP",
        qr_code_uri="otpauth://totp/CoinTrader:test@example.com?secret=JBSWY3DPEHPK3PXP",
        qr_code_base64="base64png==",
        expires_in=600,
    )

    resp = await auth_client.post(
        "/auth/2fa/setup",
        headers={"Authorization": "Bearer valid.access.token"},
    )

    body = resp.json()
    assert body["error"] is None
    assert "meta" in body
    assert "timestamp" in body["meta"]


@pytest.mark.anyio
async def test_login_verify_response_format(
    client: AsyncClient,
    mock_auth_service: AsyncMock,
    mock_two_factor_service: AsyncMock,
    mock_session_service: AsyncMock,
):
    """login-verify 성공 응답 포맷: user, tokens 필드 검증."""
    user = _make_user(is_2fa_enabled=True)
    tokens = _make_token_pair()

    mock_auth_service.get_and_delete_2fa_login_pending.return_value = _pending_json(user)
    mock_auth_service.get_user_by_id.return_value = user
    mock_two_factor_service.verify_code.return_value = True
    mock_auth_service.issue_tokens_with_store.return_value = tokens

    resp = await client.post(
        "/auth/2fa/login-verify",
        json={"temp_token": "valid-token", "code": "123456"},
    )

    body = resp.json()
    assert body["error"] is None
    assert "meta" in body
    data = body["data"]
    assert "user" in data
    assert "tokens" in data
    user_data = data["user"]
    for field in ["id", "email", "nickname", "is_2fa_enabled", "email_verified"]:
        assert field in user_data, f"필드 누락: {field}"


# ── 보안 시나리오 ──────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_2fa_verify_code_validation_non_numeric(auth_client: AsyncClient):
    """TwoFactorVerifyRequest: 숫자가 아닌 6자리 코드 → 422."""
    resp = await auth_client.post(
        "/auth/2fa/verify",
        json={"code": "ABC123"},
        headers={"Authorization": "Bearer valid.access.token"},
    )
    assert resp.status_code == 422


@pytest.mark.anyio
async def test_login_verify_missing_temp_token(client: AsyncClient):
    """temp_token 없이 login-verify 요청 → 422."""
    resp = await client.post(
        "/auth/2fa/login-verify",
        json={"code": "123456"},
    )
    assert resp.status_code == 422


@pytest.mark.anyio
async def test_login_verify_missing_code(client: AsyncClient):
    """code 없이 login-verify 요청 → 422."""
    resp = await client.post(
        "/auth/2fa/login-verify",
        json={"temp_token": "some-token"},
    )
    assert resp.status_code == 422

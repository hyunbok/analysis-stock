"""거래소 계정 관리 API 통합 테스트 — POST/GET/PUT/DELETE /api/v1/exchanges."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.exceptions import AppError, ExchangeErrors
from app.middleware.correlation_id import CorrelationIdMiddleware
from app.middleware.error_handler import register_error_handlers
from app.models.user import User
from app.schemas.exchange import ExchangeAccountResponse, ExchangeVerifyResponse

# ── 헬퍼 ─────────────────────────────────────────────────────────────────────


def _make_user(email: str = "test@example.com") -> User:
    user = MagicMock(spec=User)
    user.id = uuid.uuid4()
    user.email = email
    user.nickname = "테스터"
    user.email_verified_at = datetime.now(UTC)
    user.soft_deleted_at = None
    return user


def _make_account_response(
    exchange_type: str = "upbit",
    nickname: str | None = "메인 업비트",
    api_key_masked: str = "****key456",
    is_verified: bool = True,
    warning_level: str = "none",
    permissions: list[str] | None = None,
) -> ExchangeAccountResponse:
    return ExchangeAccountResponse(
        id=uuid.uuid4(),
        exchange_type=exchange_type,
        nickname=nickname,
        api_key_masked=api_key_masked,
        permissions=permissions or ["view_balance", "trade"],
        is_active=True,
        is_verified=is_verified,
        warning_level=warning_level,
        verified_at=datetime.now(UTC),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _make_verify_response(
    is_valid: bool = True,
    has_withdraw_permission: bool = False,
    warning_level: str = "none",
) -> ExchangeVerifyResponse:
    return ExchangeVerifyResponse(
        is_valid=is_valid,
        permissions=["view_balance", "trade"],
        has_withdraw_permission=has_withdraw_permission,
        warning_level=warning_level,
        message=None,
    )


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_exchange_service() -> AsyncMock:
    svc = AsyncMock()
    return svc


@pytest.fixture
def mock_user() -> User:
    return _make_user()


@pytest.fixture
def mock_other_user() -> User:
    return _make_user(email="other@example.com")


def _build_app(
    mock_exchange_service: AsyncMock,
    current_user: User | None = None,
) -> FastAPI:
    """테스트용 FastAPI 앱 — exchange 라우터 + 선택적 인증 override."""
    from app.api.v1.exchanges import router as exchanges_router
    from app.core.deps import get_audit_service, get_current_user, get_exchange_account_service

    app = FastAPI()
    register_error_handlers(app)
    app.add_middleware(CorrelationIdMiddleware)
    app.include_router(exchanges_router, prefix="/exchanges")

    mock_audit = AsyncMock()
    mock_audit.log.return_value = None

    app.dependency_overrides[get_exchange_account_service] = lambda: mock_exchange_service
    app.dependency_overrides[get_audit_service] = lambda: mock_audit
    if current_user is not None:
        app.dependency_overrides[get_current_user] = lambda: current_user
    return app


@pytest.fixture
def test_app(mock_exchange_service: AsyncMock, mock_user: User) -> FastAPI:
    """인증된 사용자 앱."""
    return _build_app(mock_exchange_service, current_user=mock_user)


@pytest.fixture
def test_app_no_auth(mock_exchange_service: AsyncMock) -> FastAPI:
    """인증 override 없는 앱 (401 테스트용)."""
    return _build_app(mock_exchange_service, current_user=None)


@pytest.fixture
async def client(test_app: FastAPI) -> AsyncClient:
    async with AsyncClient(
        transport=ASGITransport(app=test_app), base_url="http://test"
    ) as c:
        yield c


@pytest.fixture
async def anon_client(test_app_no_auth: FastAPI) -> AsyncClient:
    async with AsyncClient(
        transport=ASGITransport(app=test_app_no_auth), base_url="http://test"
    ) as c:
        yield c


# ── 인증 검증 ─────────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_list_accounts_unauthenticated_returns_401(anon_client: AsyncClient):
    """Authorization 헤더 없이 목록 조회 → 401."""
    resp = await anon_client.get("/exchanges")
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_register_unauthenticated_returns_401(anon_client: AsyncClient):
    """인증 없이 등록 → 401."""
    resp = await anon_client.post(
        "/exchanges",
        json={"exchange_type": "upbit", "api_key": "key", "api_secret": "secret"},
    )
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_update_unauthenticated_returns_401(anon_client: AsyncClient):
    """인증 없이 수정 → 401."""
    resp = await anon_client.put(
        f"/exchanges/{uuid.uuid4()}",
        json={"nickname": "새 이름"},
    )
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_delete_unauthenticated_returns_401(anon_client: AsyncClient):
    """인증 없이 삭제 → 401."""
    resp = await anon_client.delete(f"/exchanges/{uuid.uuid4()}")
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_verify_unauthenticated_returns_401(anon_client: AsyncClient):
    """인증 없이 검증 → 401."""
    resp = await anon_client.post(f"/exchanges/{uuid.uuid4()}/verify")
    assert resp.status_code == 401


# ── POST /exchanges — 등록 ────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_register_success_returns_201_with_masked_key(
    client: AsyncClient, mock_exchange_service: AsyncMock
):
    """정상 등록 → 201 + api_key_masked 포함, api_secret 미포함."""
    expected = _make_account_response(
        exchange_type="upbit",
        nickname="메인 업비트",
        api_key_masked="****key456",
    )
    mock_exchange_service.register.return_value = expected

    resp = await client.post(
        "/exchanges",
        json={
            "exchange_type": "upbit",
            "api_key": "abcdefkey456",
            "api_secret": "mysecret",
            "nickname": "메인 업비트",
        },
    )

    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["api_key_masked"] == "****key456"
    assert data["exchange_type"] == "upbit"
    assert data["nickname"] == "메인 업비트"
    assert data["is_verified"] is True
    assert data["warning_level"] == "none"
    assert "api_secret" not in data
    assert resp.json()["error"] is None


@pytest.mark.anyio
async def test_register_without_nickname_returns_201(
    client: AsyncClient, mock_exchange_service: AsyncMock
):
    """닉네임 없이 등록 → 201."""
    expected = _make_account_response(nickname=None)
    mock_exchange_service.register.return_value = expected

    resp = await client.post(
        "/exchanges",
        json={
            "exchange_type": "upbit",
            "api_key": "abcdefkey456",
            "api_secret": "mysecret",
        },
    )

    assert resp.status_code == 201
    assert resp.json()["data"]["nickname"] is None


@pytest.mark.anyio
async def test_register_withdraw_permission_returns_warning(
    client: AsyncClient, mock_exchange_service: AsyncMock
):
    """출금 권한 키 등록 → warning_level='warning'."""
    expected = _make_account_response(
        warning_level="warning",
        permissions=["view_balance", "trade", "withdraw"],
    )
    mock_exchange_service.register.return_value = expected

    resp = await client.post(
        "/exchanges",
        json={
            "exchange_type": "upbit",
            "api_key": "abcdefkey456",
            "api_secret": "mysecret",
        },
    )

    assert resp.status_code == 201
    assert resp.json()["data"]["warning_level"] == "warning"


@pytest.mark.anyio
async def test_register_duplicate_returns_409(
    client: AsyncClient, mock_exchange_service: AsyncMock
):
    """동일 거래소 중복 등록 → 409 EXCHANGE_DUPLICATE_ACCOUNT."""
    mock_exchange_service.register.side_effect = ExchangeErrors.duplicate_exchange_account(
        "upbit"
    )

    resp = await client.post(
        "/exchanges",
        json={
            "exchange_type": "upbit",
            "api_key": "abcdefkey456",
            "api_secret": "mysecret",
        },
    )

    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "EXCHANGE_DUPLICATE_ACCOUNT"


@pytest.mark.anyio
async def test_register_invalid_api_key_returns_422(
    client: AsyncClient, mock_exchange_service: AsyncMock
):
    """API 키 검증 실패 → 422 EXCHANGE_INVALID_API_KEY."""
    mock_exchange_service.register.side_effect = ExchangeErrors.invalid_api_key()

    resp = await client.post(
        "/exchanges",
        json={
            "exchange_type": "upbit",
            "api_key": "badkey",
            "api_secret": "badsecret",
        },
    )

    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "EXCHANGE_INVALID_API_KEY"


@pytest.mark.anyio
async def test_register_encryption_not_configured_returns_500(
    client: AsyncClient, mock_exchange_service: AsyncMock
):
    """암호화 키 미설정 → 500 EXCHANGE_ENCRYPTION_NOT_CONFIGURED."""
    mock_exchange_service.register.side_effect = (
        ExchangeErrors.encryption_key_not_configured()
    )

    resp = await client.post(
        "/exchanges",
        json={
            "exchange_type": "upbit",
            "api_key": "key",
            "api_secret": "secret",
        },
    )

    assert resp.status_code == 500
    assert resp.json()["error"]["code"] == "EXCHANGE_ENCRYPTION_NOT_CONFIGURED"


@pytest.mark.anyio
async def test_register_exchange_unavailable_returns_503(
    client: AsyncClient, mock_exchange_service: AsyncMock
):
    """거래소 연결 불가 → 503 EXCHANGE_UNAVAILABLE."""
    mock_exchange_service.register.side_effect = ExchangeErrors.unavailable("upbit")

    resp = await client.post(
        "/exchanges",
        json={
            "exchange_type": "upbit",
            "api_key": "key",
            "api_secret": "secret",
        },
    )

    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "EXCHANGE_UNAVAILABLE"


@pytest.mark.anyio
async def test_register_missing_required_fields_returns_422(client: AsyncClient):
    """필수 필드 누락 → 422 (Pydantic 검증 오류)."""
    resp = await client.post(
        "/exchanges",
        json={"exchange_type": "upbit"},
    )

    assert resp.status_code == 422


@pytest.mark.anyio
async def test_register_invalid_exchange_type_returns_422(client: AsyncClient):
    """지원하지 않는 거래소 타입 → 422."""
    resp = await client.post(
        "/exchanges",
        json={
            "exchange_type": "unknown_exchange",
            "api_key": "key",
            "api_secret": "secret",
        },
    )

    assert resp.status_code == 422


# ── GET /exchanges — 목록 조회 ────────────────────────────────────────────────


@pytest.mark.anyio
async def test_list_accounts_success_returns_200_with_list(
    client: AsyncClient, mock_exchange_service: AsyncMock
):
    """목록 조회 → 200 + 계정 목록."""
    accounts = [
        _make_account_response(exchange_type="upbit"),
        _make_account_response(exchange_type="coinone"),
    ]
    mock_exchange_service.list_accounts.return_value = accounts

    resp = await client.get("/exchanges")

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert isinstance(data, list)
    assert len(data) == 2
    assert data[0]["exchange_type"] == "upbit"
    assert data[1]["exchange_type"] == "coinone"
    assert resp.json()["error"] is None


@pytest.mark.anyio
async def test_list_accounts_empty_returns_empty_list(
    client: AsyncClient, mock_exchange_service: AsyncMock
):
    """등록된 계정 없을 때 → 200 + 빈 배열."""
    mock_exchange_service.list_accounts.return_value = []

    resp = await client.get("/exchanges")

    assert resp.status_code == 200
    assert resp.json()["data"] == []


@pytest.mark.anyio
async def test_list_accounts_no_api_secret_in_response(
    client: AsyncClient, mock_exchange_service: AsyncMock
):
    """목록 응답에 api_secret 없음 확인."""
    mock_exchange_service.list_accounts.return_value = [_make_account_response()]

    resp = await client.get("/exchanges")

    data = resp.json()["data"]
    for account in data:
        assert "api_secret" not in account
        assert "api_key_masked" in account


# ── PUT /exchanges/{id} — 수정 ────────────────────────────────────────────────


@pytest.mark.anyio
async def test_update_nickname_only_returns_200(
    client: AsyncClient, mock_exchange_service: AsyncMock
):
    """닉네임만 수정 → 200."""
    account_id = uuid.uuid4()
    expected = _make_account_response(nickname="새 닉네임")
    mock_exchange_service.update.return_value = expected

    resp = await client.put(
        f"/exchanges/{account_id}",
        json={"nickname": "새 닉네임"},
    )

    assert resp.status_code == 200
    assert resp.json()["data"]["nickname"] == "새 닉네임"


@pytest.mark.anyio
async def test_update_api_key_pair_returns_200_with_reverification(
    client: AsyncClient, mock_exchange_service: AsyncMock
):
    """API 키 쌍 변경 → 200 + is_verified=True (재검증)."""
    account_id = uuid.uuid4()
    expected = _make_account_response(api_key_masked="****new789", is_verified=True)
    mock_exchange_service.update.return_value = expected

    resp = await client.put(
        f"/exchanges/{account_id}",
        json={"api_key": "newabckey789", "api_secret": "newsecret"},
    )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["api_key_masked"] == "****new789"
    assert data["is_verified"] is True


@pytest.mark.anyio
async def test_update_account_not_found_returns_404(
    client: AsyncClient, mock_exchange_service: AsyncMock
):
    """존재하지 않는 계정 수정 → 404 EXCHANGE_ACCOUNT_NOT_FOUND."""
    mock_exchange_service.update.side_effect = ExchangeErrors.account_not_found()

    resp = await client.put(
        f"/exchanges/{uuid.uuid4()}",
        json={"nickname": "테스트"},
    )

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "EXCHANGE_ACCOUNT_NOT_FOUND"


@pytest.mark.anyio
async def test_update_key_pair_required_returns_400(
    client: AsyncClient, mock_exchange_service: AsyncMock
):
    """API 키만 제공하고 시크릿 누락 → 400 EXCHANGE_KEY_PAIR_REQUIRED."""
    mock_exchange_service.update.side_effect = ExchangeErrors.key_pair_required()

    resp = await client.put(
        f"/exchanges/{uuid.uuid4()}",
        json={"api_key": "onlykeynotsecret"},
    )

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "EXCHANGE_KEY_PAIR_REQUIRED"


@pytest.mark.anyio
async def test_update_invalid_api_key_returns_422(
    client: AsyncClient, mock_exchange_service: AsyncMock
):
    """새 API 키 검증 실패 → 422 EXCHANGE_INVALID_API_KEY."""
    mock_exchange_service.update.side_effect = ExchangeErrors.invalid_api_key()

    resp = await client.put(
        f"/exchanges/{uuid.uuid4()}",
        json={"api_key": "badkey", "api_secret": "badsecret"},
    )

    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "EXCHANGE_INVALID_API_KEY"


@pytest.mark.anyio
async def test_update_empty_string_api_key_returns_422(client: AsyncClient):
    """빈 문자열 api_key → 422 (Pydantic field_validator)."""
    resp = await client.put(
        f"/exchanges/{uuid.uuid4()}",
        json={"api_key": "", "api_secret": "secret"},
    )

    assert resp.status_code == 422


# ── DELETE /exchanges/{id} — 삭제 ────────────────────────────────────────────


@pytest.mark.anyio
async def test_delete_success_returns_200(
    client: AsyncClient, mock_exchange_service: AsyncMock
):
    """정상 삭제 → 200 + 메시지."""
    account_id = uuid.uuid4()
    mock_exchange_service.delete.return_value = None

    resp = await client.delete(f"/exchanges/{account_id}")

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "message" in data
    assert resp.json()["error"] is None


@pytest.mark.anyio
async def test_delete_account_not_found_returns_404(
    client: AsyncClient, mock_exchange_service: AsyncMock
):
    """존재하지 않는 계정 삭제 → 404 EXCHANGE_ACCOUNT_NOT_FOUND."""
    mock_exchange_service.delete.side_effect = ExchangeErrors.account_not_found()

    resp = await client.delete(f"/exchanges/{uuid.uuid4()}")

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "EXCHANGE_ACCOUNT_NOT_FOUND"


# ── POST /exchanges/{id}/verify — 검증 ───────────────────────────────────────


@pytest.mark.anyio
async def test_verify_success_returns_200_with_valid(
    client: AsyncClient, mock_exchange_service: AsyncMock
):
    """API 키 검증 성공 → 200 + is_valid=True."""
    account_id = uuid.uuid4()
    expected = _make_verify_response(is_valid=True, warning_level="none")
    mock_exchange_service.verify.return_value = expected

    resp = await client.post(f"/exchanges/{account_id}/verify")

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["is_valid"] is True
    assert data["warning_level"] == "none"
    assert data["has_withdraw_permission"] is False
    assert resp.json()["error"] is None


@pytest.mark.anyio
async def test_verify_with_withdraw_permission_returns_warning(
    client: AsyncClient, mock_exchange_service: AsyncMock
):
    """출금 권한 키 검증 → warning_level='warning'."""
    account_id = uuid.uuid4()
    expected = _make_verify_response(
        is_valid=True,
        has_withdraw_permission=True,
        warning_level="warning",
    )
    mock_exchange_service.verify.return_value = expected

    resp = await client.post(f"/exchanges/{account_id}/verify")

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["has_withdraw_permission"] is True
    assert data["warning_level"] == "warning"


@pytest.mark.anyio
async def test_verify_account_not_found_returns_404(
    client: AsyncClient, mock_exchange_service: AsyncMock
):
    """존재하지 않는 계정 검증 → 404."""
    mock_exchange_service.verify.side_effect = ExchangeErrors.account_not_found()

    resp = await client.post(f"/exchanges/{uuid.uuid4()}/verify")

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "EXCHANGE_ACCOUNT_NOT_FOUND"


@pytest.mark.anyio
async def test_verify_invalid_api_key_returns_422(
    client: AsyncClient, mock_exchange_service: AsyncMock
):
    """재검증 시 키 무효 → 422."""
    mock_exchange_service.verify.side_effect = ExchangeErrors.invalid_api_key()

    resp = await client.post(f"/exchanges/{uuid.uuid4()}/verify")

    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "EXCHANGE_INVALID_API_KEY"


@pytest.mark.anyio
async def test_verify_exchange_unavailable_returns_503(
    client: AsyncClient, mock_exchange_service: AsyncMock
):
    """거래소 연결 불가로 검증 실패 → 503."""
    mock_exchange_service.verify.side_effect = ExchangeErrors.unavailable("upbit")

    resp = await client.post(f"/exchanges/{uuid.uuid4()}/verify")

    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "EXCHANGE_UNAVAILABLE"


@pytest.mark.anyio
async def test_verify_returns_is_valid_false_in_body(
    client: AsyncClient, mock_exchange_service: AsyncMock
):
    """API 키 무효 시 is_valid=False → 200 (예외 아닌 응답 바디로 반환)."""
    expected = ExchangeVerifyResponse(
        is_valid=False,
        permissions=[],
        has_withdraw_permission=False,
        warning_level="none",
        message="API 키가 만료되었습니다.",
    )
    mock_exchange_service.verify.return_value = expected

    resp = await client.post(f"/exchanges/{uuid.uuid4()}/verify")

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["is_valid"] is False
    assert data["message"] == "API 키가 만료되었습니다."


# ── 타 사용자 계정 접근 ────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_update_other_users_account_returns_404(
    client: AsyncClient, mock_exchange_service: AsyncMock
):
    """타 사용자 계정 수정 → 404 (서비스에서 소유권 검증 후 account_not_found 반환)."""
    mock_exchange_service.update.side_effect = ExchangeErrors.account_not_found()

    resp = await client.put(
        f"/exchanges/{uuid.uuid4()}",
        json={"nickname": "해킹 시도"},
    )

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "EXCHANGE_ACCOUNT_NOT_FOUND"


@pytest.mark.anyio
async def test_delete_other_users_account_returns_404(
    client: AsyncClient, mock_exchange_service: AsyncMock
):
    """타 사용자 계정 삭제 → 404."""
    mock_exchange_service.delete.side_effect = ExchangeErrors.account_not_found()

    resp = await client.delete(f"/exchanges/{uuid.uuid4()}")

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "EXCHANGE_ACCOUNT_NOT_FOUND"


# ── 응답 포맷 공통 검증 ────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_successful_response_has_meta_timestamp(
    client: AsyncClient, mock_exchange_service: AsyncMock
):
    """성공 응답에 meta.timestamp 포함 확인."""
    mock_exchange_service.list_accounts.return_value = []

    resp = await client.get("/exchanges")

    body = resp.json()
    assert "meta" in body
    assert "timestamp" in body["meta"]


@pytest.mark.anyio
async def test_error_response_format(
    client: AsyncClient, mock_exchange_service: AsyncMock
):
    """에러 응답 포맷 — code, message 필드 존재 확인."""
    mock_exchange_service.register.side_effect = AppError("TEST_CODE", "테스트", 400)

    resp = await client.post(
        "/exchanges",
        json={"exchange_type": "upbit", "api_key": "k", "api_secret": "s"},
    )

    error = resp.json()["error"]
    assert "code" in error
    assert "message" in error

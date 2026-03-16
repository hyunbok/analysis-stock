"""Client API 통합 테스트 — POST/GET/DELETE /api/v1/clients.

설계서: docs/tasks/v1-22-fcm-push-notification-plan.md §6.1
패턴:  test_notifications_api.py와 동일 — 서비스 계층 Mock + HTTP 검증
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.middleware.correlation_id import CorrelationIdMiddleware
from app.middleware.error_handler import register_error_handlers
from app.models.user import User

# ── 헬퍼 ─────────────────────────────────────────────────────────────────────


def _make_user(email: str = "test@example.com") -> User:
    user = MagicMock(spec=User)
    user.id = uuid.uuid4()
    user.email = email
    user.nickname = "테스터"
    user.email_verified_at = datetime.now(UTC)
    user.soft_deleted_at = None
    return user


def _make_client_orm(
    client_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    device_type: str = "ios",
    device_name: str | None = "iPhone 16 Pro",
    fcm_token: str | None = "fcm_tok_abc",
    is_active: bool = True,
) -> MagicMock:
    """ORM Client mock (DB에서 반환되는 형태)."""
    c = MagicMock()
    c.id = client_id or uuid.uuid4()
    c.user_id = user_id or uuid.uuid4()
    c.device_type = device_type
    c.device_name = device_name
    c.fcm_token = fcm_token
    c.is_active = is_active
    c.created_at = datetime.now(UTC)
    c.last_active_at = datetime.now(UTC)
    return c


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_client_repo() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def mock_user() -> User:
    return _make_user()


def _build_app(
    mock_repo: AsyncMock,
    current_user: User | None = None,
) -> FastAPI:
    from app.api.v1.clients import router as clients_router
    from app.core.database import get_db
    from app.core.deps import get_client_repository, get_current_user

    app = FastAPI()
    register_error_handlers(app)
    app.add_middleware(CorrelationIdMiddleware)
    app.include_router(clients_router, prefix="/clients")

    mock_db = AsyncMock()
    mock_db.commit = AsyncMock()

    app.dependency_overrides[get_client_repository] = lambda: mock_repo
    app.dependency_overrides[get_db] = lambda: mock_db
    if current_user is not None:
        app.dependency_overrides[get_current_user] = lambda: current_user
    return app


@pytest.fixture
def test_app(mock_client_repo: AsyncMock, mock_user: User) -> FastAPI:
    return _build_app(mock_client_repo, current_user=mock_user)


@pytest.fixture
def test_app_no_auth(mock_client_repo: AsyncMock) -> FastAPI:
    return _build_app(mock_client_repo, current_user=None)


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
async def test_register_client_unauthenticated_returns_401(
    anon_client: AsyncClient,
):
    """인증 없이 POST /clients → 401."""
    resp = await anon_client.post("/clients", json={"device_type": "ios"})
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_list_clients_unauthenticated_returns_401(anon_client: AsyncClient):
    """인증 없이 GET /clients → 401."""
    resp = await anon_client.get("/clients")
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_delete_client_unauthenticated_returns_401(anon_client: AsyncClient):
    """인증 없이 DELETE /clients/{id} → 401."""
    resp = await anon_client.delete(f"/clients/{uuid.uuid4()}")
    assert resp.status_code == 401


# ── POST /clients — 신규 등록 ────────────────────────────────────────────────


@pytest.mark.anyio
async def test_register_client_new_returns_201_with_client_info(
    client: AsyncClient, mock_client_repo: AsyncMock
):
    """신규 클라이언트 등록 (fingerprint 없음) → 201 + client 정보."""
    new_client = _make_client_orm(device_type="ios", fcm_token="fcm_tok_abc")
    mock_client_repo.get_by_user_and_fingerprint = AsyncMock(return_value=None)
    mock_client_repo.create = AsyncMock(return_value=new_client)

    resp = await client.post(
        "/clients",
        json={
            "device_type": "ios",
            "device_name": "iPhone 16 Pro",
            "fcm_token": "fcm_tok_abc",
        },
    )

    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["device_type"] == "ios"
    assert data["is_active"] is True
    assert resp.json()["error"] is None


@pytest.mark.anyio
async def test_register_client_existing_fingerprint_updates_returns_200(
    client: AsyncClient, mock_client_repo: AsyncMock
):
    """X-Device-Fingerprint 헤더 + 기존 클라이언트 → 갱신 200."""
    existing = _make_client_orm(device_type="android")
    updated = _make_client_orm(device_type="android", fcm_token="new_token_xyz")

    mock_client_repo.get_by_user_and_fingerprint = AsyncMock(return_value=existing)
    mock_client_repo.update_fcm_token = AsyncMock(return_value=updated)

    resp = await client.post(
        "/clients",
        json={"device_type": "android", "fcm_token": "new_token_xyz"},
        headers={"X-Device-Fingerprint": "fp_sha256_abc"},
    )

    assert resp.status_code == 200
    assert resp.json()["error"] is None
    mock_client_repo.update_fcm_token.assert_called_once()


@pytest.mark.anyio
async def test_register_client_without_fcm_token_returns_201(
    client: AsyncClient, mock_client_repo: AsyncMock
):
    """fcm_token 없이 등록 → 201 (FCM 비활성 기기 허용)."""
    new_client = _make_client_orm(device_type="web", fcm_token=None)
    mock_client_repo.get_by_user_and_fingerprint = AsyncMock(return_value=None)
    mock_client_repo.create = AsyncMock(return_value=new_client)

    resp = await client.post("/clients", json={"device_type": "web"})

    assert resp.status_code == 201
    assert resp.json()["data"]["fcm_token"] is None


# ── GET /clients ──────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_list_clients_returns_200_with_clients_list(
    client: AsyncClient, mock_client_repo: AsyncMock
):
    """GET /clients → 200 + clients 목록."""
    clients = [
        _make_client_orm(device_type="ios"),
        _make_client_orm(device_type="android"),
    ]
    mock_client_repo.get_by_user = AsyncMock(return_value=clients)

    resp = await client.get("/clients")

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "clients" in data
    assert len(data["clients"]) == 2


@pytest.mark.anyio
async def test_list_clients_empty_returns_empty_list(
    client: AsyncClient, mock_client_repo: AsyncMock
):
    """활성 기기 없음 → 200 + 빈 목록."""
    mock_client_repo.get_by_user = AsyncMock(return_value=[])

    resp = await client.get("/clients")

    assert resp.status_code == 200
    assert resp.json()["data"]["clients"] == []


# ── DELETE /clients/{id} ──────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_delete_client_returns_204(
    client: AsyncClient, mock_client_repo: AsyncMock, mock_user: User
):
    """DELETE /clients/{id} → 204."""
    client_obj = _make_client_orm(user_id=mock_user.id)
    mock_client_repo.get_by_id = AsyncMock(return_value=client_obj)
    mock_client_repo.deactivate = AsyncMock()

    resp = await client.delete(f"/clients/{uuid.uuid4()}")

    assert resp.status_code == 204


@pytest.mark.anyio
async def test_delete_client_not_found_returns_404(
    client: AsyncClient, mock_client_repo: AsyncMock
):
    """미존재 client_id → 404 CLIENT_NOT_FOUND."""
    mock_client_repo.get_by_id = AsyncMock(return_value=None)

    resp = await client.delete(f"/clients/{uuid.uuid4()}")

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "CLIENT_NOT_FOUND"


@pytest.mark.anyio
async def test_delete_client_access_denied_returns_403(
    client: AsyncClient, mock_client_repo: AsyncMock
):
    """타인 소유 클라이언트 삭제 → 403 CLIENT_ACCESS_DENIED."""
    client_obj = _make_client_orm(user_id=uuid.uuid4())  # 다른 사용자 소유
    mock_client_repo.get_by_id = AsyncMock(return_value=client_obj)

    resp = await client.delete(f"/clients/{uuid.uuid4()}")

    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "CLIENT_ACCESS_DENIED"


# ── 응답 포맷 공통 검증 ────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_success_response_has_meta_timestamp(
    client: AsyncClient, mock_client_repo: AsyncMock
):
    """성공 응답에 meta.timestamp 포함."""
    mock_client_repo.get_by_user = AsyncMock(return_value=[])

    resp = await client.get("/clients")

    assert "meta" in resp.json()
    assert "timestamp" in resp.json()["meta"]

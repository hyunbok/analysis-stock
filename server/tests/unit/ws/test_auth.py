"""authenticate_ws 단위 테스트 — JWT 인증 + DB 조회."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from jose import jwt

from app.ws.auth import authenticate_ws


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_valid_token(user_id: str) -> str:
    from app.core.config import settings

    payload = {
        "sub": user_id,
        "type": "access",
        "email": "test@example.com",
        "iat": 1700000000,
        "exp": 9999999999,  # 만료되지 않음
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def _make_expired_token(user_id: str) -> str:
    from app.core.config import settings

    payload = {
        "sub": user_id,
        "type": "access",
        "email": "test@example.com",
        "iat": 1000000000,
        "exp": 1000000001,  # 이미 만료
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def _mock_user(user_id: str, deleted: bool = False) -> MagicMock:
    user = MagicMock()
    user.id = uuid.UUID(user_id)
    user.soft_deleted_at = datetime.now(timezone.utc) if deleted else None
    return user


# ── Tests ──────────────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_authenticate_ws_valid_token_returns_user():
    user_id = str(uuid.uuid4())
    token = _make_valid_token(user_id)
    mock_user = _mock_user(user_id)

    with patch("app.ws.auth.AsyncSessionLocal") as mock_session_ctx:
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session_ctx.return_value = mock_session

        with patch("app.ws.auth.UserRepository") as MockRepo:
            mock_repo = MagicMock()
            mock_repo.get_by_id = AsyncMock(return_value=mock_user)
            MockRepo.return_value = mock_repo

            result = await authenticate_ws(token)

    assert result is mock_user


@pytest.mark.anyio
async def test_authenticate_ws_expired_token_returns_none():
    user_id = str(uuid.uuid4())
    token = _make_expired_token(user_id)

    result = await authenticate_ws(token)
    assert result is None


@pytest.mark.anyio
async def test_authenticate_ws_invalid_token_returns_none():
    result = await authenticate_ws("not.a.valid.token")
    assert result is None


@pytest.mark.anyio
async def test_authenticate_ws_empty_token_returns_none():
    result = await authenticate_ws("")
    assert result is None


@pytest.mark.anyio
async def test_authenticate_ws_user_not_found_returns_none():
    user_id = str(uuid.uuid4())
    token = _make_valid_token(user_id)

    with patch("app.ws.auth.AsyncSessionLocal") as mock_session_ctx:
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session_ctx.return_value = mock_session

        with patch("app.ws.auth.UserRepository") as MockRepo:
            mock_repo = MagicMock()
            mock_repo.get_by_id = AsyncMock(return_value=None)
            MockRepo.return_value = mock_repo

            result = await authenticate_ws(token)

    assert result is None


@pytest.mark.anyio
async def test_authenticate_ws_soft_deleted_user_returns_none():
    user_id = str(uuid.uuid4())
    token = _make_valid_token(user_id)
    deleted_user = _mock_user(user_id, deleted=True)

    with patch("app.ws.auth.AsyncSessionLocal") as mock_session_ctx:
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session_ctx.return_value = mock_session

        with patch("app.ws.auth.UserRepository") as MockRepo:
            mock_repo = MagicMock()
            mock_repo.get_by_id = AsyncMock(return_value=deleted_user)
            MockRepo.return_value = mock_repo

            result = await authenticate_ws(token)

    assert result is None


@pytest.mark.anyio
async def test_authenticate_ws_wrong_token_type_returns_none():
    """refresh 토큰으로 WS 인증 시도 시 거부."""
    from app.core.config import settings

    user_id = str(uuid.uuid4())
    payload = {
        "sub": user_id,
        "type": "refresh",  # wrong type
        "client_id": "some-client",
        "iat": 1700000000,
        "exp": 9999999999,
    }
    token = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

    result = await authenticate_ws(token)
    assert result is None

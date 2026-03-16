"""ClientRepository FCM 메서드 단위 테스트.

설계서: docs/tasks/v1-22-fcm-push-notification-plan.md §11
테스트: update_fcm_token / get_active_fcm_tokens / clear_fcm_token_by_value (~8건)
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.repositories.client_repository import ClientRepository

# ── 상수 / 헬퍼 ───────────────────────────────────────────────────────────────

CLIENT_ID = uuid.uuid4()
USER_ID = uuid.uuid4()


def _make_client(
    client_id: uuid.UUID = CLIENT_ID,
    user_id: uuid.UUID = USER_ID,
    fcm_token: str | None = "fcm_tok_abc",
    is_active: bool = True,
    device_name: str | None = "iPhone 16 Pro",
) -> MagicMock:
    c = MagicMock()
    c.id = client_id
    c.user_id = user_id
    c.fcm_token = fcm_token
    c.is_active = is_active
    c.device_name = device_name
    c.last_active_at = datetime.now(UTC)
    return c


def _make_repo() -> tuple[ClientRepository, AsyncMock]:
    """ClientRepository + mock AsyncSession 반환."""
    db = AsyncMock()
    repo = ClientRepository(db)
    return repo, db


def _make_scalar_result(return_value) -> MagicMock:
    """scalar_one_or_none()를 가진 execute() 반환값 mock."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = return_value
    return result


# ── update_fcm_token ──────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_update_fcm_token_returns_updated_client() -> None:
    """update_fcm_token() → UPDATE + flush + get_by_id 반환."""
    updated_client = _make_client(fcm_token="new_token_xyz")
    repo, db = _make_repo()
    db.execute = AsyncMock(return_value=_make_scalar_result(updated_client))
    db.flush = AsyncMock()

    result = await repo.update_fcm_token(CLIENT_ID, "new_token_xyz")

    assert result == updated_client
    assert db.flush.called


@pytest.mark.anyio
async def test_update_fcm_token_with_device_name_updates_device_name() -> None:
    """device_name 전달 시 갱신된 클라이언트 반환."""
    updated_client = _make_client(device_name="Galaxy S25")
    repo, db = _make_repo()
    db.execute = AsyncMock(return_value=_make_scalar_result(updated_client))
    db.flush = AsyncMock()

    result = await repo.update_fcm_token(
        CLIENT_ID, "tok", device_name="Galaxy S25"
    )

    assert result.device_name == "Galaxy S25"


@pytest.mark.anyio
async def test_update_fcm_token_calls_flush() -> None:
    """update_fcm_token() → flush() 호출 확인."""
    repo, db = _make_repo()
    db.execute = AsyncMock(return_value=_make_scalar_result(_make_client()))
    db.flush = AsyncMock()

    await repo.update_fcm_token(CLIENT_ID, "tok")

    db.flush.assert_called()


# ── get_active_fcm_tokens ─────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_get_active_fcm_tokens_returns_id_token_pairs() -> None:
    """get_active_fcm_tokens() → [(client_id, fcm_token), ...] 반환."""
    repo, db = _make_repo()
    client_id_2 = uuid.uuid4()
    rows = [(CLIENT_ID, "tok_abc"), (client_id_2, "tok_def")]
    result_mock = MagicMock()
    result_mock.all.return_value = rows
    db.execute = AsyncMock(return_value=result_mock)

    result = await repo.get_active_fcm_tokens(USER_ID)

    assert len(result) == 2
    assert result[0] == (CLIENT_ID, "tok_abc")
    assert result[1] == (client_id_2, "tok_def")


@pytest.mark.anyio
async def test_get_active_fcm_tokens_empty_when_no_tokens() -> None:
    """활성 FCM 토큰 없음 → 빈 리스트."""
    repo, db = _make_repo()
    result_mock = MagicMock()
    result_mock.all.return_value = []
    db.execute = AsyncMock(return_value=result_mock)

    result = await repo.get_active_fcm_tokens(USER_ID)

    assert result == []


# ── clear_fcm_token_by_value ──────────────────────────────────────────────────


@pytest.mark.anyio
async def test_clear_fcm_token_by_value_executes_update_and_flushes() -> None:
    """clear_fcm_token_by_value() → UPDATE execute + flush() 호출."""
    repo, db = _make_repo()
    db.execute = AsyncMock()
    db.flush = AsyncMock()

    await repo.clear_fcm_token_by_value("invalid_token_xyz")

    db.execute.assert_called_once()
    db.flush.assert_called_once()


@pytest.mark.anyio
async def test_clear_fcm_token_by_value_returns_none() -> None:
    """clear_fcm_token_by_value() → None 반환 (반환값 없음)."""
    repo, db = _make_repo()
    db.execute = AsyncMock()
    db.flush = AsyncMock()

    result = await repo.clear_fcm_token_by_value("tok_expired")

    assert result is None

"""토큰 정리 태스크 단위 테스트."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4


@pytest.fixture(autouse=True)
def reset_task_context():
    import tasks.context as ctx_module
    ctx_module._task_context = None
    yield
    ctx_module._task_context = None


@pytest.fixture
def mock_ctx():
    ctx = MagicMock()
    ctx.redis = AsyncMock()
    ctx.redis.smembers = AsyncMock(return_value=set())
    ctx.redis.scan_iter = AsyncMock(return_value=aiter([]))
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    ctx.create_session.return_value = session
    return ctx


async def aiter(items):
    """동기 리스트를 async iterator로 변환."""
    for item in items:
        yield item


class TestRefreshTokenCleanup:
    """Refresh Token 인덱스 정리 검증."""

    @pytest.mark.anyio
    async def test_no_deleted_users_returns_zero(self, mock_ctx):
        """soft-deleted 사용자 없으면 0 반환."""
        from tasks.cleanup import _cleanup_expired_tokens_async

        result_mock = MagicMock()
        result_mock.all.return_value = []
        mock_ctx.create_session.return_value.__aenter__.return_value.execute = AsyncMock(
            return_value=result_mock
        )
        mock_ctx.redis.scan_iter = MagicMock(return_value=aiter([]))

        with patch("tasks.cleanup.TaskContext") as mock_ctx_cls:
            mock_ctx_cls.get = AsyncMock(return_value=mock_ctx)
            mock_task = MagicMock()
            result = await _cleanup_expired_tokens_async(mock_task)

        assert result["refresh_index_cleaned"] == 0
        assert result["orphan_2fa"] == 0
        assert result["soft_deleted_users_purged"] == 0

    @pytest.mark.anyio
    async def test_deleted_user_tokens_cleaned(self, mock_ctx):
        """soft-deleted 사용자 토큰 키 삭제 확인."""
        from tasks.cleanup import _cleanup_expired_tokens_async

        uid = str(uuid4())
        client_ids = {"client-1", "client-2"}

        result_mock = MagicMock()
        result_mock.all.return_value = [(uid,)]
        mock_ctx.create_session.return_value.__aenter__.return_value.execute = AsyncMock(
            return_value=result_mock
        )
        mock_ctx.redis.smembers = AsyncMock(return_value=client_ids)
        mock_ctx.redis.scan_iter = MagicMock(return_value=aiter([]))

        with patch("tasks.cleanup.TaskContext") as mock_ctx_cls:
            mock_ctx_cls.get = AsyncMock(return_value=mock_ctx)
            mock_task = MagicMock()
            result = await _cleanup_expired_tokens_async(mock_task)

        # client_ids 2개 + idx_key 1개 = 3개 삭제
        assert result["refresh_index_cleaned"] == 3
        assert result["soft_deleted_users_purged"] == 1

    @pytest.mark.anyio
    async def test_deleted_user_no_tokens_skips_delete(self, mock_ctx):
        """토큰 없는 사용자는 Redis delete 호출 안 함."""
        from tasks.cleanup import _cleanup_expired_tokens_async

        uid = str(uuid4())

        result_mock = MagicMock()
        result_mock.all.return_value = [(uid,)]
        mock_ctx.create_session.return_value.__aenter__.return_value.execute = AsyncMock(
            return_value=result_mock
        )
        mock_ctx.redis.smembers = AsyncMock(return_value=set())  # 빈 set
        mock_ctx.redis.scan_iter = MagicMock(return_value=aiter([]))

        with patch("tasks.cleanup.TaskContext") as mock_ctx_cls:
            mock_ctx_cls.get = AsyncMock(return_value=mock_ctx)
            mock_task = MagicMock()
            result = await _cleanup_expired_tokens_async(mock_task)

        assert result["refresh_index_cleaned"] == 0
        mock_ctx.redis.delete.assert_not_called()


class TestOrphan2FACleanup:
    """고아 2FA 키 정리 검증."""

    @pytest.mark.anyio
    async def test_orphan_keys_without_ttl_deleted(self, mock_ctx):
        """TTL -1인 2FA pending 키 삭제."""
        from tasks.cleanup import _cleanup_expired_tokens_async

        orphan_key = "auth:2fa_pending:user-1:temp-1"

        result_mock = MagicMock()
        result_mock.all.return_value = []
        mock_ctx.create_session.return_value.__aenter__.return_value.execute = AsyncMock(
            return_value=result_mock
        )
        mock_ctx.redis.scan_iter = MagicMock(return_value=aiter([orphan_key]))
        mock_ctx.redis.ttl = AsyncMock(return_value=-1)  # TTL 없음 = 고아

        with patch("tasks.cleanup.TaskContext") as mock_ctx_cls:
            mock_ctx_cls.get = AsyncMock(return_value=mock_ctx)
            mock_task = MagicMock()
            result = await _cleanup_expired_tokens_async(mock_task)

        assert result["orphan_2fa"] == 1
        mock_ctx.redis.delete.assert_called_with(orphan_key)

    @pytest.mark.anyio
    async def test_keys_with_ttl_not_deleted(self, mock_ctx):
        """TTL 있는 키는 유지."""
        from tasks.cleanup import _cleanup_expired_tokens_async

        key_with_ttl = "auth:2fa_pending:user-1:temp-2"

        result_mock = MagicMock()
        result_mock.all.return_value = []
        mock_ctx.create_session.return_value.__aenter__.return_value.execute = AsyncMock(
            return_value=result_mock
        )
        mock_ctx.redis.scan_iter = MagicMock(return_value=aiter([key_with_ttl]))
        mock_ctx.redis.ttl = AsyncMock(return_value=300)  # TTL 있음

        with patch("tasks.cleanup.TaskContext") as mock_ctx_cls:
            mock_ctx_cls.get = AsyncMock(return_value=mock_ctx)
            mock_task = MagicMock()
            result = await _cleanup_expired_tokens_async(mock_task)

        assert result["orphan_2fa"] == 0


class TestTaskMetadata:
    """태스크 메타데이터 검증."""

    def test_task_name(self):
        from tasks.cleanup import cleanup_expired_tokens
        assert cleanup_expired_tokens.name == "tasks.cleanup.cleanup_expired_tokens"

    def test_task_queue(self):
        from tasks.cleanup import cleanup_expired_tokens
        assert cleanup_expired_tokens.queue == "default"

    def test_task_max_retries(self):
        from tasks.cleanup import cleanup_expired_tokens
        assert cleanup_expired_tokens.max_retries == 1

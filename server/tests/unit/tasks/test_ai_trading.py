"""AI 매매 태스크 단위 테스트."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4


@pytest.fixture(autouse=True)
def reset_task_context():
    """각 테스트 전 TaskContext 싱글턴 초기화."""
    import tasks.context as ctx_module
    ctx_module._task_context = None
    yield
    ctx_module._task_context = None


@pytest.fixture
def mock_ctx():
    ctx = MagicMock()
    ctx.redis = AsyncMock()
    ctx.motor_db = MagicMock()
    ctx.create_session.return_value = AsyncMock(
        __aenter__=AsyncMock(return_value=AsyncMock()),
        __aexit__=AsyncMock(return_value=False),
    )
    return ctx


class TestMasterSwitch:
    """마스터 스위치 체크 검증."""

    @pytest.mark.anyio
    async def test_master_switch_off_returns_skipped(self):
        """AI_TRADING_ENABLED=False 시 즉시 반환 (context 초기화 전)."""
        from tasks.ai_trading import _run_all_active_configs_async

        with patch("tasks.ai_trading.settings") as mock_settings:
            mock_settings.AI_TRADING_ENABLED = False
            mock_task = MagicMock()
            result = await _run_all_active_configs_async(mock_task)

        assert result["status"] == "skipped"
        assert result["reason"] == "master_switch_off"
        assert result["dispatched"] == 0

    @pytest.mark.anyio
    async def test_kill_switch_returns_skipped(self, mock_ctx):
        """Redis kill switch 존재 시 즉시 반환."""
        from tasks.ai_trading import _run_all_active_configs_async

        mock_ctx.redis.get.return_value = "emergency_stop"
        mock_ctx.redis.set.return_value = True

        with patch("tasks.ai_trading.settings") as mock_settings, \
             patch("tasks.ai_trading.TaskContext") as mock_ctx_cls:
            mock_settings.AI_TRADING_ENABLED = True
            mock_ctx_cls.get = AsyncMock(return_value=mock_ctx)
            mock_task = MagicMock()
            result = await _run_all_active_configs_async(mock_task)

        assert result["status"] == "skipped"
        assert result["reason"] == "kill_switch"

    @pytest.mark.anyio
    async def test_cycle_lock_held_returns_skipped(self, mock_ctx):
        """Cycle Lock 미획득 시 스킵."""
        from tasks.ai_trading import _run_all_active_configs_async

        mock_ctx.redis.get.return_value = None      # kill switch 없음
        mock_ctx.redis.set.return_value = None       # lock 획득 실패

        with patch("tasks.ai_trading.settings") as mock_settings, \
             patch("tasks.ai_trading.TaskContext") as mock_ctx_cls:
            mock_settings.AI_TRADING_ENABLED = True
            mock_ctx_cls.get = AsyncMock(return_value=mock_ctx)
            mock_task = MagicMock()
            result = await _run_all_active_configs_async(mock_task)

        assert result["status"] == "skipped"
        assert result["reason"] == "lock_held"


class TestCycleLock:
    """Cycle Lock 획득/해제 검증."""

    @pytest.mark.anyio
    async def test_lock_released_after_execution(self, mock_ctx):
        """정상 실행 후 lock 해제 확인."""
        from tasks.ai_trading import _run_all_active_configs_async

        mock_ctx.redis.get.return_value = None
        mock_ctx.redis.set.return_value = True       # lock 획득 성공

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_result = MagicMock()
        mock_result.scalars.return_value.unique.return_value.all.return_value = []
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_ctx.create_session.return_value = mock_session

        with patch("tasks.ai_trading.settings") as mock_settings, \
             patch("tasks.ai_trading.TaskContext") as mock_ctx_cls:
            mock_settings.AI_TRADING_ENABLED = True
            mock_ctx_cls.get = AsyncMock(return_value=mock_ctx)
            mock_task = MagicMock()
            mock_task.request.id = "test-task-id"
            await _run_all_active_configs_async(mock_task)

        # lock 해제 확인
        mock_ctx.redis.delete.assert_called_once_with("celery:lock:ai_trading_cycle")

    @pytest.mark.anyio
    async def test_lock_released_on_exception(self, mock_ctx):
        """예외 발생 시에도 lock 해제 (finally 블록)."""
        from tasks.ai_trading import _run_all_active_configs_async

        mock_ctx.redis.get.return_value = None
        mock_ctx.redis.set.return_value = True

        # create_session에서 예외 발생
        mock_ctx.create_session.side_effect = RuntimeError("DB error")

        with patch("tasks.ai_trading.settings") as mock_settings, \
             patch("tasks.ai_trading.TaskContext") as mock_ctx_cls:
            mock_settings.AI_TRADING_ENABLED = True
            mock_ctx_cls.get = AsyncMock(return_value=mock_ctx)
            mock_task = MagicMock()
            mock_task.request.id = "test-task-id"
            with pytest.raises(RuntimeError):
                await _run_all_active_configs_async(mock_task)

        # 예외에도 lock 해제
        mock_ctx.redis.delete.assert_called_with("celery:lock:ai_trading_cycle")


class TestConfigLock:
    """Config Lock 획득/해제 검증."""

    @pytest.mark.anyio
    async def test_config_lock_not_acquired_returns_skipped(self, mock_ctx):
        """Config Lock 미획득 시 duplicate_lock 반환."""
        from tasks.ai_trading import _run_single_config_async

        config_id = str(uuid4())
        mock_ctx.redis.set.return_value = None  # lock 미획득

        with patch("tasks.ai_trading.TaskContext") as mock_ctx_cls:
            mock_ctx_cls.get = AsyncMock(return_value=mock_ctx)
            mock_task = MagicMock()
            mock_task.request.id = "test-id"
            result = await _run_single_config_async(mock_task, config_id)

        assert result["status"] == "skipped"
        assert result["skipped_reason"] == "duplicate_lock"

    @pytest.mark.anyio
    async def test_config_lock_released_after_execution(self, mock_ctx):
        """Config Lock은 항상 finally에서 해제."""
        from tasks.ai_trading import _run_single_config_async

        config_id = str(uuid4())
        mock_ctx.redis.set.return_value = True  # lock 획득

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        # config 없음 처리
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_ctx.create_session.return_value = mock_session

        with patch("tasks.ai_trading.TaskContext") as mock_ctx_cls:
            mock_ctx_cls.get = AsyncMock(return_value=mock_ctx)
            mock_task = MagicMock()
            mock_task.request.id = "test-id"
            await _run_single_config_async(mock_task, config_id)

        expected_lock = f"celery:lock:ai_trading:{config_id}"
        mock_ctx.redis.delete.assert_called_with(expected_lock)


class TestConfigNotFound:
    """Config 없음/비활성 처리."""

    @pytest.mark.anyio
    async def test_config_not_found_returns_skipped(self, mock_ctx):
        """Config 없으면 skipped 반환."""
        from tasks.ai_trading import _run_single_config_async

        config_id = str(uuid4())
        mock_ctx.redis.set.return_value = True

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_ctx.create_session.return_value = mock_session

        with patch("tasks.ai_trading.TaskContext") as mock_ctx_cls:
            mock_ctx_cls.get = AsyncMock(return_value=mock_ctx)
            mock_task = MagicMock()
            mock_task.request.id = "test-id"
            result = await _run_single_config_async(mock_task, config_id)

        assert result["status"] == "skipped"
        assert result["skipped_reason"] == "config_not_found_or_disabled"

    @pytest.mark.anyio
    async def test_disabled_config_returns_skipped(self, mock_ctx):
        """is_enabled=False config 스킵."""
        from tasks.ai_trading import _run_single_config_async

        config_id = str(uuid4())
        mock_ctx.redis.set.return_value = True

        mock_config = MagicMock()
        mock_config.is_enabled = False

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_config
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_ctx.create_session.return_value = mock_session

        with patch("tasks.ai_trading.TaskContext") as mock_ctx_cls:
            mock_ctx_cls.get = AsyncMock(return_value=mock_ctx)
            mock_task = MagicMock()
            mock_task.request.id = "test-id"
            result = await _run_single_config_async(mock_task, config_id)

        assert result["status"] == "skipped"


class TestBacktestStub:
    """run_backtest 스텁 검증."""

    def test_backtest_returns_not_implemented(self):
        """backtest는 M9 스텁이므로 not_implemented 반환."""
        from tasks.ai_trading import run_backtest

        config_id = str(uuid4())
        # Celery eager mode로 직접 실행
        result = run_backtest.run(config_id, "2024-01-01", "2024-01-31")

        assert result["status"] == "not_implemented"
        assert result["config_id"] == config_id
        assert result["period"]["start"] == "2024-01-01"
        assert result["period"]["end"] == "2024-01-31"
        assert "M9" in result["message"]

    def test_backtest_task_name(self):
        """태스크 이름 확인."""
        from tasks.ai_trading import run_backtest
        assert run_backtest.name == "tasks.ai_trading.run_backtest"

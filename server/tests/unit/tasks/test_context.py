"""TaskContext 단위 테스트."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from tasks.context import TaskContext


@pytest.fixture(autouse=True)
def reset_singleton():
    """각 테스트 전 TaskContext 싱글턴 초기화."""
    import tasks.context as ctx_module
    ctx_module._task_context = None
    yield
    ctx_module._task_context = None


@pytest.fixture
def mock_engine():
    engine = MagicMock()
    return engine


@pytest.fixture
def mock_redis():
    return AsyncMock()


@pytest.fixture
def mock_motor_db():
    return MagicMock()


@pytest.fixture
def task_context(mock_redis, mock_engine, mock_motor_db):
    return TaskContext(redis=mock_redis, engine=mock_engine, motor_db=mock_motor_db)


class TestTaskContextSingleton:
    """TaskContext 싱글턴 패턴 검증."""

    @pytest.mark.anyio
    async def test_get_initializes_on_first_call(self, task_context):
        """첫 호출 시 초기화 수행."""
        with patch.object(TaskContext, "initialize", new_callable=AsyncMock, return_value=task_context):
            ctx = await TaskContext.get()
            assert ctx is task_context

    @pytest.mark.anyio
    async def test_get_returns_same_instance(self, task_context):
        """두 번째 호출은 동일 인스턴스 반환."""
        with patch.object(TaskContext, "initialize", new_callable=AsyncMock, return_value=task_context):
            ctx1 = await TaskContext.get()
            ctx2 = await TaskContext.get()
            assert ctx1 is ctx2
            # initialize는 1회만 호출
            TaskContext.initialize.assert_awaited_once()

    @pytest.mark.anyio
    async def test_get_calls_initialize_once(self, task_context):
        """싱글턴이 없을 때만 initialize 호출."""
        call_count = 0

        async def _mock_init():
            nonlocal call_count
            call_count += 1
            return task_context

        with patch.object(TaskContext, "initialize", side_effect=_mock_init):
            await TaskContext.get()
            await TaskContext.get()
            await TaskContext.get()

        assert call_count == 1


class TestTaskContextSession:
    """create_session 검증."""

    def test_create_session_returns_async_session(self, task_context):
        """create_session이 AsyncSession 반환."""
        from sqlalchemy.ext.asyncio import AsyncSession
        session = task_context.create_session()
        assert hasattr(session, "__aenter__")  # async context manager
        assert hasattr(session, "__aexit__")

    def test_create_session_creates_new_each_time(self, task_context):
        """매 호출마다 새 세션 반환."""
        s1 = task_context.create_session()
        s2 = task_context.create_session()
        assert s1 is not s2

    @pytest.mark.anyio
    async def test_create_session_as_context_manager(self, task_context):
        """AsyncSession을 async with로 사용 가능."""
        # create_session()은 AsyncSession을 반환해야 하므로
        # close() 가능한 인터페이스 확인
        session = task_context.create_session()
        assert callable(getattr(session, "close", None))


class TestTaskContextResources:
    """리소스 필드 접근 검증."""

    def test_redis_field_accessible(self, task_context, mock_redis):
        assert task_context.redis is mock_redis

    def test_engine_field_accessible(self, task_context, mock_engine):
        assert task_context.engine is mock_engine

    def test_motor_db_field_accessible(self, task_context, mock_motor_db):
        assert task_context.motor_db is mock_motor_db

"""PnL 리포트 태스크 단위 테스트."""
from __future__ import annotations

import pytest
from datetime import date, datetime, UTC, timedelta
from decimal import Decimal
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
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    ctx.create_session.return_value = session
    return ctx


class TestReportDateCalculation:
    """리포트 날짜 계산 검증."""

    @pytest.mark.anyio
    async def test_none_date_uses_yesterday(self, mock_ctx):
        """report_date=None이면 어제 날짜 사용."""
        from tasks.reports import _generate_daily_pnl_reports_async

        # 사용자 없음 처리
        result_mock = MagicMock()
        result_mock.all.return_value = []
        mock_ctx.create_session.return_value.__aenter__.return_value.execute = AsyncMock(
            return_value=result_mock
        )

        with patch("tasks.reports.TaskContext") as mock_ctx_cls:
            mock_ctx_cls.get = AsyncMock(return_value=mock_ctx)
            mock_task = MagicMock()
            result = await _generate_daily_pnl_reports_async(mock_task, None)

        yesterday = (datetime.now(UTC) - timedelta(days=1)).date()
        assert result["report_date"] == str(yesterday)
        assert result["users_processed"] == 0
        assert result["reports_created"] == 0

    @pytest.mark.anyio
    async def test_explicit_date_used(self, mock_ctx):
        """명시적 날짜 사용."""
        from tasks.reports import _generate_daily_pnl_reports_async

        result_mock = MagicMock()
        result_mock.all.return_value = []
        mock_ctx.create_session.return_value.__aenter__.return_value.execute = AsyncMock(
            return_value=result_mock
        )

        with patch("tasks.reports.TaskContext") as mock_ctx_cls:
            mock_ctx_cls.get = AsyncMock(return_value=mock_ctx)
            mock_task = MagicMock()
            result = await _generate_daily_pnl_reports_async(mock_task, "2024-03-15")

        assert result["report_date"] == "2024-03-15"


class TestReportGeneration:
    """리포트 생성 로직 검증."""

    @pytest.mark.anyio
    async def test_no_active_users_returns_zero(self, mock_ctx):
        """활성 사용자 없으면 0건 반환."""
        from tasks.reports import _generate_daily_pnl_reports_async

        result_mock = MagicMock()
        result_mock.all.return_value = []
        mock_ctx.create_session.return_value.__aenter__.return_value.execute = AsyncMock(
            return_value=result_mock
        )

        with patch("tasks.reports.TaskContext") as mock_ctx_cls:
            mock_ctx_cls.get = AsyncMock(return_value=mock_ctx)
            mock_task = MagicMock()
            result = await _generate_daily_pnl_reports_async(mock_task, "2024-01-01")

        assert result["users_processed"] == 0
        assert result["reports_created"] == 0

    def test_task_name(self):
        from tasks.reports import generate_daily_pnl_reports
        assert generate_daily_pnl_reports.name == "tasks.reports.generate_daily_pnl_reports"

    def test_task_queue(self):
        from tasks.reports import generate_daily_pnl_reports
        assert generate_daily_pnl_reports.queue == "default"

    def test_task_max_retries(self):
        from tasks.reports import generate_daily_pnl_reports
        assert generate_daily_pnl_reports.max_retries == 2


class TestReportIdempotency:
    """멱등성 검증 (upsert)."""

    @pytest.mark.anyio
    async def test_user_report_failure_does_not_stop_others(self, mock_ctx):
        """한 사용자 실패해도 다른 사용자 처리 계속."""
        from tasks.reports import _generate_daily_pnl_reports_async

        user1 = uuid4()
        user2 = uuid4()

        result_mock = MagicMock()
        result_mock.all.return_value = [(user1,), (user2,)]
        mock_ctx.create_session.return_value.__aenter__.return_value.execute = AsyncMock(
            return_value=result_mock
        )

        call_count = 0

        async def mock_generate_single(ctx, uid, *args):
            nonlocal call_count
            call_count += 1
            if uid == user1:
                raise RuntimeError("DB error")

        with patch("tasks.reports.TaskContext") as mock_ctx_cls, \
             patch("tasks.reports._generate_single_user_report", side_effect=mock_generate_single):
            mock_ctx_cls.get = AsyncMock(return_value=mock_ctx)
            mock_task = MagicMock()
            result = await _generate_daily_pnl_reports_async(mock_task, "2024-01-01")

        # 2명 처리 시도, 1명만 성공
        assert result["users_processed"] == 2
        assert result["reports_created"] == 1
        assert call_count == 2

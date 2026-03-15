"""RiskManager 단위 테스트 — 8건.

쿨다운 / 일일 손실 / MDD / 포지션 수 각 차단 + 경계값 + 전체 통과.
순수 계산이므로 외부 의존성 없음.
"""
from __future__ import annotations

import pytest

from app.trading.execution.risk_manager import RiskManager

from .conftest import future_iso, make_drawdown_state, make_risk_params, past_iso


@pytest.fixture
def rm() -> RiskManager:
    return RiskManager()


class TestCooldown:
    def test_active_cooldown_blocks_trade(self, rm: RiskManager):
        """쿨다운 활성 상태에서 거래 차단."""
        state = make_drawdown_state(
            is_suspended=True,
            cooldown_until=future_iso(3600),
        )
        result = rm.check(state, make_risk_params(), active_position_count=0)
        assert result["allowed"] is False
        assert "쿨다운" in result["reason"]

    def test_expired_cooldown_passes(self, rm: RiskManager):
        """만료된 쿨다운은 거래 허용."""
        state = make_drawdown_state(
            is_suspended=True,
            cooldown_until=past_iso(60),  # 1분 전 만료
        )
        result = rm.check(state, make_risk_params(), active_position_count=0)
        assert result["allowed"] is True

    def test_suspended_without_cooldown_until_passes(self, rm: RiskManager):
        """is_suspended=True지만 cooldown_until=None이면 차단 안 함 (쿨다운 만료 처리)."""
        state = make_drawdown_state(is_suspended=True, cooldown_until=None)
        result = rm.check(state, make_risk_params(), active_position_count=0)
        assert result["allowed"] is True


class TestDailyLoss:
    def test_daily_loss_at_limit_blocks(self, rm: RiskManager):
        """일일 손실이 한도에 정확히 도달하면 차단."""
        state = make_drawdown_state(daily_loss_ratio=0.05)
        result = rm.check(state, make_risk_params(daily_max_loss_ratio=0.05), 0)
        assert result["allowed"] is False
        assert "일일 손실" in result["reason"]

    def test_daily_loss_below_limit_passes(self, rm: RiskManager):
        """일일 손실이 한도 미만이면 통과."""
        state = make_drawdown_state(daily_loss_ratio=0.049)
        result = rm.check(state, make_risk_params(daily_max_loss_ratio=0.05), 0)
        assert result["allowed"] is True


class TestMDD:
    def test_mdd_at_limit_blocks(self, rm: RiskManager):
        """MDD가 한도에 도달하면 차단."""
        state = make_drawdown_state(mdd_ratio=0.15)
        result = rm.check(state, make_risk_params(mdd_limit_ratio=0.15), 0)
        assert result["allowed"] is False
        assert "MDD" in result["reason"]

    def test_mdd_below_limit_passes(self, rm: RiskManager):
        """MDD가 한도 미만이면 통과."""
        state = make_drawdown_state(mdd_ratio=0.149)
        result = rm.check(state, make_risk_params(mdd_limit_ratio=0.15), 0)
        assert result["allowed"] is True


class TestPositionLimit:
    def test_max_positions_reached_blocks(self, rm: RiskManager):
        """최대 포지션 수 도달 시 차단."""
        state = make_drawdown_state()
        result = rm.check(state, make_risk_params(max_active_positions=3), 3)
        assert result["allowed"] is False
        assert "포지션" in result["reason"]

    def test_below_max_positions_passes(self, rm: RiskManager):
        """포지션 수 여유 있으면 통과."""
        state = make_drawdown_state()
        result = rm.check(state, make_risk_params(max_active_positions=3), 2)
        assert result["allowed"] is True


class TestAllClear:
    def test_all_clear_returns_ok(self, rm: RiskManager):
        """모든 조건 이상 없으면 allowed=True, reason='OK'."""
        state = make_drawdown_state()
        result = rm.check(state, make_risk_params(), 0)
        assert result["allowed"] is True
        assert result["reason"] == "OK"
        assert result["daily_loss_ratio"] == 0.0
        assert result["mdd_ratio"] == 0.0
        assert result["consecutive_losses"] == 0
        assert result["active_position_count"] == 0

    def test_result_carries_state_metrics(self, rm: RiskManager):
        """결과에 현재 상태 지표가 올바르게 포함된다."""
        state = make_drawdown_state(
            daily_loss_ratio=0.02,
            mdd_ratio=0.05,
            consecutive_losses=1,
        )
        result = rm.check(state, make_risk_params(), active_position_count=2)
        assert result["daily_loss_ratio"] == 0.02
        assert result["mdd_ratio"] == 0.05
        assert result["consecutive_losses"] == 1
        assert result["active_position_count"] == 2

    def test_check_order_cooldown_before_daily(self, rm: RiskManager):
        """검증 순서: 쿨다운이 일일 손실보다 먼저 체크된다."""
        state = make_drawdown_state(
            is_suspended=True,
            cooldown_until=future_iso(),
            daily_loss_ratio=0.10,  # 일일 손실 한도도 초과
        )
        result = rm.check(state, make_risk_params(daily_max_loss_ratio=0.05), 0)
        assert "쿨다운" in result["reason"]  # 쿨다운이 먼저 걸려야 함

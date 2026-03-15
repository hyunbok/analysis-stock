"""DynamicStopLoss 단위 테스트 — 12건.

SL/TP 계산, Trailing Stop 초기화/활성화/업데이트/청산 판단.
순수 계산이므로 외부 의존성 없음.
"""
from __future__ import annotations

import pytest

from app.trading.execution.sl_tp import DynamicStopLoss


ENTRY = 100_000.0
SL = 98_000.0       # 2% 손절
TP = 104_000.0      # 4% 익절
ATR = 1_000.0       # ATR = 1000원


class TestCalculate:
    def test_sell_sl_above_entry_tp_below_entry(self):
        """SELL 포지션: SL > entry, TP < entry."""
        entry = 100_000.0
        sl = 102_000.0      # entry 위 (손절)
        tp = 96_000.0       # entry 아래 (익절)
        result = DynamicStopLoss.calculate(entry, sl, tp, ATR, 2.0, 4.0)
        assert result["stop_loss_price"] == sl
        assert result["take_profit_price"] == tp
        # trailing trigger = entry + (tp - entry) × 0.5 = 100k + (-4k × 0.5) = 98k
        expected_trigger = entry + (tp - entry) * 0.5
        assert abs(result["trailing_trigger_price"] - expected_trigger) < 0.01

    def test_basic_sl_tp_params(self):
        """SL/TP 그대로 StopLossParams에 반영."""
        result = DynamicStopLoss.calculate(
            entry_price=ENTRY,
            stop_loss_price=SL,
            take_profit_price=TP,
            atr=ATR,
            stop_loss_atr_mult=2.0,
            take_profit_atr_mult=4.0,
        )
        assert result["stop_loss_price"] == SL
        assert result["take_profit_price"] == TP
        assert result["stop_loss_atr_mult"] == 2.0
        assert result["take_profit_atr_mult"] == 4.0

    def test_trailing_trigger_at_50_percent_of_tp_distance(self):
        """Trailing trigger = entry + (TP - entry) × 50%."""
        result = DynamicStopLoss.calculate(ENTRY, SL, TP, ATR, 2.0, 4.0)
        expected_trigger = ENTRY + (TP - ENTRY) * 0.5  # 102,000
        assert abs(result["trailing_trigger_price"] - expected_trigger) < 0.01

    def test_trailing_stop_distance_is_atr_times_1(self):
        """Trailing stop 거리 = ATR × 1.0."""
        result = DynamicStopLoss.calculate(ENTRY, SL, TP, ATR, 2.0, 4.0)
        assert abs(result["trailing_stop_distance"] - ATR * 1.0) < 0.01


class TestInitTrailingState:
    def test_initial_state_not_active(self):
        """초기 상태: is_active=False, peak=entry, stop=sl."""
        sl_params = DynamicStopLoss.calculate(ENTRY, SL, TP, ATR, 2.0, 4.0)
        state = DynamicStopLoss.init_trailing_state(ENTRY, sl_params)

        assert state["is_active"] is False
        assert state["peak_price"] == ENTRY
        assert state["current_stop"] == SL
        assert state["activation_threshold"] == sl_params["trailing_trigger_price"]


class TestUpdateTrailingStop:
    def test_activates_when_price_reaches_threshold(self):
        """가격이 activation_threshold에 도달하면 is_active=True."""
        sl_params = DynamicStopLoss.calculate(ENTRY, SL, TP, ATR, 2.0, 4.0)
        state = DynamicStopLoss.init_trailing_state(ENTRY, sl_params)
        trigger = sl_params["trailing_trigger_price"]  # 102,000

        updated = DynamicStopLoss.update_trailing_stop(state, trigger, ATR)
        assert updated["is_active"] is True

    def test_not_activated_below_threshold(self):
        """임계값 미달 시 비활성."""
        sl_params = DynamicStopLoss.calculate(ENTRY, SL, TP, ATR, 2.0, 4.0)
        state = DynamicStopLoss.init_trailing_state(ENTRY, sl_params)
        trigger = sl_params["trailing_trigger_price"]

        updated = DynamicStopLoss.update_trailing_stop(state, trigger - 1, ATR)
        assert updated["is_active"] is False

    def test_peak_price_updates_on_new_high(self):
        """활성화 후 신고가 경신 시 peak_price 갱신."""
        sl_params = DynamicStopLoss.calculate(ENTRY, SL, TP, ATR, 2.0, 4.0)
        state = DynamicStopLoss.init_trailing_state(ENTRY, sl_params)
        trigger = sl_params["trailing_trigger_price"]

        # 활성화
        state = DynamicStopLoss.update_trailing_stop(state, trigger, ATR)
        # 신고가 갱신
        state = DynamicStopLoss.update_trailing_stop(state, 103_500.0, ATR)
        assert state["peak_price"] == 103_500.0
        assert abs(state["current_stop"] - (103_500.0 - ATR)) < 0.01

    def test_current_stop_updated_to_peak_minus_atr(self):
        """current_stop = peak_price - ATR × 1.0."""
        sl_params = DynamicStopLoss.calculate(ENTRY, SL, TP, ATR, 2.0, 4.0)
        state = DynamicStopLoss.init_trailing_state(ENTRY, sl_params)
        trigger = sl_params["trailing_trigger_price"]

        state = DynamicStopLoss.update_trailing_stop(state, trigger, ATR)
        assert abs(state["current_stop"] - (trigger - ATR * 1.0)) < 0.01


class TestShouldExit:
    def test_stop_loss_triggered(self):
        """가격이 SL 이하 → stop_loss."""
        state = DynamicStopLoss.init_trailing_state(
            ENTRY,
            DynamicStopLoss.calculate(ENTRY, SL, TP, ATR, 2.0, 4.0),
        )
        should_exit, reason = DynamicStopLoss.should_exit(state, SL - 1, SL, TP)
        assert should_exit is True
        assert reason == "stop_loss"

    def test_take_profit_triggered(self):
        """가격이 TP 이상 → take_profit."""
        state = DynamicStopLoss.init_trailing_state(
            ENTRY,
            DynamicStopLoss.calculate(ENTRY, SL, TP, ATR, 2.0, 4.0),
        )
        should_exit, reason = DynamicStopLoss.should_exit(state, TP + 1, SL, TP)
        assert should_exit is True
        assert reason == "take_profit"

    def test_trailing_stop_triggered_when_active(self):
        """Trailing Stop 활성화 후 current_stop 이하 → trailing_stop."""
        sl_params = DynamicStopLoss.calculate(ENTRY, SL, TP, ATR, 2.0, 4.0)
        state = DynamicStopLoss.init_trailing_state(ENTRY, sl_params)
        trigger = sl_params["trailing_trigger_price"]

        # 활성화 + peak 갱신
        state = DynamicStopLoss.update_trailing_stop(state, trigger + 1000, ATR)
        current_stop = state["current_stop"]  # peak - ATR

        should_exit, reason = DynamicStopLoss.should_exit(state, current_stop - 1, SL, TP)
        assert should_exit is True
        assert reason == "trailing_stop"

    def test_no_exit_in_normal_range(self):
        """정상 가격 범위에서는 청산 없음."""
        state = DynamicStopLoss.init_trailing_state(
            ENTRY,
            DynamicStopLoss.calculate(ENTRY, SL, TP, ATR, 2.0, 4.0),
        )
        should_exit, reason = DynamicStopLoss.should_exit(state, ENTRY + 1000, SL, TP)
        assert should_exit is False
        assert reason == ""

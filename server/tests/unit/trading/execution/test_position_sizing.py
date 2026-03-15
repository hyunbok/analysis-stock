"""PositionSizer 단위 테스트 — 11건.

FixedFractionalSizer + HalfKellySizer: 투자금 계산, 캡, 신호 강도, position_scale.
순수 계산이므로 외부 의존성 없음.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.trading.execution.position_sizing import FixedFractionalSizer, HalfKellySizer

from .conftest import make_exit_params, make_risk_params, make_trading_signal

# 테스트 기준값
CAPITAL = Decimal("10_000_000")       # 1000만원
BALANCE = Decimal("10_000_000")
ENTRY = 100_000_000.0                 # BTC 1억원
STOP = 97_000_000.0                   # 3% 손절


class TestFixedFractionalSizer:
    def test_basic_calculation(self):
        """FF 기본 투자금 계산.

        risk_amount = 1000만 × 0.02 = 20만
        stop_loss_pct = (100M - 97M) / 100M = 0.03
        investment = 20만 / 0.03 = 약 666.7만
        × 1.0(strong) × 1.0(scale) → 666.7만
        max_cap = 1000만 × 0.10 = 100만 → min(666.7만, 100만) = 100만
        """
        signal = make_trading_signal(strength="strong", position_scale=1.0)
        result = FixedFractionalSizer.calculate(CAPITAL, BALANCE, signal, make_risk_params())
        assert result["method"] == "fixed_fractional"
        assert result["investment_amount"] == CAPITAL * Decimal("0.10")  # 캡 적용
        assert result["kelly_fraction"] is None

    def test_strong_signal_multiplier(self):
        """strong 신호 배수 = 1.0 (최대)."""
        signal = make_trading_signal(strength="strong", position_scale=1.0)
        result = FixedFractionalSizer.calculate(CAPITAL, BALANCE, signal, make_risk_params())
        assert result["strength_multiplier"] == 1.0

    def test_moderate_signal_multiplier(self):
        """moderate 신호 배수 = 0.75."""
        signal = make_trading_signal(strength="moderate", position_scale=1.0)
        result = FixedFractionalSizer.calculate(CAPITAL, BALANCE, signal, make_risk_params())
        assert result["strength_multiplier"] == 0.75

    def test_weak_signal_multiplier(self):
        """weak 신호 배수 = 0.5 (최소)."""
        signal = make_trading_signal(strength="weak", position_scale=1.0)
        result = FixedFractionalSizer.calculate(CAPITAL, BALANCE, signal, make_risk_params())
        assert result["strength_multiplier"] == 0.5

    def test_position_scale_half(self):
        """position_scale=0.5 적용 시 투자금 절반."""
        signal_full = make_trading_signal(strength="strong", position_scale=1.0)
        signal_half = make_trading_signal(strength="strong", position_scale=0.5)

        result_full = FixedFractionalSizer.calculate(CAPITAL, BALANCE, signal_full, make_risk_params())
        result_half = FixedFractionalSizer.calculate(CAPITAL, BALANCE, signal_half, make_risk_params())

        # 캡 미적용 케이스에서 검증: 높은 stop_loss_ratio 사용
        params = make_risk_params(stop_loss_ratio=0.001, max_investment_ratio=1.0)
        r_full = FixedFractionalSizer.calculate(CAPITAL, BALANCE, signal_full, params)
        r_half = FixedFractionalSizer.calculate(CAPITAL, BALANCE, signal_half, params)
        # half가 full의 절반이어야 함
        assert abs(float(r_half["investment_amount"]) - float(r_full["investment_amount"]) * 0.5) < 0.01

    def test_caps_at_max_investment_ratio(self):
        """투자금이 총자산 × max_investment_ratio를 초과하면 캡 적용."""
        signal = make_trading_signal(strength="strong", position_scale=1.0)
        params = make_risk_params(max_investment_ratio=0.05)  # 5% 캡
        result = FixedFractionalSizer.calculate(CAPITAL, BALANCE, signal, params)
        max_cap = CAPITAL * Decimal("0.05")
        assert result["investment_amount"] <= max_cap

    def test_quantity_calculated_from_investment_and_entry_price(self):
        """quantity = investment_amount / entry_price."""
        signal = make_trading_signal(strength="strong", position_scale=1.0)
        params = make_risk_params(max_investment_ratio=0.10)
        result = FixedFractionalSizer.calculate(CAPITAL, BALANCE, signal, params)
        expected_qty = result["investment_amount"] / Decimal(str(ENTRY))
        assert abs(float(result["quantity"] - expected_qty)) < 1e-10


class TestHalfKellySizer:
    def test_basic_kelly_calculation(self):
        """HK 기본 계산: W=0.5, R=1.5 → kelly = 0.5 - 0.5/1.5 = 0.1667 → half = 0.0833."""
        signal = make_trading_signal(strength="strong", position_scale=1.0)
        params = make_risk_params(win_rate_estimate=0.5, avg_rr_ratio=1.5, max_investment_ratio=1.0)
        result = HalfKellySizer.calculate(CAPITAL, BALANCE, signal, params)
        assert result["method"] == "half_kelly"
        # kelly = 0.5 - (1-0.5)/1.5 = 0.5 - 0.333 = 0.1667
        # half_kelly = 0.1667 × 0.5 = 0.0833
        expected_hk = (0.5 - (1.0 - 0.5) / 1.5) * 0.5
        assert abs(result["kelly_fraction"] - expected_hk) < 0.001

    def test_negative_kelly_becomes_zero(self):
        """음수 Kelly는 0으로 처리 (손실 기대값)."""
        signal = make_trading_signal(strength="strong", position_scale=1.0)
        params = make_risk_params(win_rate_estimate=0.2, avg_rr_ratio=1.0, max_investment_ratio=1.0)
        result = HalfKellySizer.calculate(CAPITAL, BALANCE, signal, params)
        # kelly = 0.2 - 0.8/1.0 = -0.6 → 음수 → 0
        assert result["kelly_fraction"] == 0.0
        assert result["investment_amount"] == Decimal("0")

    def test_caps_at_max_investment_ratio(self):
        """투자금이 캡을 초과하지 않는다."""
        signal = make_trading_signal(strength="strong", position_scale=1.0)
        params = make_risk_params(win_rate_estimate=0.9, avg_rr_ratio=5.0, max_investment_ratio=0.10)
        result = HalfKellySizer.calculate(CAPITAL, BALANCE, signal, params)
        max_cap = CAPITAL * Decimal("0.10")
        assert result["investment_amount"] <= max_cap


class TestSizerComparison:
    def test_ff_smaller_than_hk(self):
        """FF < HK인 경우 FF 선택 (보수적)."""
        signal = make_trading_signal(strength="strong", position_scale=1.0)
        # high win rate → HK 크게, FF는 stop_loss 2%로 제한
        params = make_risk_params(
            win_rate_estimate=0.9,
            avg_rr_ratio=5.0,
            stop_loss_ratio=0.002,  # 작은 리스크량 → FF 작아짐
            max_investment_ratio=1.0,
        )
        ff = FixedFractionalSizer.calculate(CAPITAL, BALANCE, signal, params)
        hk = HalfKellySizer.calculate(CAPITAL, BALANCE, signal, params)
        # engine.py에서 min 선택하므로 FF가 더 작으면 FF 선택
        assert ff["investment_amount"] < hk["investment_amount"]

    def test_hk_smaller_than_ff(self):
        """HK < FF인 경우 HK 선택 (보수적)."""
        signal = make_trading_signal(strength="strong", position_scale=1.0)
        # low win rate → HK 작아짐
        params = make_risk_params(
            win_rate_estimate=0.35,   # kelly≈음수 → 0
            avg_rr_ratio=1.5,
            stop_loss_ratio=0.02,
            max_investment_ratio=1.0,
        )
        hk = HalfKellySizer.calculate(CAPITAL, BALANCE, signal, params)
        ff = FixedFractionalSizer.calculate(CAPITAL, BALANCE, signal, params)
        assert hk["investment_amount"] <= ff["investment_amount"]

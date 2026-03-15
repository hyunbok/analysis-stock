"""포지션 사이징 — Fixed Fractional + Half-Kelly.

순수 계산 모듈 — 외부 의존성 없음.
두 개의 독립 클래스 — engine.py에서 둘 다 실행 후 보수적(작은) 결과 선택.
"""
from __future__ import annotations

import logging
from decimal import Decimal

from app.trading.strategy.types import TradingSignal

from .constants import KELLY_HALF_FACTOR, SIGNAL_MULTIPLIER
from .types import PositionSizeResult, RiskParams

logger = logging.getLogger(__name__)


class FixedFractionalSizer:
    """Fixed Fractional: 투자금 = (총자산 × 리스크비율) / 손절비율.

    1. risk_amount = total_capital × stop_loss_ratio
    2. stop_loss_pct = |entry_price - stop_loss_price| / entry_price
    3. investment = risk_amount / stop_loss_pct
    4. × SignalStrength 배수 × position_scale
    5. min(investment, total_capital × max_investment_ratio)
    """

    @staticmethod
    def calculate(
        total_capital: Decimal,
        available_balance: Decimal,
        signal: TradingSignal,
        params: RiskParams,
    ) -> PositionSizeResult:
        entry_price = signal["entry_price"]
        stop_loss_price = signal["exit_params"]["stop_loss"]
        strength = signal["strength"]
        position_scale = signal["position_scale"]

        strength_multiplier = SIGNAL_MULTIPLIER.get(strength, 0.5)

        # 손절 비율 (entry 대비)
        stop_loss_pct = abs(entry_price - stop_loss_price) / entry_price
        if stop_loss_pct <= 0:
            stop_loss_pct = params["stop_loss_ratio"]

        # 리스크 금액 기반 투자금 산출
        risk_amount = total_capital * Decimal(str(params["stop_loss_ratio"]))
        raw_investment = risk_amount / Decimal(str(stop_loss_pct))

        # 신호 강도 + 장세 스케일 적용
        investment = raw_investment * Decimal(str(strength_multiplier)) * Decimal(str(position_scale))

        # 최대 투자비율 캡
        max_investment = total_capital * Decimal(str(params["max_investment_ratio"]))
        investment = min(investment, max_investment)

        investment_ratio = float(investment / total_capital) if total_capital > 0 else 0.0
        quantity = investment / Decimal(str(entry_price)) if entry_price > 0 else Decimal("0")

        logger.debug(
            "FF sizer: investment=%s ratio=%.4f stop_pct=%.4f",
            investment, investment_ratio, stop_loss_pct,
        )

        return PositionSizeResult(
            method="fixed_fractional",
            quantity=quantity,
            investment_amount=investment,
            investment_ratio=investment_ratio,
            stop_loss_ratio=stop_loss_pct,
            kelly_fraction=None,
            strength_multiplier=strength_multiplier,
            position_scale=position_scale,
            detail=(
                f"FF: risk_amount={float(risk_amount):.0f} "
                f"stop_pct={stop_loss_pct:.4f} "
                f"×{strength_multiplier}(strength) ×{position_scale}(scale)"
            ),
        )


class HalfKellySizer:
    """Half-Kelly: Kelly% = W - (1-W)/R → Half-Kelly = Kelly × 0.5.

    1. kelly_pct = win_rate - (1 - win_rate) / avg_rr_ratio
    2. half_kelly_pct = max(kelly_pct × 0.5, 0)  # 음수 방지
    3. investment = total_capital × half_kelly_pct
    4. × SignalStrength 배수 × position_scale
    5. min(investment, total_capital × max_investment_ratio)
    """

    @staticmethod
    def calculate(
        total_capital: Decimal,
        available_balance: Decimal,
        signal: TradingSignal,
        params: RiskParams,
    ) -> PositionSizeResult:
        win_rate = params["win_rate_estimate"]
        avg_rr = params["avg_rr_ratio"]
        strength = signal["strength"]
        position_scale = signal["position_scale"]
        entry_price = signal["entry_price"]
        stop_loss_price = signal["exit_params"]["stop_loss"]

        strength_multiplier = SIGNAL_MULTIPLIER.get(strength, 0.5)

        # Kelly 계산
        kelly_pct = win_rate - (1.0 - win_rate) / avg_rr if avg_rr > 0 else 0.0
        half_kelly_pct = max(kelly_pct * KELLY_HALF_FACTOR, 0.0)

        # 투자금 산출
        raw_investment = total_capital * Decimal(str(half_kelly_pct))

        # 신호 강도 + 장세 스케일 적용
        investment = raw_investment * Decimal(str(strength_multiplier)) * Decimal(str(position_scale))

        # 최대 투자비율 캡
        max_investment = total_capital * Decimal(str(params["max_investment_ratio"]))
        investment = min(investment, max_investment)

        investment_ratio = float(investment / total_capital) if total_capital > 0 else 0.0
        quantity = investment / Decimal(str(entry_price)) if entry_price > 0 else Decimal("0")

        stop_loss_pct = abs(entry_price - stop_loss_price) / entry_price if entry_price > 0 else params["stop_loss_ratio"]

        logger.debug(
            "HK sizer: kelly=%.4f half_kelly=%.4f investment=%s",
            kelly_pct, half_kelly_pct, investment,
        )

        return PositionSizeResult(
            method="half_kelly",
            quantity=quantity,
            investment_amount=investment,
            investment_ratio=investment_ratio,
            stop_loss_ratio=stop_loss_pct,
            kelly_fraction=half_kelly_pct,
            strength_multiplier=strength_multiplier,
            position_scale=position_scale,
            detail=(
                f"HK: kelly={kelly_pct:.4f} half={half_kelly_pct:.4f} "
                f"×{strength_multiplier}(strength) ×{position_scale}(scale)"
            ),
        )

"""전략 선택기 — regime → strategy 매핑.

PRD §7.3.5 기반 confidence 구간별 처리.
순수 계산 클래스 — DB / Redis / HTTP 의존성 없음.
"""
from __future__ import annotations

import logging

from app.trading.indicators.types import CandleInput, IndicatorResult
from app.trading.regime.types import RegimeResult, RegimeType

from .base import TradingStrategy
from .rsi_bb_reversal import RSIBBReversalStrategy
from .rsi_divergence import RSIDivergenceStrategy
from .trend_ma import TrendMAStrategy
from .types import StrategyName, StrategySelection, StrategySignal
from .vwap_band_reversal import VWAPBandReversalStrategy
from .vwap_bounce import VWAPBounceStrategy

logger = logging.getLogger(__name__)

# ── 상수 ──────────────────────────────────────────────────────────────────────

CONFIDENCE_HOLD_THRESHOLD = 0.5       # 미만 시 HOLD
CONFIDENCE_FULL_THRESHOLD = 0.7       # 이상 시 풀 포지션
CONSERVATIVE_POSITION_SCALE = 0.5     # 50~70% confidence

# Regime → Strategy 우선순위 매핑 (PRD §7.4)
# 리스트 순서 = 우선순위 (둘 다 충족 시 앞 전략 채택)
REGIME_STRATEGY_MAP: dict[RegimeType, list[StrategyName]] = {
    "trend": ["trend_ma", "vwap_bounce"],                    # TrendMA 우선
    "range": ["rsi_bb_reversal", "vwap_band_reversal"],      # RSI+볼밴 우선
    "transition": ["rsi_divergence"],
}


class StrategySelector:
    """regime → strategy 매핑 + 조건부 전략 선택.

    순수 계산 클래스 — DB / Redis / HTTP 의존성 없음.
    """

    def __init__(self) -> None:
        self._strategies: dict[StrategyName, TradingStrategy] = {
            "trend_ma": TrendMAStrategy(),
            "vwap_bounce": VWAPBounceStrategy(),
            "rsi_bb_reversal": RSIBBReversalStrategy(),
            "vwap_band_reversal": VWAPBandReversalStrategy(),
            "rsi_divergence": RSIDivergenceStrategy(),
        }

    def select(
        self,
        regime: RegimeResult,
        candles: list[CandleInput],
        indicators: IndicatorResult,
    ) -> tuple[StrategySelection, StrategySignal] | None:
        """전략 선택 + 진입 조건 평가.

        1. confidence < 0.5 → None (HOLD)
        2. REGIME_STRATEGY_MAP에서 후보 전략 조회
        3. 후보를 순서대로 evaluate() → 첫 번째 non-None 채택
        4. (StrategySelection, StrategySignal) 또는 None 반환

        Returns:
            (StrategySelection, StrategySignal) 또는 None (HOLD).
        """
        confidence = regime["confidence"]
        regime_type = regime["regime"]

        # 1. confidence 미달 시 HOLD
        if confidence < CONFIDENCE_HOLD_THRESHOLD:
            logger.debug(
                "StrategySelector: HOLD (confidence=%.2f < %.2f)",
                confidence, CONFIDENCE_HOLD_THRESHOLD,
            )
            return None

        # 2. 포지션 스케일 결정
        position_scale = (
            1.0 if confidence >= CONFIDENCE_FULL_THRESHOLD else CONSERVATIVE_POSITION_SCALE
        )

        # 3. 후보 전략 조회
        candidate_names = REGIME_STRATEGY_MAP.get(regime_type)
        if not candidate_names:
            logger.debug("StrategySelector: regime=%s 에 매핑된 전략 없음", regime_type)
            return None

        # 4. 후보 전략 순서대로 evaluate()
        for strategy_name in candidate_names:
            strategy = self._strategies.get(strategy_name)
            if strategy is None:
                logger.warning("StrategySelector: 전략 %s 를 찾을 수 없음", strategy_name)
                continue

            signal = strategy.evaluate(candles, indicators)
            if signal is not None:
                selection = StrategySelection(
                    strategy_name=strategy_name,
                    position_scale=position_scale,
                    reason=(
                        f"regime={regime_type}(confidence={confidence:.2f}), "
                        f"전략={strategy_name} 조건 충족"
                    ),
                )
                logger.debug(
                    "StrategySelector: %s 선택 (confidence=%.2f, scale=%.1f)",
                    strategy_name, confidence, position_scale,
                )
                return selection, signal

        logger.debug(
            "StrategySelector: %s 장세 모든 후보 전략 미충족 %s",
            regime_type, candidate_names,
        )
        return None

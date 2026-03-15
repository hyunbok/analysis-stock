"""매매 신호 생성기 — SignalGenerator + MTF 검증.

순수 계산 클래스 — DB / Redis / HTTP 의존성 없음.
서비스 레이어의 진입점.
"""
from __future__ import annotations

import logging
from typing import Literal

from app.trading.indicators.types import CandleInput, IndicatorResult
from app.trading.regime.types import RegimeResult

from .selector import StrategySelector
from .types import MTFDirection, MTFResult, SignalStrength, TradingSignal

logger = logging.getLogger(__name__)

# ── MTF 상수 ──────────────────────────────────────────────────────────────────

MTF_WEIGHT_BOTH_ALIGNED = 1.0    # 1h bullish + 4h bullish
MTF_WEIGHT_ONE_NEUTRAL = 0.75    # 한쪽 neutral
MTF_WEIGHT_BOTH_NEUTRAL = 0.5    # 둘 다 neutral
MTF_WEIGHT_BLOCKED = 0.0         # bearish 포함 → 차단


def _classify_direction(
    indicators: IndicatorResult,
    timeframe: str,
) -> MTFDirection:
    """단일 타임프레임 방향 판별 (ADR-17-7).

    bullish 조건 (any):
    - EMA20 > EMA50 (상승 정렬)
    - RSI > 50

    bearish 조건 (any):
    - EMA20 < EMA50 (하락 정렬)
    - RSI < 50

    neutral: 위 조건 미충족 또는 혼합
    """
    ema = indicators["ema"]
    rsi = indicators["rsi"]
    ema_20 = ema["ema_20"]
    ema_50 = ema["ema_50"]

    details: list[str] = []
    bullish_signals = 0
    bearish_signals = 0

    # EMA 정렬
    if ema_20 is not None and ema_50 is not None:
        if ema_20 > ema_50:
            bullish_signals += 1
            details.append(f"EMA20={ema_20:.4f} > EMA50={ema_50:.4f}(상승)")
        elif ema_20 < ema_50:
            bearish_signals += 1
            details.append(f"EMA20={ema_20:.4f} < EMA50={ema_50:.4f}(하락)")
        else:
            details.append("EMA20=EMA50(중립)")
    else:
        details.append("EMA 없음")

    # RSI (설계서 §7.1: RSI > 50 = bullish, RSI < 50 = bearish, RSI == 50 = neutral)
    if rsi is not None:
        if rsi > 50:
            bullish_signals += 1
            details.append(f"RSI={rsi:.1f} > 50(상승)")
        elif rsi < 50:
            bearish_signals += 1
            details.append(f"RSI={rsi:.1f} < 50(하락)")
        else:
            details.append(f"RSI={rsi:.1f} = 50(중립)")
    else:
        details.append("RSI 없음")

    # 방향 결정
    direction: Literal["bullish", "bearish", "neutral"]
    if bullish_signals > bearish_signals:
        direction = "bullish"
    elif bearish_signals > bullish_signals:
        direction = "bearish"
    else:
        direction = "neutral"

    return MTFDirection(
        timeframe=timeframe,
        direction=direction,
        detail=", ".join(details),
    )


def _verify_mtf(
    action: Literal["buy", "sell"],
    indicators_1h: IndicatorResult | None,
    indicators_4h: IndicatorResult | None,
) -> MTFResult:
    """MTF 검증 규칙 (PRD §7.7).

    MTF 데이터 없으면 중립으로 처리.

    반환:
        MTFResult(allowed, weight, directions, detail)
    """
    # MTF 데이터 없으면 weight=0.5 (both neutral)
    if indicators_1h is None and indicators_4h is None:
        return MTFResult(
            allowed=True,
            weight=MTF_WEIGHT_BOTH_NEUTRAL,
            directions=[],
            detail="MTF 데이터 없음 (기본 weight=0.5 적용)",
        )

    directions: list[MTFDirection] = []

    dir_1h: Literal["bullish", "bearish", "neutral"] = "neutral"
    dir_4h: Literal["bullish", "bearish", "neutral"] = "neutral"

    if indicators_1h is not None:
        mtf_1h = _classify_direction(indicators_1h, "1h")
        directions.append(mtf_1h)
        dir_1h = mtf_1h["direction"]

    if indicators_4h is not None:
        mtf_4h = _classify_direction(indicators_4h, "4h")
        directions.append(mtf_4h)
        dir_4h = mtf_4h["direction"]

    # 매수 신호 차단 규칙: bearish 포함 시 차단
    if action == "buy":
        if dir_1h == "bearish" or dir_4h == "bearish":
            return MTFResult(
                allowed=False,
                weight=MTF_WEIGHT_BLOCKED,
                directions=directions,
                detail=f"매수 차단: 1h={dir_1h}, 4h={dir_4h} (bearish 포함)",
            )
    elif action == "sell":
        if dir_1h == "bullish" or dir_4h == "bullish":
            return MTFResult(
                allowed=False,
                weight=MTF_WEIGHT_BLOCKED,
                directions=directions,
                detail=f"매도 차단: 1h={dir_1h}, 4h={dir_4h} (bullish 포함)",
            )

    # weight 결정
    if dir_1h == "bullish" and dir_4h == "bullish":
        weight = MTF_WEIGHT_BOTH_ALIGNED
        detail = "MTF 정렬 (1h bullish + 4h bullish)"
    elif dir_1h == "neutral" and dir_4h == "neutral":
        weight = MTF_WEIGHT_BOTH_NEUTRAL
        detail = "MTF 중립 (1h neutral + 4h neutral)"
    elif (dir_1h == "bullish" and dir_4h == "neutral") or (
        dir_1h == "neutral" and dir_4h == "bullish"
    ):
        weight = MTF_WEIGHT_ONE_NEUTRAL
        detail = f"MTF 부분 정렬 (1h={dir_1h}, 4h={dir_4h})"
    elif dir_1h == "bearish" and dir_4h == "bearish":
        # sell signal — bearish alignment
        weight = MTF_WEIGHT_BOTH_ALIGNED
        detail = "MTF 하락 정렬 (1h bearish + 4h bearish)"
    else:
        weight = MTF_WEIGHT_ONE_NEUTRAL
        detail = f"MTF 혼합 (1h={dir_1h}, 4h={dir_4h})"

    return MTFResult(
        allowed=True,
        weight=weight,
        directions=directions,
        detail=detail,
    )


def _calc_strength(confidence: float) -> SignalStrength:
    """confidence 기반 시그널 강도 계산."""
    if confidence >= 0.7:
        return "strong"
    if confidence >= 0.4:
        return "moderate"
    return "weak"


class SignalGenerator:
    """매매 신호 생성 + MTF 검증.

    순수 계산 클래스 — DB / Redis / HTTP 의존성 없음.
    """

    def __init__(self) -> None:
        self._selector = StrategySelector()

    def generate(
        self,
        candles: list[CandleInput],
        indicators: IndicatorResult,
        regime: RegimeResult,
        indicators_1h: IndicatorResult | None = None,
        indicators_4h: IndicatorResult | None = None,
    ) -> TradingSignal | None:
        """매매 신호 생성.

        1. StrategySelector.select() → 전략 선택 + 진입 평가
        2. MTF 방향 검증 → 차단 or 가중치 적용
        3. 최종 confidence = regime.confidence × strategy.confidence × mtf.weight
        4. TradingSignal 조립

        Args:
            candles: 5분봉 OHLCV (시간순, 최소 200개 권장).
            indicators: 5분봉 기술적 지표.
            regime: 장세 분류 결과.
            indicators_1h: 1시간봉 지표 (MTF, 선택).
            indicators_4h: 4시간봉 지표 (MTF, 선택).

        Returns:
            TradingSignal 또는 None (HOLD / MTF 차단).
        """
        # 1. 전략 선택 + 진입 조건 평가
        result = self._selector.select(regime, candles, indicators)
        if result is None:
            logger.debug("SignalGenerator: StrategySelector → HOLD")
            return None

        selection, strategy_signal = result

        # 2. MTF 검증
        mtf = _verify_mtf(
            strategy_signal["action"],
            indicators_1h,
            indicators_4h,
        )

        if not mtf["allowed"]:
            logger.debug("SignalGenerator: MTF 차단 — %s", mtf["detail"])
            return None

        # 3. 최종 confidence 계산
        final_confidence = (
            regime["confidence"]
            * strategy_signal["confidence"]
            * mtf["weight"]
        )

        # 4. TradingSignal 조립
        return TradingSignal(
            strategy_name=strategy_signal["strategy_name"],
            action=strategy_signal["action"],
            confidence=final_confidence,
            entry_price=strategy_signal["entry_price"],
            exit_params=strategy_signal["exit_params"],
            strength=_calc_strength(final_confidence),
            position_scale=selection["position_scale"],
            mtf_weight=mtf["weight"],
            conditions=strategy_signal["conditions"],
            regime_type=regime["regime"],
            detail=(
                f"{strategy_signal['detail']} | "
                f"MTF: {mtf['detail']} | "
                f"regime={regime['regime']}(conf={regime['confidence']:.2f}) | "
                f"최종 confidence={final_confidence:.3f}"
            ),
        )

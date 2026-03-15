"""장세 분류기 — 규칙 기반 통합 분류 + confidence 계산.

순수 함수 모듈 — FastAPI / DB / Redis 의존성 금지.
"""
from __future__ import annotations

import logging
import math

from app.trading.indicators.types import IndicatorResult

from .rules import (
    check_adx_strength,
    check_bollinger_regime,
    check_ema_alignment,
    check_macd_momentum,
    check_rsi_regime,
)
from .types import RegimeResult, RegimeScores, RuleSignal

logger = logging.getLogger(__name__)

# ── 규칙별 가중치 ──────────────────────────────────────────────────────────────

RULE_WEIGHTS: dict[str, float] = {
    "adx_strength": 0.30,
    "ema_alignment": 0.20,
    "rsi_regime": 0.20,
    "macd_momentum": 0.15,
    "bollinger_regime": 0.15,
}

# 활성 규칙 최소 수 (미만 시 ValueError — §8.2 RegimeErrors.insufficient_indicators)
MIN_ACTIVE_RULES = 2


def _softmax(scores: dict[str, float]) -> dict[str, float]:
    """scores dict → 확률 분포 (합=1.0).

    temperature=1.0 사용. 모든 score가 0이면 균등 분배.
    """
    values = list(scores.values())
    if all(v == 0.0 for v in values):
        n = len(scores)
        return {k: 1.0 / n for k in scores}

    max_s = max(values)
    exp_scores = {k: math.exp(v - max_s) for k, v in scores.items()}
    total = sum(exp_scores.values())
    return {k: v / total for k, v in exp_scores.items()}


def _renormalize_weights(active_rule_names: list[str]) -> dict[str, float]:
    """활성 규칙만 포함하도록 가중치 재정규화.

    None 반환된 규칙의 가중치를 제거하고, 나머지 가중치를 비례 배분.
    """
    active_weights = {name: RULE_WEIGHTS[name] for name in active_rule_names}
    total = sum(active_weights.values())
    if total == 0:
        return {}
    return {name: w / total for name, w in active_weights.items()}


def classify_regime(indicators: IndicatorResult) -> RegimeResult:
    """규칙 기반 장세 분류 + confidence 계산.

    1. 5개 규칙 함수 실행 → RuleSignal 리스트 수집
    2. 각 signal.regime 별 가중 합산:
       scores[signal.regime] += WEIGHTS[signal.name] * signal.strength
    3. None 규칙 제외 후 가중치 재정규화
    4. softmax(scores) → 확률 분포
    5. argmax → 선택된 regime, max → confidence

    Args:
        indicators: calculate_all_indicators() 결과.

    Returns:
        RegimeResult (gpt_validated=False, gpt_agreement=None)

    Raises:
        ValueError: 활성 규칙이 2개 미만인 경우 (신뢰도 부족).
    """
    # 1. 규칙 함수 실행
    rule_results: list[tuple[str, RuleSignal | None]] = [
        ("adx_strength", check_adx_strength(indicators)),
        ("ema_alignment", check_ema_alignment(indicators)),
        ("rsi_regime", check_rsi_regime(indicators)),
        ("macd_momentum", check_macd_momentum(indicators)),
        ("bollinger_regime", check_bollinger_regime(indicators)),
    ]

    # 2. 활성 규칙 (None 아닌 것) 수집
    active_signals: list[RuleSignal] = []
    active_rule_names: list[str] = []

    for rule_name, signal in rule_results:
        if signal is not None:
            active_signals.append(signal)
            active_rule_names.append(rule_name)

    # 3. 활성 규칙 수 확인
    if len(active_signals) < MIN_ACTIVE_RULES:
        raise ValueError(
            f"활성 규칙이 {len(active_signals)}개로 최소 {MIN_ACTIVE_RULES}개 미만입니다. "
            "장세 분류에 필요한 지표 데이터가 부족합니다."
        )

    # 4. 가중치 재정규화
    normalized_weights = _renormalize_weights(active_rule_names)

    # 5. 장세별 가중 합산
    raw_scores: dict[str, float] = {"trend": 0.0, "range": 0.0, "transition": 0.0}
    for signal in active_signals:
        weight = normalized_weights[signal["name"]]
        raw_scores[signal["regime"]] += weight * signal["strength"]

    # 6. softmax 정규화
    prob_scores = _softmax(raw_scores)

    # 7. 최고 확률 장세 선택
    selected_regime = max(prob_scores, key=lambda k: prob_scores[k])
    confidence = prob_scores[selected_regime]

    scores = RegimeScores(
        trend=prob_scores["trend"],
        range=prob_scores["range"],
        transition=prob_scores["transition"],
    )

    logger.debug(
        "장세 분류 완료: regime=%s, confidence=%.3f, active_rules=%d",
        selected_regime,
        confidence,
        len(active_signals),
    )

    return RegimeResult(
        regime=selected_regime,
        confidence=confidence,
        scores=scores,
        signals=active_signals,
        gpt_validated=False,
        gpt_agreement=None,
    )

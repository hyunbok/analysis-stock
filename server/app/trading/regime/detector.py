"""MarketRegimeDetector — 태스크 스펙 클래스 인터페이스.

classify_regime()의 클래스 래퍼. news_context는 GPT 검증용으로
서비스 레이어에 전달만 함 (순수 계산 클래스 내 GPT 호출 금지).
"""
from __future__ import annotations

import logging

from app.trading.indicators.types import CandleInput, IndicatorResult

from .classifier import classify_regime
from .types import RegimeResult

logger = logging.getLogger(__name__)


class MarketRegimeDetector:
    """규칙 기반 장세 분류기 클래스 인터페이스.

    순수 계산 클래스 — DB / Redis / HTTP 의존성 없음.
    news_context는 저장만 하여 서비스 레이어(RegimeService)에서 GPT 검증 시 사용.
    """

    def detect(
        self,
        candles: list[CandleInput],
        indicators: IndicatorResult,
    ) -> RegimeResult:
        """장세 분류 수행.

        Args:
            candles: OHLCV 캔들 리스트 (현재 버전에서는 미사용, 미래 히스토그램 추세 확장 대비).
            indicators: calculate_all_indicators() 결과.

        Returns:
            RegimeResult (gpt_validated=False, gpt_agreement=None).

        Raises:
            ValueError: indicators에 유효한 지표가 2개 미만인 경우.
        """
        return classify_regime(indicators)

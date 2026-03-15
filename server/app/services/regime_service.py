"""장세 분석 오케스트레이션 서비스.

Redis 캐싱, GPT 검증, MongoDB 저장을 담당한다.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, UTC

from app.core.config import Settings
from app.core.exceptions import RegimeErrors
from app.documents.trading_logs import AiDecision
from app.services.ai_cache_service import AICacheService
from app.services.market_cache_service import MarketCacheService
from app.trading.indicators.types import IndicatorResult
from app.trading.regime.classifier import classify_regime
from app.trading.regime.gpt_validator import adjust_confidence, validate_with_gpt
from app.trading.regime.types import (
    GptValidationInput,
    GptValidationResult,
    RegimeResult,
)

logger = logging.getLogger(__name__)

_NEEDS_GPT_CONFIDENCE_THRESHOLD = 0.7


def _build_indicators_summary(indicators: IndicatorResult) -> dict:
    """IndicatorResult → GPT 프롬프트용 주요 지표 요약 dict."""
    return {
        "adx": indicators["adx"].get("adx"),
        "di_plus": indicators["adx"].get("di_plus"),
        "di_minus": indicators["adx"].get("di_minus"),
        "rsi": indicators.get("rsi"),
        "macd_line": indicators["macd"].get("macd_line"),
        "macd_signal": indicators["macd"].get("signal_line"),
        "macd_histogram": indicators["macd"].get("histogram"),
        "ema_20": indicators["ema"].get("ema_20"),
        "ema_50": indicators["ema"].get("ema_50"),
        "ema_200": indicators["ema"].get("ema_200"),
        "bb_bandwidth": indicators["bollinger"].get("bandwidth"),
        "bb_percent_b": indicators["bollinger"].get("percent_b"),
    }


class RegimeService:
    """장세 분석 오케스트레이션 서비스.

    DI 의존성:
    - MarketCacheService: Redis 캐시 (get/set_regime)
    - AICacheService: AI 결정 캐시 + Pub/Sub 발행
    - Settings: OpenAI API 키/모델/타임아웃

    Note: MongoDB 저장은 Beanie ORM (doc.insert())를 통해 수행.
          Beanie는 앱 lifespan에서 전역 초기화되므로 Motor 직접 의존 불필요.
    """

    def __init__(
        self,
        market_cache: MarketCacheService,
        ai_cache: AICacheService,
        settings: Settings,
    ) -> None:
        self._market_cache = market_cache
        self._ai_cache = ai_cache
        self._settings = settings

    async def detect(
        self,
        *,
        exchange: str,
        market: str,
        indicators: IndicatorResult,
        news_context: list[str] | None = None,
        user_id: str | None = None,
        force_refresh: bool = False,
    ) -> RegimeResult:
        """장세 분석 실행.

        1. Redis 캐시 확인 (force_refresh=False 시)
        2. classify_regime() 호출
        3. GPT 검증 필요 시 validate_with_gpt() 호출
        4. confidence 조정
        5. Redis 캐시 저장
        6. MongoDB ai_decisions 저장 (user_id 있는 경우)
        7. RegimeResult 반환

        Raises:
            AppError(REGIME_INSUFFICIENT_INDICATORS): 활성 규칙 < 2개
            AppError(REGIME_ANALYSIS_FAILED): 분류 과정 예기치 못한 오류
        """
        # 1. Redis 캐시 확인
        if not force_refresh:
            cached = await self._get_cached(exchange, market)
            if cached is not None:
                return cached

        # 2. 규칙 기반 분류
        try:
            result: RegimeResult = classify_regime(indicators)
        except ValueError:
            raise RegimeErrors.insufficient_indicators()
        except Exception:
            logger.error("regime_classify_failed: exchange=%s market=%s", exchange, market, exc_info=True)
            raise RegimeErrors.analysis_failed()

        # 3. GPT 검증 여부 결정
        needs_gpt = (
            result["confidence"] < _NEEDS_GPT_CONFIDENCE_THRESHOLD
            or result["regime"] == "transition"
        )

        gpt_result: GptValidationResult | None = None
        if needs_gpt and self._settings.OPENAI_API_KEY:
            gpt_result = await self._run_gpt_validation(result, indicators, news_context)

        # 4. confidence 조정 (gpt_validator.adjust_confidence 활용)
        adjusted_confidence, gpt_validated, gpt_agreement = adjust_confidence(
            result["confidence"], gpt_result
        )
        result = RegimeResult(
            regime=result["regime"],
            confidence=adjusted_confidence,
            scores=result["scores"],
            signals=result["signals"],
            gpt_validated=gpt_validated,
            gpt_agreement=gpt_agreement,
        )

        # 5. Redis 캐시 저장 (fire-and-forget)
        await self._store_cache(exchange, market, result)

        # 6. MongoDB 저장 (user_id 있는 경우, fire-and-forget)
        if user_id is not None:
            await self._store_mongodb(
                exchange=exchange,
                market=market,
                result=result,
                user_id=user_id,
                news_context=news_context,
                gpt_result=gpt_result,
            )

        return result

    # ── 내부 헬퍼 ─────────────────────────────────────────────────────────────

    async def _get_cached(self, exchange: str, market: str) -> RegimeResult | None:
        """Redis 캐시 조회. 실패 시 None 반환 (fire-and-forget)."""
        try:
            cached = await self._market_cache.get_regime(exchange, market)
            if cached is not None:
                logger.debug("regime_cache_hit: exchange=%s market=%s", exchange, market)
                return RegimeResult(**cached)
        except Exception:
            logger.warning(
                "regime_cache_get_failed: exchange=%s market=%s",
                exchange,
                market,
                exc_info=True,
            )
        return None

    async def _run_gpt_validation(
        self,
        result: RegimeResult,
        indicators: IndicatorResult,
        news_context: list[str] | None,
    ) -> GptValidationResult | None:
        """GPT 검증 수행. 실패 시 None 반환 (non-blocking)."""
        gpt_input: GptValidationInput = {
            "regime": result["regime"],
            "confidence": result["confidence"],
            "scores": result["scores"],
            "signals": result["signals"],
            "indicators_summary": _build_indicators_summary(indicators),
            "news_context": news_context[:5] if news_context else None,
        }
        try:
            return await validate_with_gpt(
                gpt_input,
                api_key=self._settings.OPENAI_API_KEY,
                model=self._settings.OPENAI_MODEL,
                timeout=self._settings.OPENAI_TIMEOUT,
            )
        except Exception:
            logger.warning("regime_gpt_validation_failed", exc_info=True)
            return None

    async def _store_cache(self, exchange: str, market: str, result: RegimeResult) -> None:
        """Redis에 RegimeResult 저장. 실패 시 로그만 (fire-and-forget)."""
        try:
            await self._market_cache.set_regime(exchange, market, dict(result))
        except Exception:
            logger.warning(
                "regime_cache_set_failed: exchange=%s market=%s",
                exchange,
                market,
                exc_info=True,
            )

    async def _store_mongodb(
        self,
        *,
        exchange: str,
        market: str,
        result: RegimeResult,
        user_id: str,
        news_context: list[str] | None,
        gpt_result: GptValidationResult | None,
    ) -> None:
        """AiDecision 도큐먼트에 장세 분석 결과 저장. 실패 시 로그만 (fire-and-forget)."""
        try:
            parsed_user_id = uuid.UUID(user_id)
        except (ValueError, AttributeError):
            logger.warning("regime_mongodb_invalid_user_id: user_id=%s", user_id)
            return

        try:
            gpt_model = gpt_result["model"] if gpt_result else None
            gpt_prompt_tokens = gpt_result["prompt_tokens"] if gpt_result else None
            gpt_completion_tokens = gpt_result["completion_tokens"] if gpt_result else None
            gpt_raw = json.dumps(gpt_result, ensure_ascii=False) if gpt_result else None

            # signals 포함 파싱 결과를 gpt_parsed_result에 저장
            gpt_parsed: dict = {
                "regime": result["regime"],
                "confidence": result["confidence"],
                "signals": list(result["signals"]),
                "gpt_agreement": result["gpt_agreement"],
            }
            if gpt_result:
                gpt_parsed["gpt_reasoning"] = gpt_result.get("reasoning")

            news_summary: str | None = None
            if news_context:
                news_summary = " | ".join(news_context[:5])

            doc = AiDecision(
                user_id=parsed_user_id,
                coin_symbol=market,
                market_regime=result["regime"],
                regime_confidence=dict(result["scores"]),
                gpt_model=gpt_model,
                gpt_prompt_tokens=gpt_prompt_tokens,
                gpt_completion_tokens=gpt_completion_tokens,
                gpt_raw_response=gpt_raw,
                gpt_parsed_result=gpt_parsed,
                news_context_summary=news_summary,
                created_at=datetime.now(UTC),
            )
            await doc.insert()
            logger.debug(
                "regime_mongodb_stored: exchange=%s market=%s user_id=%s",
                exchange,
                market,
                user_id,
            )
        except Exception:
            logger.error(
                "regime_mongodb_store_failed: exchange=%s market=%s user_id=%s",
                exchange,
                market,
                user_id,
                exc_info=True,
            )

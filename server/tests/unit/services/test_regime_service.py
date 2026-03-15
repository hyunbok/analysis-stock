"""RegimeService 단위 테스트 — 캐시 HIT/MISS, GPT 분기, MongoDB 저장."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.config import Settings
from app.services.ai_cache_service import AICacheService
from app.services.market_cache_service import MarketCacheService
from app.services.regime_service import RegimeService
from app.trading.regime.types import RegimeResult


# ── 공통 픽스처 ────────────────────────────────────────────────────────────────

TREND_RESULT: RegimeResult = {
    "regime": "trend",
    "confidence": 0.80,
    "scores": {"trend": 0.80, "range": 0.10, "transition": 0.10},
    "signals": [
        {"name": "adx_strength", "regime": "trend", "strength": 0.9, "detail": "ADX=35"},
    ],
    "gpt_validated": False,
    "gpt_agreement": None,
}

LOW_CONF_RESULT: RegimeResult = {
    "regime": "transition",
    "confidence": 0.55,
    "scores": {"trend": 0.30, "range": 0.15, "transition": 0.55},
    "signals": [
        {"name": "adx_strength", "regime": "transition", "strength": 0.5, "detail": "ADX=22"},
    ],
    "gpt_validated": False,
    "gpt_agreement": None,
}

MOCK_INDICATORS = {
    "adx": {"adx": 35.0, "di_plus": 28.0, "di_minus": 12.0},
    "rsi": 65.0,
    "macd": {"macd_line": 0.005, "signal_line": 0.003, "histogram": 0.002},
    "ema": {"ema_20": 50100.0, "ema_50": 49800.0, "ema_200": 48000.0},
    "bollinger": {
        "upper": 51000.0,
        "middle": 50000.0,
        "lower": 49000.0,
        "bandwidth": 0.04,
        "percent_b": 0.55,
    },
    "vwap": {"vwap": 50050.0, "upper_band": 51000.0, "lower_band": 49100.0},
    "stochastic": {"k": 70.0, "d": 65.0},
    "williams_r": -30.0,
    "cci": 80.0,
    "atr": 500.0,
    "obv": 1234567.0,
}


@pytest.fixture
def mock_market_cache():
    cache = MagicMock(spec=MarketCacheService)
    cache.get_regime = AsyncMock(return_value=None)  # 기본: 캐시 MISS
    cache.set_regime = AsyncMock()
    return cache


@pytest.fixture
def mock_ai_cache():
    cache = MagicMock(spec=AICacheService)
    cache.set_ai_decision = AsyncMock()
    return cache


@pytest.fixture
def mock_settings():
    s = MagicMock(spec=Settings)
    s.OPENAI_API_KEY = "test-key"
    s.OPENAI_MODEL = "gpt-4o-mini"
    s.OPENAI_TIMEOUT = 10.0
    return s


@pytest.fixture
def service(mock_market_cache, mock_ai_cache, mock_settings):
    return RegimeService(mock_market_cache, mock_ai_cache, mock_settings)


# ── 테스트 ─────────────────────────────────────────────────────────────────────

async def test_cache_hit_returns_cached(service, mock_market_cache):
    """캐시 HIT 시 classify_regime 호출 없이 캐시 결과 반환."""
    mock_market_cache.get_regime = AsyncMock(return_value=dict(TREND_RESULT))

    with patch("app.services.regime_service.classify_regime") as mock_classify:
        result = await service.detect(
            exchange="upbit",
            market="KRW-BTC",
            indicators=MOCK_INDICATORS,
        )

    mock_classify.assert_not_called()
    assert result["regime"] == "trend"
    assert result["confidence"] == 0.80


async def test_cache_miss_calls_classify(service, mock_market_cache):
    """캐시 MISS 시 classify_regime 호출 후 결과 반환."""
    mock_market_cache.get_regime = AsyncMock(return_value=None)

    with patch("app.services.regime_service.classify_regime", return_value=TREND_RESULT):
        result = await service.detect(
            exchange="upbit",
            market="KRW-BTC",
            indicators=MOCK_INDICATORS,
        )

    assert result["regime"] == "trend"
    mock_market_cache.set_regime.assert_called_once()


async def test_high_confidence_no_gpt(service, mock_market_cache):
    """confidence ≥ 0.7 + trend → GPT 미호출."""
    mock_market_cache.get_regime = AsyncMock(return_value=None)

    with (
        patch("app.services.regime_service.classify_regime", return_value=TREND_RESULT),
        patch.object(service, "_run_gpt_validation", new_callable=AsyncMock) as mock_gpt,
    ):
        result = await service.detect(
            exchange="upbit",
            market="KRW-BTC",
            indicators=MOCK_INDICATORS,
        )

    mock_gpt.assert_not_called()
    assert result["gpt_validated"] is False


async def test_low_confidence_triggers_gpt(service, mock_market_cache):
    """confidence < 0.7 → GPT 호출 + confidence 조정 (동의)."""
    mock_market_cache.get_regime = AsyncMock(return_value=None)
    gpt_response = {
        "agrees": True,
        "suggested_regime": "transition",
        "reasoning": "Market is consolidating.",
        "prompt_tokens": 100,
        "completion_tokens": 50,
        "model": "gpt-4o-mini",
    }

    with (
        patch("app.services.regime_service.classify_regime", return_value=LOW_CONF_RESULT),
        patch.object(service, "_run_gpt_validation", new_callable=AsyncMock, return_value=gpt_response),
    ):
        result = await service.detect(
            exchange="upbit",
            market="KRW-BTC",
            indicators=MOCK_INDICATORS,
        )

    assert result["gpt_validated"] is True
    assert result["gpt_agreement"] is True
    # confidence 조정: 0.55 + 0.10 = 0.65
    assert abs(result["confidence"] - 0.65) < 1e-9


async def test_gpt_disagreement_lowers_confidence(service, mock_market_cache):
    """GPT 불일치 → confidence -0.15."""
    mock_market_cache.get_regime = AsyncMock(return_value=None)
    gpt_response = {
        "agrees": False,
        "suggested_regime": "range",
        "reasoning": "Indicators weak.",
        "prompt_tokens": 80,
        "completion_tokens": 40,
        "model": "gpt-4o-mini",
    }

    with (
        patch("app.services.regime_service.classify_regime", return_value=LOW_CONF_RESULT),
        patch.object(service, "_run_gpt_validation", new_callable=AsyncMock, return_value=gpt_response),
    ):
        result = await service.detect(
            exchange="upbit",
            market="KRW-BTC",
            indicators=MOCK_INDICATORS,
        )

    # confidence 조정: 0.55 - 0.15 = 0.40
    assert abs(result["confidence"] - 0.40) < 1e-9
    assert result["gpt_agreement"] is False


async def test_gpt_failure_returns_rule_based(service, mock_market_cache):
    """GPT 타임아웃/오류 → 규칙 기반 결과 그대로 반환 (non-blocking)."""
    mock_market_cache.get_regime = AsyncMock(return_value=None)

    with (
        patch("app.services.regime_service.classify_regime", return_value=LOW_CONF_RESULT),
        patch.object(service, "_run_gpt_validation", new_callable=AsyncMock, return_value=None),
    ):
        result = await service.detect(
            exchange="upbit",
            market="KRW-BTC",
            indicators=MOCK_INDICATORS,
        )

    assert result["gpt_validated"] is False
    assert result["gpt_agreement"] is None
    assert result["confidence"] == 0.55


async def test_force_refresh_skips_cache(service, mock_market_cache):
    """force_refresh=True 시 캐시 조회 건너뜀."""
    mock_market_cache.get_regime = AsyncMock(return_value=dict(TREND_RESULT))

    with patch("app.services.regime_service.classify_regime", return_value=TREND_RESULT):
        await service.detect(
            exchange="upbit",
            market="KRW-BTC",
            indicators=MOCK_INDICATORS,
            force_refresh=True,
        )

    # force_refresh=True이므로 get_regime 미호출
    mock_market_cache.get_regime.assert_not_called()


async def test_no_openai_key_skips_gpt(service, mock_market_cache, mock_settings):  # noqa: ARG001
    """OPENAI_API_KEY 미설정 시 GPT 미호출."""
    mock_settings.OPENAI_API_KEY = ""
    mock_market_cache.get_regime = AsyncMock(return_value=None)

    with (
        patch("app.services.regime_service.classify_regime", return_value=LOW_CONF_RESULT),
        patch.object(service, "_run_gpt_validation", new_callable=AsyncMock) as mock_gpt,
    ):
        result = await service.detect(
            exchange="upbit",
            market="KRW-BTC",
            indicators=MOCK_INDICATORS,
        )

    mock_gpt.assert_not_called()
    assert result["gpt_validated"] is False


async def test_user_id_triggers_mongodb_store(service, mock_market_cache):
    """user_id 있을 때 _store_mongodb 호출 확인."""
    mock_market_cache.get_regime = AsyncMock(return_value=None)

    with (
        patch("app.services.regime_service.classify_regime", return_value=TREND_RESULT),
        patch.object(service, "_store_mongodb", new_callable=AsyncMock) as mock_store,
    ):
        await service.detect(
            exchange="upbit",
            market="KRW-BTC",
            indicators=MOCK_INDICATORS,
            user_id="550e8400-e29b-41d4-a716-446655440000",
        )

    mock_store.assert_called_once()


async def test_no_user_id_skips_mongodb(service, mock_market_cache):
    """user_id 없으면 _store_mongodb 미호출 확인."""
    mock_market_cache.get_regime = AsyncMock(return_value=None)

    with (
        patch("app.services.regime_service.classify_regime", return_value=TREND_RESULT),
        patch.object(service, "_store_mongodb", new_callable=AsyncMock) as mock_store,
    ):
        await service.detect(
            exchange="upbit",
            market="KRW-BTC",
            indicators=MOCK_INDICATORS,
        )

    mock_store.assert_not_called()

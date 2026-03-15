"""trading/regime/gpt_validator.py 단위 테스트 (mock 기반)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.trading.regime.gpt_validator import adjust_confidence, validate_with_gpt
from app.trading.regime.types import GptValidationInput, GptValidationResult, RegimeScores, RuleSignal


def _make_gpt_input() -> GptValidationInput:
    return GptValidationInput(
        regime="trend",
        confidence=0.65,
        scores=RegimeScores(trend=0.65, range=0.20, transition=0.15),
        signals=[
            RuleSignal(name="adx_strength", regime="trend", strength=0.8, detail="ADX=35"),
        ],
        indicators_summary={"adx": 35.0, "rsi": 65.0},
        news_context=None,
    )


def _make_mock_response(agrees: bool, suggested: str = "trend") -> MagicMock:
    """openai 응답 mock 생성."""
    import json
    mock_usage = MagicMock()
    mock_usage.prompt_tokens = 100
    mock_usage.completion_tokens = 50

    mock_choice = MagicMock()
    mock_choice.message.content = json.dumps({
        "agrees": agrees,
        "suggested_regime": suggested,
        "reasoning": "Test reasoning",
    })

    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    mock_response.usage = mock_usage
    mock_response.model = "gpt-4o-mini"
    return mock_response


class TestValidateWithGpt:
    @pytest.mark.asyncio
    async def test_agrees_true_returns_result(self):
        mock_response = _make_mock_response(agrees=True, suggested="trend")

        with patch("app.trading.regime.gpt_validator.AsyncOpenAI") as mock_cls:
            mock_client = AsyncMock()
            mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
            mock_client.close = AsyncMock()
            mock_cls.return_value = mock_client

            result = await validate_with_gpt(
                _make_gpt_input(), api_key="test-key", model="gpt-4o-mini"
            )

        assert result is not None
        assert result["agrees"] is True
        assert result["suggested_regime"] == "trend"

    @pytest.mark.asyncio
    async def test_disagrees_returns_result(self):
        mock_response = _make_mock_response(agrees=False, suggested="range")

        with patch("app.trading.regime.gpt_validator.AsyncOpenAI") as mock_cls:
            mock_client = AsyncMock()
            mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
            mock_client.close = AsyncMock()
            mock_cls.return_value = mock_client

            result = await validate_with_gpt(
                _make_gpt_input(), api_key="test-key"
            )

        assert result is not None
        assert result["agrees"] is False
        assert result["suggested_regime"] == "range"

    @pytest.mark.asyncio
    async def test_timeout_returns_none(self):
        with patch("app.trading.regime.gpt_validator.AsyncOpenAI") as mock_cls:
            mock_client = AsyncMock()
            mock_client.chat.completions.create = AsyncMock(side_effect=TimeoutError())
            mock_client.close = AsyncMock()
            mock_cls.return_value = mock_client

            result = await validate_with_gpt(
                _make_gpt_input(), api_key="test-key", timeout=0.001
            )

        assert result is None

    @pytest.mark.asyncio
    async def test_api_error_returns_none(self):
        with patch("app.trading.regime.gpt_validator.AsyncOpenAI") as mock_cls:
            mock_client = AsyncMock()
            mock_client.chat.completions.create = AsyncMock(side_effect=Exception("API error"))
            mock_client.close = AsyncMock()
            mock_cls.return_value = mock_client

            result = await validate_with_gpt(
                _make_gpt_input(), api_key="test-key"
            )

        assert result is None

    @pytest.mark.asyncio
    async def test_invalid_json_returns_none(self):
        mock_choice = MagicMock()
        mock_choice.message.content = "not valid json {"

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        with patch("app.trading.regime.gpt_validator.AsyncOpenAI") as mock_cls:
            mock_client = AsyncMock()
            mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
            mock_client.close = AsyncMock()
            mock_cls.return_value = mock_client

            result = await validate_with_gpt(
                _make_gpt_input(), api_key="test-key"
            )

        assert result is None


class TestAdjustConfidence:
    def test_gpt_none_no_change(self):
        confidence, validated, agreement = adjust_confidence(0.65, None)
        assert confidence == pytest.approx(0.65)
        assert validated is False
        assert agreement is None

    def test_gpt_agrees_increases_confidence(self):
        gpt_result = GptValidationResult(
            agrees=True, suggested_regime="trend", reasoning="ok",
            prompt_tokens=100, completion_tokens=50, model="gpt-4o-mini"
        )
        confidence, validated, agreement = adjust_confidence(0.65, gpt_result)
        assert confidence == pytest.approx(0.75)
        assert validated is True
        assert agreement is True

    def test_gpt_disagrees_decreases_confidence(self):
        gpt_result = GptValidationResult(
            agrees=False, suggested_regime="range", reasoning="disagree",
            prompt_tokens=100, completion_tokens=50, model="gpt-4o-mini"
        )
        confidence, validated, agreement = adjust_confidence(0.65, gpt_result)
        assert confidence == pytest.approx(0.50)
        assert validated is True
        assert agreement is False

    def test_confidence_capped_at_1(self):
        gpt_result = GptValidationResult(
            agrees=True, suggested_regime="trend", reasoning="ok",
            prompt_tokens=100, completion_tokens=50, model="gpt-4o-mini"
        )
        confidence, _, _ = adjust_confidence(0.95, gpt_result)
        assert confidence == pytest.approx(1.0)

    def test_confidence_floored_at_0(self):
        gpt_result = GptValidationResult(
            agrees=False, suggested_regime="range", reasoning="disagree",
            prompt_tokens=100, completion_tokens=50, model="gpt-4o-mini"
        )
        confidence, _, _ = adjust_confidence(0.10, gpt_result)
        assert confidence == pytest.approx(0.0)

"""GPT 보조 검증 모듈.

openai SDK 의존 허용 (I/O 바운드 외부 API 클라이언트).
FastAPI / DB / Redis 의존성 금지.
"""
from __future__ import annotations

import json
import logging

from openai import APITimeoutError as OpenAITimeoutError
from openai import AsyncOpenAI

from .types import GptValidationInput, GptValidationResult

logger = logging.getLogger(__name__)

# ── 프롬프트 ───────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a cryptocurrency market analyst.
Analyze the given technical indicators and news context to determine the market regime.
Respond in JSON format only."""


def _build_user_prompt(input: GptValidationInput) -> str:
    """GPT 검증 요청 프롬프트 생성.

    포함 정보:
    - 규칙 기반 분류 결과 (regime, confidence, scores)
    - 주요 지표 값 (ADX, RSI, MACD, EMA, BB bandwidth)
    - 개별 규칙 판별 결과 (signals)
    - 뉴스 컨텍스트 (최대 5건, 있는 경우)
    """
    signals_text = "\n".join(
        f"  - {s['name']}: {s['regime']} (strength={s['strength']:.2f}) — {s['detail']}"
        for s in input["signals"]
    )

    scores = input["scores"]
    scores_text = (
        f"trend={scores['trend']:.3f}, "
        f"range={scores['range']:.3f}, "
        f"transition={scores['transition']:.3f}"
    )

    indicators_text = json.dumps(input["indicators_summary"], ensure_ascii=False, indent=2)

    news_text = ""
    if input["news_context"]:
        news_items = input["news_context"][:5]
        news_text = "\n\nNews Context:\n" + "\n".join(f"  - {n}" for n in news_items)

    return f"""Rule-based classification result:
- Regime: {input['regime']}
- Confidence: {input['confidence']:.3f}
- Scores: {scores_text}

Rule signals:
{signals_text}

Key indicator values:
{indicators_text}{news_text}

Please analyze and respond with:
1. Do you agree with the rule-based classification? (agrees: true/false)
2. Your suggested market regime (suggested_regime: trend/range/transition)
3. Brief reasoning (reasoning: 1-2 sentences)

Respond in JSON format:
{{
  "agrees": true/false,
  "suggested_regime": "trend" | "range" | "transition",
  "reasoning": "brief explanation"
}}"""


# ── 검증 함수 ──────────────────────────────────────────────────────────────────

async def validate_with_gpt(
    input: GptValidationInput,
    *,
    api_key: str,
    model: str = "gpt-4o-mini",
    timeout: float = 10.0,
) -> GptValidationResult | None:
    """GPT 보조 검증 수행.

    Args:
        input: GPT 검증 요청 데이터.
        api_key: OpenAI API 키.
        model: 사용할 GPT 모델명.
        timeout: 요청 타임아웃 (초).

    Returns:
        GptValidationResult 또는 None (API 오류/타임아웃 시).
    """
    client = AsyncOpenAI(api_key=api_key, timeout=timeout)

    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": _build_user_prompt(input)},
            ],
            response_format={"type": "json_object"},
            temperature=0.3,
            max_tokens=256,
        )

        content = response.choices[0].message.content
        if not content:
            logger.warning("GPT 응답 content가 비어있음")
            return None

        parsed = json.loads(content)

        # 필수 필드 검증
        if "agrees" not in parsed or "suggested_regime" not in parsed:
            logger.warning("GPT 응답 필수 필드 누락: %s", parsed)
            return None

        suggested = parsed.get("suggested_regime", "").lower()
        if suggested not in ("trend", "range", "transition"):
            logger.warning("GPT 응답 suggested_regime 유효하지 않음: %s", suggested)
            return None

        usage = response.usage
        return GptValidationResult(
            agrees=bool(parsed["agrees"]),
            suggested_regime=suggested,
            reasoning=parsed.get("reasoning", ""),
            prompt_tokens=usage.prompt_tokens if usage else 0,
            completion_tokens=usage.completion_tokens if usage else 0,
            model=response.model,
        )

    except (OpenAITimeoutError, TimeoutError):
        logger.warning("GPT 검증 타임아웃 (%.1fs)", timeout)
        return None
    except json.JSONDecodeError as e:
        logger.warning("GPT 응답 JSON 파싱 실패: %s", e)
        return None
    except Exception as e:
        logger.warning("GPT 검증 실패: %s", e)
        return None
    finally:
        await client.close()


def adjust_confidence(
    confidence: float,
    gpt_result: GptValidationResult | None,
) -> tuple[float, bool, bool | None]:
    """GPT 검증 결과에 따라 confidence를 조정한다.

    Args:
        confidence: 현재 confidence (0.0 ~ 1.0).
        gpt_result: GPT 검증 결과 (None이면 검증 미수행).

    Returns:
        (adjusted_confidence, gpt_validated, gpt_agreement)
    """
    if gpt_result is None:
        return confidence, False, None

    if gpt_result["agrees"]:
        adjusted = min(confidence + 0.10, 1.0)
    else:
        adjusted = max(confidence - 0.15, 0.0)

    return adjusted, True, gpt_result["agrees"]

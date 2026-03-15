"""장세 분류 엔진 입출력 타입 정의.

FastAPI / SQLAlchemy / Beanie 의존성 완전 금지.
"""
from __future__ import annotations

from typing import Literal, TypedDict


# ── 장세 타입 ──────────────────────────────────────────────────────────────────

RegimeType = Literal["trend", "range", "transition"]


# ── 규칙 판별 결과 ──────────────────────────────────────────────────────────────

class RuleSignal(TypedDict):
    """개별 규칙 판별 결과."""

    name: str                          # 규칙 이름 (예: "adx_strength")
    regime: RegimeType                 # 이 규칙이 지지하는 장세
    strength: float                    # 0.0 ~ 1.0, 규칙 충족 강도
    detail: str                        # 사람이 읽을 수 있는 설명


class RegimeScores(TypedDict):
    """장세별 원시 스코어 (softmax 전)."""

    trend: float
    range: float
    transition: float


class RegimeResult(TypedDict):
    """장세 분류 최종 결과."""

    regime: RegimeType                 # 선택된 장세
    confidence: float                  # 0.0 ~ 1.0 (softmax 정규화 후 최고 스코어)
    scores: RegimeScores               # 장세별 확률 분포
    signals: list[RuleSignal]          # 개별 규칙 판별 결과 목록
    gpt_validated: bool                # GPT 검증 수행 여부
    gpt_agreement: bool | None         # GPT 동의 여부 (미수행 시 None)


# ── GPT 검증 입출력 ─────────────────────────────────────────────────────────────

class GptValidationInput(TypedDict):
    """GPT 검증 요청 입력."""

    regime: RegimeType
    confidence: float
    scores: RegimeScores
    signals: list[RuleSignal]
    indicators_summary: dict           # 주요 지표값 요약
    news_context: list[str] | None     # 뉴스 요약 최대 5건


class GptValidationResult(TypedDict):
    """GPT 검증 응답."""

    agrees: bool                       # 규칙 기반 결과 동의 여부
    suggested_regime: RegimeType       # GPT가 제안하는 장세
    reasoning: str                     # GPT 판단 근거 요약
    prompt_tokens: int
    completion_tokens: int
    model: str

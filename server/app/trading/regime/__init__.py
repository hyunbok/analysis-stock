"""장세 분류 엔진.

순수 계산 패키지 — FastAPI / DB / Redis 의존성 금지.
GPT 검증은 services/ 레이어에서 처리.

# 주의: gpt_validator.py는 openai SDK에 의존함.
# openai는 외부 AI API 클라이언트로, DB/Redis와 달리 인프라 결합 없음 — 허용 예외.
"""
from __future__ import annotations

from .classifier import classify_regime
from .detector import MarketRegimeDetector
from .types import (
    GptValidationInput,
    GptValidationResult,
    RegimeResult,
    RegimeScores,
    RegimeType,
    RuleSignal,
)

__all__ = [
    # 클래스 인터페이스 (태스크 스펙 요구사항)
    "MarketRegimeDetector",
    # 함수 인터페이스 (내부 파이프라인)
    "classify_regime",
    # 타입
    "RegimeType",
    "RegimeResult",
    "RegimeScores",
    "RuleSignal",
    "GptValidationInput",
    "GptValidationResult",
]

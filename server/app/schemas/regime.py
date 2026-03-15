"""장세 분석 Pydantic 스키마.

내부 서비스 DTO + 미래 ai-trading API 응답 준비.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Literal

from pydantic import BaseModel, Field


# ── 내부 DTO (TypedDict → Pydantic 변환용) ────────────────────────────────────

RegimeTypeStr = Literal["trend", "range", "transition"]


class RuleSignalSchema(BaseModel):
    """개별 규칙 판별 결과 — trading/regime/types.py RuleSignal의 Pydantic 변환."""

    name: str
    regime: RegimeTypeStr
    strength: Annotated[float, Field(ge=0.0, le=1.0)]
    detail: str


class RegimeScoresSchema(BaseModel):
    """장세별 softmax 확률 분포."""

    trend: Annotated[float, Field(ge=0.0, le=1.0)]
    range: Annotated[float, Field(ge=0.0, le=1.0)]
    transition: Annotated[float, Field(ge=0.0, le=1.0)]


# ── API 응답 스키마 ────────────────────────────────────────────────────────────

class RegimeDetectionResponse(BaseModel):
    """장세 분석 응답.

    ApiResponse[RegimeDetectionResponse] 형태로 래핑하여 반환.
    """

    exchange: str = Field(description="거래소 식별자 (upbit | coinone | coinbase | binance)")
    market: str = Field(description="마켓 코드 (예: KRW-BTC)")
    regime: RegimeTypeStr = Field(description="분류된 장세 유형")
    confidence: Annotated[float, Field(ge=0.0, le=1.0, description="최고 장세 softmax 확률")]
    scores: RegimeScoresSchema = Field(description="장세별 확률 분포")
    signals: list[RuleSignalSchema] = Field(description="개별 규칙 판별 결과 목록")
    gpt_validated: bool = Field(description="GPT 보조 검증 수행 여부")
    gpt_agreement: bool | None = Field(None, description="GPT 동의 여부 (미수행 시 None)")
    cached: bool = Field(description="Redis 캐시 HIT 여부")
    analyzed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="분석 시각 (UTC)",
    )

    @classmethod
    def from_regime_result(
        cls,
        result: dict,
        exchange: str,
        market: str,
        *,
        cached: bool = False,
    ) -> "RegimeDetectionResponse":
        """RegimeResult TypedDict → Pydantic 변환 헬퍼."""
        return cls(
            exchange=exchange,
            market=market,
            regime=result["regime"],
            confidence=result["confidence"],
            scores=RegimeScoresSchema(**result["scores"]),
            signals=[RuleSignalSchema(**s) for s in result["signals"]],
            gpt_validated=result["gpt_validated"],
            gpt_agreement=result["gpt_agreement"],
            cached=cached,
        )

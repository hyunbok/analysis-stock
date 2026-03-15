# v1-16: AI 장세 분석 엔진 구현 설계서

> **작성**: project-architect + code-architect 공동 작성
> **최종 수정**: 2026-03-15
> **현재 상태**: 구현 완료 (코드 리뷰 통과, 58/58 테스트 통과)

---

## 1. 개요

`server/app/trading/regime/` 패키지를 구현한다.
기술적 지표(`trading/indicators/`)로부터 산출된 결과를 입력받아 장세를 **Trend / Range / Transition** 3가지로 분류하고, confidence score를 산출한다. 낮은 confidence 시 GPT 보조 검증을 수행한다.

### 1.1 핵심 원칙

- `trading/regime/` 내 규칙 기반 로직은 **순수 함수** — FastAPI/DB/Redis 의존 금지
- GPT 호출 모듈(`gpt_validator.py`)만 예외적으로 `openai` SDK 의존 허용 (I/O 바운드)
- 서비스 레이어(`RegimeService`)에서 캐싱/저장/오케스트레이션 담당

### 1.2 데이터 흐름

```
Candles (OHLCV)
  │
  ▼
calculate_all_indicators()          ← trading/indicators/calculator.py (기존)
  │
  ▼
IndicatorResult (TypedDict)
  │
  ▼
classify_regime()                   ← trading/regime/classifier.py (신규)
  │
  ├─ 1차 규칙 기반 분류 (ADX, EMA, MACD, RSI, BB)
  ├─ confidence score 계산 (가중치 기반 softmax)
  │
  ▼
RegimeResult (TypedDict)
  │
  ├─ confidence ≥ 0.7 AND regime ≠ Transition → 최종 결과
  │
  ├─ confidence < 0.7 OR Transition → GPT 검증 요청
  │     │
  │     ▼
  │   validate_with_gpt()           ← trading/regime/gpt_validator.py (신규)
  │     │
  │     ▼
  │   GPT 동의 → confidence +10%
  │   GPT 불일치 → confidence -15%
  │
  ▼
RegimeService.detect()              ← services/regime_service.py (신규)
  │
  ├─ Redis 캐시 저장 (regime:{exchange}:{market}, TTL 300s)
  ├─ MongoDB ai_decisions 저장 (기존 AiDecision 도큐먼트 활용)
  │
  ▼
최종 RegimeDetectionResponse
```

---

## 2. 패키지 디렉토리 구조

```
server/app/trading/
├── __init__.py                     # 기존 유지
├── indicators/                     # 기존 (v1-15)
│   ├── __init__.py
│   ├── types.py
│   ├── trend.py
│   ├── oscillator.py
│   ├── volatility.py
│   └── calculator.py
└── regime/                         # 신규 (v1-16)
    ├── __init__.py                 # public API: classify_regime, RegimeResult
    ├── types.py                    # TypedDict 타입 정의
    ├── rules.py                    # 개별 규칙 판별 함수 (ADX, EMA, MACD, RSI, BB)
    ├── classifier.py               # classify_regime() — 규칙 통합 + confidence 계산
    └── gpt_validator.py            # GPT 보조 검증 (openai SDK 의존)

server/app/services/
└── regime_service.py               # RegimeService (오케스트레이션, 캐싱, 저장)

server/app/schemas/
└── regime.py                       # API 응답 스키마 (Pydantic)

server/tests/unit/trading/regime/
├── test_rules.py                   # 규칙 함수 단위 테스트
├── test_classifier.py              # 분류기 통합 테스트
└── test_gpt_validator.py           # GPT 검증 모듈 테스트 (mock)

server/tests/unit/services/
└── test_regime_service.py          # 서비스 레이어 테스트
```

### 2.1 디렉토리 원칙

- `trading/regime/types.py`, `rules.py`, `classifier.py` — 순수 함수, `app.*` import 금지
- `trading/regime/gpt_validator.py` — `openai` SDK만 허용, `app.*` import 금지
- `services/regime_service.py` — DI 주입, 캐싱/저장/오케스트레이션

---

## 3. 타입 정의 (`trading/regime/types.py`)

```python
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
    scores: RegimeScores              # 장세별 확률 분포
    signals: list[RuleSignal]         # 개별 규칙 판별 결과 목록
    gpt_validated: bool               # GPT 검증 수행 여부
    gpt_agreement: bool | None        # GPT 동의 여부 (미수행 시 None)


# ── GPT 검증 입출력 ─────────────────────────────────────────────────────────────

class GptValidationInput(TypedDict):
    """GPT 검증 요청 입력."""
    regime: RegimeType
    confidence: float
    scores: RegimeScores
    signals: list[RuleSignal]
    indicators_summary: dict          # 주요 지표값 요약
    news_context: list[str] | None    # 뉴스 요약 최대 5건


class GptValidationResult(TypedDict):
    """GPT 검증 응답."""
    agrees: bool                      # 규칙 기반 결과 동의 여부
    suggested_regime: RegimeType      # GPT가 제안하는 장세
    reasoning: str                    # GPT 판단 근거 요약
    prompt_tokens: int
    completion_tokens: int
    model: str
```

---

## 4. 규칙 기반 분류 로직 (`trading/regime/rules.py`)

### 4.1 개별 규칙 함수

각 규칙 함수는 `IndicatorResult`를 입력받아 `RuleSignal | None`을 반환한다.
지표 값이 None이면 해당 규칙은 건너뛴다 (None 반환).

```python
def check_adx_strength(indicators: IndicatorResult) -> RuleSignal | None:
    """ADX 기반 추세 강도 판별.

    - ADX > 25: Trend (strength = min((adx - 25) / 25, 1.0))
    - ADX < 20: Range (strength = min((20 - adx) / 20, 1.0))
    - ADX 20~25: Transition (strength = 0.5)
    """

def check_ema_alignment(indicators: IndicatorResult) -> RuleSignal | None:
    """EMA 정배열/역배열 판별.

    - 정배열 (ema_20 > ema_50 > ema_200): Trend (상승), strength 1.0
    - 역배열 (ema_20 < ema_50 < ema_200): Trend (하락), strength 1.0
    - 부분 정렬: Transition, strength 0.5
    - 수렴 (모든 EMA 간 차이 < 0.5%): Range, strength 0.7
    """

def check_macd_momentum(indicators: IndicatorResult) -> RuleSignal | None:
    """MACD 히스토그램 방향성 판별.

    - 히스토그램 부호 일관 (양/음 연속): Trend
    - 크로스오버 임박 (|histogram| < |signal_line| * 0.1): Transition
    - 히스토그램 ≈ 0 (|histogram| < threshold): Range
    Note: 연속 3봉 증가/감소 판별은 candles 히스토리 필요 → 단일 시점에서는
          히스토그램 절대값과 부호로 대체 판별
    """

def check_rsi_regime(indicators: IndicatorResult) -> RuleSignal | None:
    """RSI 기반 장세 판별.

    - RSI 40~60: Range (strength = 1.0 - abs(rsi - 50) / 10)
    - RSI > 70 or RSI < 30: Trend (과매수/과매도 추세)
    - RSI 30~40 or 60~70: Transition
    """

def check_bollinger_regime(indicators: IndicatorResult) -> RuleSignal | None:
    """Bollinger Bandwidth 기반 장세 판별.

    - bandwidth < 임계값 (0.05): Range (좁은 밴드 → 횡보)
    - bandwidth > 0.15: Trend (넓은 밴드 → 추세)
    - %B < 0.05 or %B > 0.95: Transition (밴드 이탈 → 전환 가능)
    """
```

### 4.2 임계값 상수

```python
# ADX 임계값
ADX_TREND_THRESHOLD = 25.0
ADX_RANGE_THRESHOLD = 20.0

# Bollinger Bandwidth 임계값
BB_NARROW_THRESHOLD = 0.05      # 횡보 판별
BB_WIDE_THRESHOLD = 0.15        # 추세 판별

# RSI 구간
RSI_OVERBOUGHT = 70.0
RSI_OVERSOLD = 30.0
RSI_RANGE_UPPER = 60.0
RSI_RANGE_LOWER = 40.0

# EMA 수렴 판별 (가격 대비 비율)
EMA_CONVERGENCE_RATIO = 0.005   # 0.5%

# MACD 크로스오버 임박 비율
MACD_CROSSOVER_RATIO = 0.1
```

---

## 5. Confidence Score 계산 (`trading/regime/classifier.py`)

### 5.1 가중치 배분

| 규칙 | 가중치 | 근거 |
|------|--------|------|
| ADX 강도 | 0.30 | 추세 강도의 직접 지표 |
| EMA 배열 | 0.20 | 중장기 추세 방향성 |
| RSI 다이버전스 | 0.20 | 과매수/과매도 전환 신호 |
| MACD 크로스 | 0.15 | 모멘텀 변화 감지 |
| BB Bandwidth | 0.15 | 변동성 수준 |

### 5.2 계산 흐름

```python
def classify_regime(indicators: IndicatorResult) -> RegimeResult:
    """규칙 기반 장세 분류 + confidence 계산.

    1. 5개 규칙 함수 실행 → RuleSignal 리스트 수집
    2. 각 signal.regime 별 가중 합산:
       scores[signal.regime] += WEIGHTS[signal.name] * signal.strength
    3. None 규칙 제외 후 가중치 재정규화
    4. softmax(scores) → 확률 분포
    5. argmax → 선택된 regime, max → confidence

    Returns:
        RegimeResult (gpt_validated=False, gpt_agreement=None)
    """
```

### 5.3 Softmax 정규화

```python
import math

def _softmax(scores: dict[str, float]) -> dict[str, float]:
    """scores dict → 확률 분포 (합=1.0).

    temperature=1.0 사용. 모든 score가 0이면 균등 분배.
    """
    max_s = max(scores.values())
    exp_scores = {k: math.exp(v - max_s) for k, v in scores.items()}
    total = sum(exp_scores.values())
    return {k: v / total for k, v in exp_scores.items()}
```

### 5.4 가중치 재정규화

규칙 실행 결과 중 None(지표 데이터 부족)인 경우 해당 가중치를 나머지에 비례 배분:

```
예: ADX=None → ADX 0.30 제거 → 나머지 가중치 합 0.70 → 각각 /0.70 으로 재정규화
EMA: 0.20/0.70 ≈ 0.286, RSI: 0.20/0.70 ≈ 0.286, MACD: 0.15/0.70 ≈ 0.214, BB: 0.15/0.70 ≈ 0.214
```

활성 규칙이 2개 미만이면 confidence를 0.3으로 강제 하향 (신뢰도 부족).

---

## 6. GPT 보조 검증 (`trading/regime/gpt_validator.py`)

### 6.1 호출 조건

```python
NEEDS_GPT = confidence < 0.7 or regime == "transition"
```

### 6.2 구현 방식

- `openai` Python SDK (AsyncOpenAI) 사용
- API 키/모델은 함수 파라미터로 주입 (Config import 금지)
- 타임아웃: 10초
- 실패 시 GPT 검증 건너뜀 (원본 결과 유지, `gpt_validated=False`)

### 6.3 프롬프트 설계

```python
SYSTEM_PROMPT = """You are a cryptocurrency market analyst.
Analyze the given technical indicators and news context to determine the market regime.
Respond in JSON format only."""

def _build_user_prompt(input: GptValidationInput) -> str:
    """
    포함 정보:
    - 규칙 기반 분류 결과 (regime, confidence, scores)
    - 주요 지표 값 (ADX, RSI, MACD, EMA, BB bandwidth)
    - 개별 규칙 판별 결과 (signals)
    - 뉴스 컨텍스트 (최대 5건, 있는 경우)

    요청:
    1. 규칙 기반 결과에 동의하는가? (agree: true/false)
    2. 제안하는 장세 (suggested_regime: trend/range/transition)
    3. 판단 근거 (reasoning: 1~2문장)
    """
```

### 6.4 GPT 응답 파싱

```python
async def validate_with_gpt(
    input: GptValidationInput,
    *,
    api_key: str,
    model: str = "gpt-4o-mini",
    timeout: float = 10.0,
) -> GptValidationResult | None:
    """GPT 보조 검증 수행.

    Returns:
        GptValidationResult 또는 None (API 오류/타임아웃 시)
    """
```

- JSON mode (`response_format={"type": "json_object"}`) 사용
- 파싱 실패 시 None 반환 (fallback: 원본 결과 유지)

### 6.5 Confidence 조정

```python
if gpt_result is not None:
    if gpt_result["agrees"]:
        adjusted_confidence = min(confidence + 0.10, 1.0)
    else:
        adjusted_confidence = max(confidence - 0.15, 0.0)
```

---

## 7. 서비스 레이어 (`services/regime_service.py`)

### 7.1 클래스 설계

```python
class RegimeService:
    """장세 분석 오케스트레이션 서비스.

    DI 의존성:
    - MarketCacheService: Redis 캐시 (get/set_regime)
    - AICacheService: AI 결정 캐시 + Pub/Sub 발행
    - AsyncIOMotorDatabase: MongoDB ai_decisions 저장
    - Settings: OpenAI API 키/모델
    """

    def __init__(
        self,
        market_cache: MarketCacheService,
        ai_cache: AICacheService,
        mongodb: AsyncIOMotorDatabase,
        settings: Settings,
    ) -> None: ...

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
        """
```

### 7.2 캐시 전략

- **키**: `regime:{exchange}:{market}` (기존 `RedisKey.regime()` 재사용)
- **TTL**: 300초 (기존 `RedisTTL.REGIME` 재사용)
- **캐시 HIT 시**: 저장된 RegimeResult dict를 그대로 반환
- **force_refresh**: 캐시 무시, 재계산 강제

### 7.3 MongoDB 저장

기존 `AiDecision` 도큐먼트(`documents/trading_logs.py`)를 활용한다.

regime 분석 전용 필드 매핑:

| RegimeResult 필드 | AiDecision 필드 |
|---|---|
| regime | market_regime |
| scores | regime_confidence |
| gpt_validator 응답 | gpt_model, gpt_prompt_tokens, gpt_completion_tokens, gpt_raw_response, gpt_parsed_result |
| signals 요약 | gpt_parsed_result (signals 포함) |
| news_context | news_context_summary |

**Note**: `AiDecision`은 "AI 트레이딩 판단" 전체를 담는 도큐먼트이다. v1-16에서는 regime 분석 결과만 저장하므로, `selected_strategy`, `action`, `action_confidence` 등은 None/빈값으로 남긴다. 이 필드들은 v2(전략 선택 엔진)에서 채워진다.

→ **결정**: `AiDecision` 도큐먼트의 `selected_strategy`, `action`, `action_confidence` 필드를 Optional로 변경 필요 (현재 non-optional).

### 7.4 DI 등록 (`core/deps.py`)

```python
from app.core.pubsub import RedisPublisher

def get_market_cache_service(redis: Redis = Depends(get_redis)) -> MarketCacheService:
    return MarketCacheService(redis)

def get_ai_cache_service(
    redis: Redis = Depends(get_redis),
    pub_redis: Redis = Depends(get_pubsub_redis),
) -> AICacheService:
    publisher = RedisPublisher(pub_redis)
    return AICacheService(redis, publisher)

def get_regime_service(
    market_cache: MarketCacheService = Depends(get_market_cache_service),
    ai_cache: AICacheService = Depends(get_ai_cache_service),
    mongodb: AsyncIOMotorDatabase = Depends(get_mongodb),
    settings: Settings = Depends(get_settings),
) -> RegimeService:
    return RegimeService(market_cache, ai_cache, mongodb, settings)

RegimeServiceDep = Annotated[RegimeService, Depends(get_regime_service)]
```

---

## 8. 에러 핸들링

### 8.1 RegimeErrors 팩토리 (`core/exceptions.py`)

```python
class RegimeErrors:
    """장세 분석 도메인 에러 팩토리."""

    @staticmethod
    def insufficient_indicators() -> AppError:
        """장세 분류에 필요한 지표 데이터 부족 (활성 규칙 < 2개)."""
        return AppError(
            "REGIME_INSUFFICIENT_INDICATORS",
            "장세 분석에 필요한 지표 데이터가 부족합니다.",
            422,
        )

    @staticmethod
    def gpt_validation_failed() -> AppError:
        """GPT 검증 API 호출 실패 (로깅용, 실제로는 graceful fallback)."""
        return AppError(
            "REGIME_GPT_VALIDATION_FAILED",
            "AI 보조 검증에 실패했습니다. 규칙 기반 결과를 사용합니다.",
            200,  # 실패해도 결과 반환 (non-blocking)
        )

    @staticmethod
    def analysis_failed() -> AppError:
        """장세 분석 전체 실패."""
        return AppError(
            "REGIME_ANALYSIS_FAILED",
            "장세 분석에 실패했습니다. 잠시 후 재시도해주세요.",
            500,
        )
```

### 8.2 에러 처리 전략

- GPT 호출 실패: **non-blocking** — 규칙 기반 결과 그대로 반환, `gpt_validated=False`
- 지표 데이터 부족 (활성 규칙 < 2): `RegimeErrors.insufficient_indicators()` raise
- MongoDB 저장 실패: **fire-and-forget** — 로그만 기록, 결과 반환에 영향 없음
- Redis 캐시 실패: **fire-and-forget** — 로그만 기록, 재계산으로 대체

---

## 9. API 스키마 (`schemas/regime.py`)

### 9.1 엔드포인트 결정

**v1-16은 전용 REST API 엔드포인트를 추가하지 않는다.**

근거:
- PRD `api-spec.md` §5.1 에 regime 전용 엔드포인트 없음
- 장세 분석 엔진은 **AI 매매 파이프라인 내부 컴포넌트** — `ai-trading` 라우터 구현 시(v1-17+) 노출
- v1-16 범위: 엔진 + Redis/MongoDB 저장만

미래 확장 시 예상 엔드포인트:
```
GET /api/v1/ai-trading/regime?exchange=upbit&market=KRW-BTC
```
→ `api/v1/ai_trading.py` 라우터 생성 시 `RegimeDetectionResponse` 재사용

### 9.2 `schemas/regime.py` 전체 구현

```python
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
```

### 9.3 사용 패턴

**서비스 레이어 내부**:
```python
# RegimeService.detect() 반환값 — TypedDict 그대로 반환 (Pydantic 변환은 API 레이어에서)
result: RegimeResult = await self._classify_and_validate(...)
return result  # TypedDict
```

**미래 API 레이어 (v1-17+ ai_trading.py 라우터)**:
```python
@router.get("/regime", response_model=ApiResponse[RegimeDetectionResponse])
async def get_market_regime(
    exchange: str = Query(...),
    market: str = Query(...),
    service: RegimeServiceDep,
    _current_user: CurrentUser,
) -> ApiResponse[RegimeDetectionResponse]:
    result = await service.detect(exchange=exchange, market=market, ...)
    response = RegimeDetectionResponse.from_regime_result(result, exchange, market)
    return ApiResponse(data=response)
```

---

## 10. 기존 코드 변경 사항

### 10.1 `documents/trading_logs.py` — AiDecision 수정

```python
# 변경: non-optional → Optional (v1-16에서는 regime만 저장)
selected_strategy: Optional[str] = None    # was: str
action: Optional[str] = None               # was: str
action_confidence: Optional[Decimal128] = None  # was: Decimal128
gpt_model: Optional[str] = None            # was: str
gpt_prompt_tokens: Optional[int] = None    # was: int
gpt_completion_tokens: Optional[int] = None  # was: int
```

### 10.2 `core/deps.py` — DI 추가

- `get_market_cache_service()`, `get_ai_cache_service()`, `get_regime_service()` 추가
- `MarketCacheServiceDep`, `AICacheServiceDep`, `RegimeServiceDep` 타입 별칭 추가

### 10.3 `core/exceptions.py` — RegimeErrors 추가

---

## 11. 테스트 전략

### 11.1 단위 테스트 (순수 함수)

| 파일 | 테스트 대상 | 케이스 수 |
|------|------------|----------|
| `test_rules.py` | 5개 규칙 함수 × (정상/경계/None) | ~20 |
| `test_classifier.py` | classify_regime() 통합 | ~10 |
| `test_gpt_validator.py` | GPT 호출 mock | ~6 |

### 11.2 서비스 테스트

| 파일 | 테스트 대상 | 케이스 수 |
|------|------------|----------|
| `test_regime_service.py` | 캐시 HIT/MISS, GPT 호출 조건, MongoDB 저장 | ~8 |

### 11.3 총 예상 테스트 수: ~44건

### 11.4 핵심 테스트 시나리오

**ST1: 강한 상승 추세**
- ADX=35, EMA 정배열, RSI=65, MACD 양수 확대, BB bandwidth=0.12
- 기대: regime="trend", confidence ≥ 0.7

**ST2: 횡보장**
- ADX=15, EMA 수렴, RSI=50, MACD ≈ 0, BB bandwidth=0.03
- 기대: regime="range", confidence ≥ 0.7

**ST3: 전환 구간**
- ADX=22, EMA 부분 정렬, RSI=35, MACD 크로스오버 임박
- 기대: regime="transition", GPT 검증 트리거

**ST4: 지표 부족**
- ADX=None, EMA 일부 None
- 기대: 활성 규칙 ≥ 2이면 정상 동작, < 2이면 에러

**ST5: GPT 타임아웃**
- GPT 10초 초과
- 기대: gpt_validated=False, 규칙 기반 결과 반환

**ST6: 캐시 HIT**
- 동일 exchange/market 300초 내 재요청
- 기대: 캐시 결과 반환, GPT 미호출

---

## 12. 의존 라이브러리

| 라이브러리 | 버전 | 용도 | 신규/기존 |
|-----------|------|------|----------|
| openai | >=1.0 | GPT 보조 검증 | **신규** |
| pandas | 기존 | 지표 계산 (간접 의존) | 기존 |
| redis.asyncio | 기존 | 캐시 | 기존 |
| motor | 기존 | MongoDB | 기존 |

---

## 13. 서브태스크 매핑

| ST | 설명 | 구현 파일 | 의존 |
|----|------|----------|------|
| ST1 | 타입 정의 + 상수 | `regime/types.py` | - |
| ST2 | 규칙 함수 5개 | `regime/rules.py` | ST1 |
| ST3 | classify_regime() + softmax | `regime/classifier.py` | ST2 |
| ST4 | GPT 검증 모듈 | `regime/gpt_validator.py` | ST1 |
| ST5 | RegimeService + 캐싱/저장 | `services/regime_service.py`, deps.py, exceptions.py | ST3, ST4 |
| ST6 | __init__.py + 통합 정리 | `regime/__init__.py`, 기존 파일 수정 | ST3, ST4, ST5 |

---

## 14. 코드 아키텍처 검토 (code-architect)

> **작성**: code-architect
> **기존 코드 패턴 대조 및 누락 항목 보완**

### 14.1 기존 코드 패턴과의 일관성 확인

| 항목 | 기존 패턴 (`indicators/`) | v1-16 준수 여부 |
|------|--------------------------|----------------|
| TypedDict 기반 타입 | `CandleInput`, `IndicatorResult` | ✅ `RuleSignal`, `RegimeResult` |
| `from __future__ import annotations` | 모든 파일 | ✅ 유지 필요 |
| `logger = logging.getLogger(__name__)` | 모든 파일 | ✅ 유지 필요 |
| `__init__.py` public API 노출 | `calculate_all_indicators`, `CandleInput` | ⚠️ 아래 14.2 참조 |
| 함수 vs 클래스 | 순수 계산은 함수 | ⚠️ 태스크 스펙 `MarketRegimeDetector 클래스` 요구 — 아래 14.3 |
| 오류 시 None 반환 | `_last_value()` 패턴 | ✅ `RuleSignal | None` |

### 14.2 `__init__.py` public API 정의 (누락 보완)

```python
"""장세 분류 엔진.

순수 계산 패키지 — FastAPI / DB / Redis 의존성 금지.
GPT 검증은 services/ 레이어에서 처리.
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
```

### 14.3 MarketRegimeDetector 클래스 추가 (`regime/detector.py` 신규)

태스크 스펙 요구사항: `MarketRegimeDetector 클래스 — 입력: candles, indicators, news_context`.
`classify_regime()` 함수를 래핑하는 클래스 어댑터를 **추가 파일**로 분리한다.

```python
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
```

**디렉토리 최종 구조 (업데이트)**:

```
server/app/trading/regime/
├── __init__.py        # public API
├── types.py           # TypedDicts + 상수
├── rules.py           # 개별 규칙 함수 (check_adx_strength 등)
├── classifier.py      # classify_regime() + softmax
├── detector.py        # MarketRegimeDetector 클래스 (신규 추가)
└── gpt_validator.py   # GPT 보조 검증
```

### 14.4 GPT Validator 위치 결정

`gpt_validator.py`의 위치에 대한 트레이드오프:

| 위치 | 장점 | 단점 |
|------|------|------|
| `trading/regime/gpt_validator.py` | regime 모듈 응집도 높음 | `trading/` 순수성 원칙 위반 (`openai` 의존) |
| `services/regime_service.py` 내부 메서드 | 인프라 의존 격리 | 서비스 파일 비대화 |

**결정**: `trading/regime/gpt_validator.py` 유지 (project-architect 설계 채택).
근거: 규칙 기반 분류와 GPT 검증은 같은 도메인 로직 — `openai` SDK는 순수 I/O 바운드, DB/Redis와 달리 계산 패키지 내 허용 예외로 인정.

`regime/__init__.py`의 독립성 원칙 주석에 이를 명시:
```python
# 주의: gpt_validator.py는 openai SDK에 의존함.
# openai는 외부 AI API 클라이언트로, DB/Redis와 달리 인프라 결합 없음 — 허용 예외.
```

### 14.5 MongoDB 저장 전략 결정

**검토**: 기존 `AiDecision` 재사용 vs 신규 `MarketRegimeSnapshot` 생성

`AiDecision` 도큐먼트 현황:
- `user_id: UUID` (required), `selected_strategy: str` (required), `action: str` (required), `action_confidence: Decimal128` (required) 등 per-user 매매 결정 필드가 다수.
- 장세 분석은 시장 공통 데이터 — `user_id` 불필요.

**결정**: project-architect 초안대로 `AiDecision` 재사용 채택.
근거:
1. 신규 컬렉션 생성은 `core/mongodb.py` Beanie 초기화 변경 + 인덱스 관리 비용 추가.
2. v1-16은 장세 분석이 목표 — MongoDB 저장은 이력 추적 용도.
3. `selected_strategy`, `action`, `action_confidence` 를 Optional로 변경하면 기존 AiDecision 쿼리에 영향 없음.

**필수 변경**: `documents/trading_logs.py` `AiDecision` 도큐먼트 — 아래 필드 Optional화:
```python
selected_strategy: Optional[str] = None
action: Optional[str] = None
action_confidence: Optional[Decimal128] = None
gpt_model: Optional[str] = None
gpt_prompt_tokens: Optional[int] = None
gpt_completion_tokens: Optional[int] = None
```

### 14.6 RegimeType 값 대소문자 확인

기존 `AiDecision.market_regime` 주석: `# trend/range/transition` (소문자).
**결정**: 소문자 `"trend" | "range" | "transition"` 통일 (project-architect 초안 채택).

### 14.7 기존 AiDecision 인덱스 호환성

`AiDecision.regime_confidence` 현재 타입: `dict` (비구조화).
`RegimeScores` TypedDict는 JSON 직렬화 시 `dict[str, float]` — **호환됨**, 변경 불필요.

### 14.8 Redis 키 확인

`core/redis_keys.py` 기존 정의 (변경 불필요):
```python
RedisKey.regime(exchange, market)  # → "regime:{exchange}:{market}"
RedisTTL.REGIME = 300              # → 5분 ✅
```

### 14.9 Settings 추가 항목

`core/config.py` 확인 결과:
- `OPENAI_API_KEY` — 이미 존재
- `OPENAI_MODEL = "gpt-4o-mini"` — 이미 존재, **regime 검증에 재사용** (별도 `OPENAI_REGIME_MODEL` 불필요)

**신규 추가 항목 1개만**:
```python
OPENAI_TIMEOUT: float = 10.0  # GPT 호출 타임아웃 (초), v1-16 신규
```

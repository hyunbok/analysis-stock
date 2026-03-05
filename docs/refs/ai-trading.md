# CoinTrader - AI 자동매매 시스템

> 원본: docs/prd.md §7 기준. 최종 갱신: 2026-03-05

---

## 7.1 전체 흐름

5단계 파이프라인으로 구성된다.

```
Celery Beat (5분 주기)
    ┌─────────────────────────────────────────────────────────────┐
    │  Stage 1: 데이터 수집 (Data Collection)                       │
    │  - 거래소 API: 2일치 5분봉 캔들 (~576개)                       │
    │  - 거래소 API: 현재 호가/틱 데이터                              │
    │  - MongoDB: 최근 뉴스 데이터 (news_data)                       │
    │  - Redis: 최근 실시간 시세 스냅샷                               │
    │  - PostgreSQL: 사용자 AI 설정 (ai_trading_configs)             │
    └──────────────────────┬──────────────────────────────────────┘
                           ▼
    ┌─────────────────────────────────────────────────────────────┐
    │  Stage 2: 전처리 및 지표 계산 (Preprocessing)                  │
    │  - 캔들 데이터 정규화 (거래소별 포맷 통일)                       │
    │  - 기술적 지표 계산 (11종): EMA, VWAP, RSI, MACD, BB, ADX,   │
    │    ATR, Stochastic, OBV, Williams %R, CCI                    │
    │  - 뉴스 감성 점수 산출 (GPT 또는 룰 기반)                       │
    │  - 결측값/이상치 필터링                                        │
    └──────────────────────┬──────────────────────────────────────┘
                           ▼
    ┌─────────────────────────────────────────────────────────────┐
    │  Stage 3: 장세 분석 (Market Regime Detection)                  │
    │  - 기술적 지표 기반 장세 1차 분류 (규칙 기반)                    │
    │  - GPT 보조 분석 (뉴스 + 지표 종합 판단)                        │
    │  - 최종 장세 결정: Trend / Range / Transition                  │
    │  - 각 장세별 confidence score(%) 산출                         │
    └──────────────────────┬──────────────────────────────────────┘
                           ▼
    ┌─────────────────────────────────────────────────────────────┐
    │  Stage 4: 전략 선택 및 매매 결정 (Strategy & Decision)          │
    │  - 장세 → 전략 매핑 (confidence 임계값 기반)                    │
    │  - 선택된 전략의 진입/청산 조건 평가                             │
    │  - 리스크 관리 검증 (포지션 크기, 손절/익절, 일일 한도)            │
    │  - 매매 신호 생성: BUY / SELL / HOLD                          │
    └──────────────────────┬──────────────────────────────────────┘
                           ▼
    ┌─────────────────────────────────────────────────────────────┐
    │  Stage 5: 주문 실행 및 기록 (Execution & Logging)              │
    │  - Exchange Abstraction Layer를 통한 주문 실행                  │
    │  - PostgreSQL: trade_orders 기록                              │
    │  - MongoDB: trade_logs (AI 판단 근거 포함) 기록                 │
    │  - 사용자 알림 (WS + 푸시)                                    │
    └─────────────────────────────────────────────────────────────┘
```

## 7.2 마스터 스위치

- users 테이블의 `ai_trading_enabled`로 전체 AI 매매 ON/OFF 제어
- OFF 시 모든 코인별 AI 매매 일괄 중지 (안전장치)
- 클라이언트: 다음 분석까지 카운트다운 타이머 표시

## 7.3 장세 분석

- **입력**: 뉴스 데이터, 2일치 5분봉(~576캔들), 기술적 지표 11종
- **출력**: Trend(추세) / Range(횡보) / Transition(전환) + 각 장세별 confidence score(%)

### 7.3.1 기술적 지표 상세

**1. EMA (Exponential Moving Average)**
- EMA 20 (단기), EMA 50 (중기), EMA 200 (장기)
- 매수: EMA20 > EMA50 > EMA200 (정배열) + 가격 EMA20 위 반등
- 매도: 역배열 + 가격 EMA20 아래

**2. VWAP (Volume Weighted Average Price)**
- `VWAP = Σ(TP × Volume) / Σ(Volume)`, 밴드: VWAP ± (1.5 × σ)
- 당일 KST 00:00 기준 리셋

**3. RSI (Relative Strength Index)**
- 기간 14, 과매수 70, 과매도 30
- 다이버전스 탐지: 최근 20~50캔들 가격-RSI 비교

**4. MACD**
- MACD Line = EMA(12) - EMA(26), Signal = EMA(9) of MACD, Histogram = MACD - Signal

**5. Bollinger Bands**
- Middle = SMA(20), Upper/Lower = SMA(20) ± (2 × σ)
- %B, Bandwidth 활용

**6. ADX (Average Directional Index)**
- 강한 추세: ADX > 25, 횡보: ADX < 20, 전환: 20~25

### 7.3.2 추가 지표

| 지표 | 기본 파라미터 | 도입 근거 |
|------|-------------|----------|
| **ATR** | 14기간 | 변동성 기반 동적 손절/익절 |
| **Stochastic** | 14/3, 과매수 80, 과매도 20 | Range 단기 반전 포착 |
| **OBV** | EMA 20 | 거래량 뒷받침 확인 |
| **Williams %R** | 14, -20/-80 | RSI+볼밴 보완 |
| **CCI** | 20, ±100 | VWAP 밴드 반전 보조 |

### 7.3.3 복합 시그널 스코어링 (-1.0 ~ +1.0)

| 카테고리 | 지표 (가중치) |
|---------|-------------|
| **추세** | EMA 배열(2.0), ADX 강도(1.5), VWAP 위치(1.5) |
| **모멘텀** | MACD 크로스(2.0), RSI(1.5), 히스토그램(1.0), Stochastic(1.0) |
| **반전** | RSI 다이버전스(2.5), 반전 캔들(2.0), BB 터치(1.5), Williams %R(1.0) |
| **거래량** | OBV 방향(1.5), 거래량 급증(1.0) |

Strong Buy > +0.6 / Medium +0.3~+0.6 / Weak +0.1~+0.3 / Neutral ±0.1

### 7.3.4 장세 분류 알고리즘

| 장세 | 조건 (AND) |
|------|-----------|
| **Trend** | ADX > 25 AND (EMA 정/역배열 OR MACD 히스토그램 연속 증가/감소 3봉 이상) |
| **Range** | ADX < 20 AND BB Bandwidth < 임계값 AND RSI 40~60 |
| **Transition** | RSI 다이버전스 감지 OR MACD 크로스오버 임박 OR ADX 20~25 급변 |

Confidence Score: ADX(30%) + EMA 배열(20%) + MACD 크로스(15%) + RSI 다이버전스(20%) + BB Bandwidth(15%) → softmax 정규화

### 7.3.5 장세 → 전략 연결

```
confidence >= 70% → 해당 장세 전용 전략 실행 (풀 포지션)
50% <= confidence < 70% → 보수적 전략 (포지션 50% 축소)
confidence < 50% → HOLD (매매 보류)
```

## 7.4 장세별 전략

| 장세 | 전략 | 핵심 |
|------|------|------|
| Trend | TrendMA 눌림목, VWAP 눌림목 | MA/VWAP 지지 반등 매매 |
| Range | VWAP 밴드 반전, RSI+볼밴+반전캔들 | 밴드 경계 반전 매매 |
| Transition | RSI 다이버전스 + MACD | 추세 전환 포착 |

### 전략별 진입/청산 조건

**A: TrendMA 눌림목** — EMA 정배열 + ADX>25 + EMA20 근접 반등 양봉 + 거래량≥1.2배 + RSI 40~65. 청산: 익절 ATR×2.0 / 손절 EMA50 이탈 또는 ATR×1.5 / RR 1:2

**B: VWAP 눌림목** — 가격>VWAP + ADX>20 + VWAP±0.3% 터치 + 반전캔들 + RSI 40~65 + OBV↑. 청산: 익절 VWAP 상단밴드 또는 ATR×2.0 / 손절 VWAP-ATR×0.5 / RR 1:2

**C: VWAP 밴드 반전** — ADX<20 + BB 수축 + VWAP 하단밴드 터치 + 반전캔들 + RSI<40 + %B<0.1. 청산: 익절 VWAP 중심선 / 손절 밴드 이탈+ATR×0.5 / RR 1:1.5

**D: RSI+볼밴+반전캔들 3중 조건** — RSI(14)<30 + Stochastic %K<20, BB Lower 터치 + %B<0.05, 반전캔들 (3조건 동시 충족). 청산: 익절 BB Middle / 손절 BB 이탈+ATR×1.0 / RR 1:1.5~2.0

**E: RSI 다이버전스+MACD 확정** — RSI Bullish Divergence + MACD Golden Cross + 히스토그램 양전환 + ADX<25 + OBV↑. 청산: 익절 ATR×2.5 / 손절 다이버전스 저점 이탈 / RR 1:2.5

### 반전 캔들 패턴

| 패턴 | 판별 조건 |
|------|----------|
| 해머 | 아래꼬리 >= 몸통×2, 위꼬리 <= 몸통×0.5 |
| Bullish Engulfing | 직전 음봉, 현재 양봉이 직전을 완전 감쌈 |
| Shooting Star | 위꼬리 >= 몸통×2, 아래꼬리 <= 몸통×0.5 |
| Bearish Engulfing | 직전 양봉, 현재 음봉이 직전을 완전 감쌈 |
| 도지 | 몸통 <= 전체범위의 10% |

## 7.5 리스크 관리

| 항목 | 기본값 | 범위 |
|------|-------|------|
| 단일 거래 최대 손실 | 2% | 0.5~5% |
| 일일 최대 손실 | 5% | 1~10% |
| 총 최대 낙폭 (MDD) | 15% | 5~30% |
| 최대 동시 포지션 | 3 | 1~5 |
| 최대 투자 비율 (단일) | 10% | 2~20% |
| 연속 손실 한도 | 3 | 1~5 |

**포지션 사이징**: Fixed Fractional 기본, Half-Kelly 보조. 둘 중 보수적 값 채택. Confidence/시그널 강도 추가 조정 (Strong×1.0, Medium×0.75, Weak×0.5)

**동적 손절/익절 (ATR 기반)**:

| 전략 | 손절 ATR배수 | 익절 ATR배수 | RR |
|------|------------|------------|-----|
| TrendMA / VWAP 눌림목 | 1.5 | 3.0 | 1:2 |
| VWAP 밴드 / RSI+볼밴 | 1.0 | 1.5 | 1:1.5 |
| RSI 다이버전스+MACD | 1.5 | 3.75 | 1:2.5 |

Trailing Stop: 익절 50% 도달 시 활성화, ATR×1.0

**드로다운 관리**: 일일 -5% → 당일 중지 / 총 -15% → 일시 정지 / 연속 3회 손실 → 4시간 쿨다운

## 7.6 통계

- 매매 로그: 진입/청산 가격, 전략, AI 판단 근거
- 일별 통계: 거래 횟수, 승률, 총 손익, AI vs 수동 분리, 장세별/전략별 성과
- 누적 통계: 총 수익률, 샤프 비율, MDD, 최선/최악 거래

## 7.7 멀티 타임프레임 분석

| 타임프레임 | 역할 |
|-----------|------|
| 5분봉 (Primary) | 메인 진입 |
| 15분봉 (Confirmation) | 5분봉 시그널 방향 확인 |
| 1시간봉 (Trend) | 상위 추세 방향 |
| 4시간봉 (Major) | 주요 추세 방향 |
| 일봉 (Context) | 시장 전체 강도 |

MTF 규칙: 1h+4h 같은 방향→허용(1.0) / 한쪽만→허용(0.75) / 둘 다 반대→차단 / 둘 다 neutral→허용(0.5, 축소)

## 7.8 Celery 워커 구조

```
FastAPI Server ◄──► Redis (Broker+Result+Pub/Sub) ◄──► Celery Worker
                                                         ├─ ai_trading (ai 큐)
                                                         ├─ news_scraper (scraper 큐)
                                                         └─ reports (default 큐)
```

| 태스크 | 주기 | 큐 |
|--------|------|-----|
| AI 매매 사이클 | 5분 | ai |
| 뉴스 스크랩 | 1시간 | scraper |
| 일별 PnL 리포트 | 매일 00:00 UTC | default |
| 만료 토큰 정리 | 매일 03:00 UTC | default |

Worker: `--concurrency=4`, 전체 240s(soft)/300s(hard), 개별 코인 90s/120s, 재시도 2회(30s backoff)

## 7.9 주문 실행 예외 처리

```
PENDING → FILLED (전량) / PARTIAL → 60초 대기 → FILLED or CANCELLED / OPEN → 120초 대기
       → API 실패 → RETRY (최대 2회, 30초 backoff) → FILLED or FAILED
```

## 7.10 GPT 연동

GPT는 **보조 분석 도구**로 활용, 최종 매매 결정은 규칙 기반 엔진이 수행.

| 역할 | 호출 시점 | 필수 여부 |
|------|----------|----------|
| 장세 검증 | Stage 3 (confidence < 70% 또는 Transition 시) | 선택적 |
| 뉴스 감성 분석 | Stage 2 | 선택적 |
| 매매 판단 보조 | Stage 4 (고위험 거래) | 선택적 |

- 모델: `OPENAI_MODEL` 환경변수 (기본 gpt-4o-mini)
- 타임아웃 30초, 사용자당 일 50회, 토큰 최대 2000/요청
- Fallback: GPT 실패 → 규칙 기반만 사용
- GPT 동의→confidence +10(최대100), 불일치→-15(50 미만 시 HOLD)

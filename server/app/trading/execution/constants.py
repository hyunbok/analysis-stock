"""리스크 관리 상수 (PRD §7.5, §7.6).

기본값 — 실제 동작은 RiskParams(AiTradingConfig에서 추출)에 의존.
PositionSizer, DynamicStopLoss에서 fallback으로 참조.
"""

# ── 리스크 한도 (기본값) ─────────────────────────────────────────────────────

DEFAULT_MAX_SINGLE_LOSS_RATIO = 0.02     # 단일 손실 한도 2%
DEFAULT_DAILY_MAX_LOSS_RATIO = 0.05      # 일일 손실 한도 5%
DEFAULT_MDD_LIMIT_RATIO = 0.15           # 최대 낙폭 한도 15%
DEFAULT_MAX_ACTIVE_POSITIONS = 3         # 최대 동시 포지션
DEFAULT_MAX_INVESTMENT_RATIO = 0.10      # 단일 투자비율 한도 10%
DEFAULT_MAX_CONSECUTIVE_LOSSES = 3       # 연속 손실 한도

# ── 포지션 사이징 ────────────────────────────────────────────────────────────

KELLY_HALF_FACTOR = 0.5                  # Half-Kelly = Kelly × 0.5
DEFAULT_WIN_RATE = 0.5                   # 초기 승률 추정치
DEFAULT_RR_RATIO = 1.5                   # 초기 RR 비율 추정치

# ── 신호 강도 배수 (PRD §7.5.2) ──────────────────────────────────────────────

SIGNAL_MULTIPLIER: dict[str, float] = {
    "strong": 1.0,
    "moderate": 0.75,
    "weak": 0.5,
}

# ── Trailing Stop (PRD §7.6) ────────────────────────────────────────────────

TRAILING_TRIGGER_RATIO = 0.5             # 익절 50% 도달 시 활성화
TRAILING_STOP_ATR_MULT = 1.0             # ATR × 1.0 추적 거리

# ── 쿨다운 ───────────────────────────────────────────────────────────────────

COOLDOWN_SECONDS = 4 * 3600              # 연속 손실 후 4시간 쿨다운

# ── 부분 체결 ────────────────────────────────────────────────────────────────

PARTIAL_FILL_WAIT_SECONDS = 60           # 부분 체결 대기 시간
PARTIAL_FILL_POLL_INTERVAL = 10          # 상태 확인 간격 (초)

# ── 재시도 ───────────────────────────────────────────────────────────────────

MAX_RETRY_COUNT = 2                      # 최대 재시도 횟수 (총 3회 시도)
RETRY_INTERVAL_SECONDS = 30              # 재시도 간격 (초)

# ── Redis ────────────────────────────────────────────────────────────────────

DRAWDOWN_HASH_TTL = 48 * 3600            # 48시간 (Hash TTL)
POSITIONS_SET_TTL = 24 * 3600            # 24시간 (열린 포지션 Set TTL)

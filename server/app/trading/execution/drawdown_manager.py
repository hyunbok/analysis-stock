"""드로다운 관리 — Redis Hash 기반 상태 저장/조회.

단일 Hash 키: trading:drawdown:{user_id}:{exchange_account_id}
TTL: 48시간 (갱신 시 리셋)
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from redis.asyncio import Redis

from app.core.redis_keys import RedisKey

from .constants import (
    COOLDOWN_SECONDS,
    DEFAULT_MAX_CONSECUTIVE_LOSSES,
    DRAWDOWN_HASH_TTL,
    POSITIONS_SET_TTL,
)
from .types import DrawdownState

logger = logging.getLogger(__name__)


_DEFAULT_STATE = DrawdownState(
    daily_loss_ratio=0.0,
    mdd_ratio=0.0,
    consecutive_losses=0,
    is_suspended=False,
    cooldown_until=None,
    peak_balance=0.0,
    detail="초기 상태",
)


def _parse_state(raw: dict[bytes, bytes]) -> DrawdownState:
    """Redis HGETALL 결과 → DrawdownState 변환."""
    def _f(key: str, default: float = 0.0) -> float:
        val = raw.get(key.encode()) or raw.get(key)
        return float(val) if val else default

    def _i(key: str, default: int = 0) -> int:
        val = raw.get(key.encode()) or raw.get(key)
        return int(val) if val else default

    def _b(key: str) -> bool:
        val = raw.get(key.encode()) or raw.get(key)
        if val is None:
            return False
        return val in (b"1", "1", 1)

    def _s(key: str) -> str | None:
        val = raw.get(key.encode()) or raw.get(key)
        if val is None:
            return None
        decoded = val.decode() if isinstance(val, bytes) else str(val)
        return decoded if decoded else None

    detail_raw = raw.get(b"detail") or raw.get("detail")
    detail = (detail_raw.decode() if isinstance(detail_raw, bytes) else str(detail_raw)) if detail_raw else "Redis 조회"

    return DrawdownState(
        daily_loss_ratio=_f("daily_loss_ratio"),
        mdd_ratio=_f("mdd_ratio"),
        consecutive_losses=_i("consecutive_losses"),
        is_suspended=_b("is_suspended"),
        cooldown_until=_s("cooldown_until"),
        peak_balance=_f("peak_balance"),
        detail=detail,
    )


class DrawdownManager:
    """드로다운 상태 관리 (Redis Hash).

    Redis 키 패턴:
    - trading:drawdown:{user_id}:{exchange_account_id}  (Hash, TTL=48h)
      fields: daily_loss_ratio, mdd_ratio, consecutive_losses,
              is_suspended, cooldown_until, peak_balance

    - trading:positions:{user_id}:{exchange_account_id}  (Set of order_ids, TTL=24h)
    """

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def get_state(
        self,
        user_id: str,
        exchange_account_id: str,
    ) -> DrawdownState:
        """현재 드로다운 상태 조회 (Redis HGETALL).

        키 미존재 시 기본값(0/false) 반환.
        """
        key = RedisKey.drawdown(user_id, exchange_account_id)
        raw: dict = await self._redis.hgetall(key)
        if not raw:
            logger.debug("drawdown key not found, returning defaults: %s", key)
            return DrawdownState(**_DEFAULT_STATE)
        return _parse_state(raw)

    async def record_trade_result(
        self,
        user_id: str,
        exchange_account_id: str,
        pnl_ratio: float,
        current_balance: Decimal,
    ) -> DrawdownState:
        """거래 결과 기록 + 드로다운 상태 업데이트.

        수익: consecutive_losses 리셋.
        손실: daily_loss_ratio += |pnl_ratio|, consecutive_losses += 1, MDD 갱신.
        연속 3회 손실: cooldown_until 설정 + is_suspended=True.
        """
        key = RedisKey.drawdown(user_id, exchange_account_id)
        raw: dict = await self._redis.hgetall(key)
        state = _parse_state(raw) if raw else DrawdownState(**_DEFAULT_STATE)

        current_bal = float(current_balance)
        peak = max(state["peak_balance"], current_bal)

        if pnl_ratio >= 0:
            # 수익 — consecutive_losses 리셋
            consecutive_losses = 0
            daily_loss_ratio = state["daily_loss_ratio"]
            is_suspended = False
            cooldown_until = None
        else:
            # 손실
            loss = abs(pnl_ratio)
            daily_loss_ratio = state["daily_loss_ratio"] + loss
            consecutive_losses = state["consecutive_losses"] + 1
            is_suspended = state["is_suspended"]
            cooldown_until = state["cooldown_until"]

        # MDD 계산 (고점 대비 현재)
        mdd_ratio = (peak - current_bal) / peak if peak > 0 else 0.0

        # 연속 손실 한도 초과 시 쿨다운
        if pnl_ratio < 0 and consecutive_losses >= DEFAULT_MAX_CONSECUTIVE_LOSSES:
            is_suspended = True
            cooldown_until = (
                datetime.now(UTC) + timedelta(seconds=COOLDOWN_SECONDS)
            ).isoformat()
            logger.warning(
                "drawdown: consecutive_losses=%d, suspension activated until %s",
                consecutive_losses,
                cooldown_until,
            )

        new_state = DrawdownState(
            daily_loss_ratio=daily_loss_ratio,
            mdd_ratio=mdd_ratio,
            consecutive_losses=consecutive_losses,
            is_suspended=is_suspended,
            cooldown_until=cooldown_until,
            peak_balance=peak,
            detail=f"pnl={pnl_ratio:.4f} balance={current_bal:.0f}",
        )
        await self._save_state(key, new_state)
        return new_state

    async def _save_state(self, key: str, state: DrawdownState) -> None:
        """Hash 저장 + TTL 갱신."""
        mapping = {
            "daily_loss_ratio": str(state["daily_loss_ratio"]),
            "mdd_ratio": str(state["mdd_ratio"]),
            "consecutive_losses": str(state["consecutive_losses"]),
            "is_suspended": "1" if state["is_suspended"] else "0",
            "cooldown_until": state["cooldown_until"] or "",
            "peak_balance": str(state["peak_balance"]),
            "detail": state["detail"],
        }
        await self._redis.hset(key, mapping=mapping)
        await self._redis.expire(key, DRAWDOWN_HASH_TTL)

    async def get_active_position_count(
        self,
        user_id: str,
        exchange_account_id: str,
    ) -> int:
        """열린 포지션 수 조회 (Redis Set SCARD)."""
        key = RedisKey.positions(user_id, exchange_account_id)
        count = await self._redis.scard(key)
        return int(count)

    async def add_position(
        self,
        user_id: str,
        exchange_account_id: str,
        order_id: str,
    ) -> None:
        """열린 포지션 추가 (Redis SADD)."""
        key = RedisKey.positions(user_id, exchange_account_id)
        await self._redis.sadd(key, order_id)
        await self._redis.expire(key, POSITIONS_SET_TTL)

    async def remove_position(
        self,
        user_id: str,
        exchange_account_id: str,
        order_id: str,
    ) -> None:
        """포지션 제거 (Redis SREM, 체결/취소 시)."""
        key = RedisKey.positions(user_id, exchange_account_id)
        await self._redis.srem(key, order_id)

    async def reset_daily(
        self,
        user_id: str,
        exchange_account_id: str,
    ) -> None:
        """일일 손실 리셋 (KST 00:00, 스케줄러/Celery에서 호출)."""
        key = RedisKey.drawdown(user_id, exchange_account_id)
        raw: dict = await self._redis.hgetall(key)
        if not raw:
            return
        state = _parse_state(raw)
        state = DrawdownState(
            daily_loss_ratio=0.0,
            mdd_ratio=state["mdd_ratio"],
            consecutive_losses=state["consecutive_losses"],
            is_suspended=state["is_suspended"],
            cooldown_until=state["cooldown_until"],
            peak_balance=state["peak_balance"],
            detail="일일 손실 리셋",
        )
        await self._save_state(key, state)
        logger.info("drawdown daily_loss_ratio reset for %s/%s", user_id, exchange_account_id)

    async def set_suspension(
        self,
        user_id: str,
        exchange_account_id: str,
        reason: str,
        cooldown_seconds: int = COOLDOWN_SECONDS,
    ) -> None:
        """자동 중지 + 쿨다운 설정."""
        key = RedisKey.drawdown(user_id, exchange_account_id)
        raw: dict = await self._redis.hgetall(key)
        state = _parse_state(raw) if raw else DrawdownState(**_DEFAULT_STATE)

        cooldown_until = (
            datetime.now(UTC) + timedelta(seconds=cooldown_seconds)
        ).isoformat()

        new_state = DrawdownState(
            daily_loss_ratio=state["daily_loss_ratio"],
            mdd_ratio=state["mdd_ratio"],
            consecutive_losses=state["consecutive_losses"],
            is_suspended=True,
            cooldown_until=cooldown_until,
            peak_balance=state["peak_balance"],
            detail=f"수동 정지: {reason}",
        )
        await self._save_state(key, new_state)
        logger.warning(
            "drawdown: suspension set for %s/%s reason=%s until=%s",
            user_id, exchange_account_id, reason, cooldown_until,
        )

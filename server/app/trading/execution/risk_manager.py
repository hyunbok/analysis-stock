"""리스크 관리자 — 거래 사전 검증.

순수 계산 — Redis/DB 의존 없음.
DrawdownState(현재 상태) + RiskParams(한도) 입력 → RiskCheckResult 출력.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime

from .types import DrawdownState, RiskCheckResult, RiskParams

logger = logging.getLogger(__name__)


class RiskManager:
    """리스크 사전 검증 — 순수 계산.

    검증 순서:
    1. 쿨다운 확인 (연속 손실 후 4시간)
    2. 일일 손실 한도 (기본 5%)
    3. MDD 한도 (기본 15%)
    4. 동시 포지션 수 (기본 3개)
    """

    def check(
        self,
        state: DrawdownState,
        params: RiskParams,
        active_position_count: int,
    ) -> RiskCheckResult:
        """전체 리스크 검증 수행.

        Args:
            state: DrawdownManager에서 조회한 현재 드로다운 상태.
            params: AiTradingConfig에서 추출한 리스크 파라미터.
            active_position_count: 현재 열린 포지션 수.

        Returns:
            RiskCheckResult: allowed=True면 거래 가능, False면 차단 + reason.
        """
        base = {
            "daily_loss_ratio": state["daily_loss_ratio"],
            "mdd_ratio": state["mdd_ratio"],
            "consecutive_losses": state["consecutive_losses"],
            "active_position_count": active_position_count,
        }

        # 1. 쿨다운 확인
        if state["is_suspended"] and state["cooldown_until"]:
            try:
                cooldown_dt = datetime.fromisoformat(state["cooldown_until"])
                if cooldown_dt > datetime.now(UTC):
                    logger.debug(
                        "risk_check: cooldown active until %s", state["cooldown_until"]
                    )
                    return RiskCheckResult(
                        allowed=False,
                        reason=f"쿨다운 활성 (해제: {state['cooldown_until']})",
                        **base,
                    )
            except ValueError:
                logger.warning("invalid cooldown_until format: %s", state["cooldown_until"])

        # 2. 일일 손실 한도
        if state["daily_loss_ratio"] >= params["daily_max_loss_ratio"]:
            logger.debug(
                "risk_check: daily_loss %.4f >= limit %.4f",
                state["daily_loss_ratio"],
                params["daily_max_loss_ratio"],
            )
            return RiskCheckResult(
                allowed=False,
                reason=(
                    f"일일 손실 한도 초과 "
                    f"({state['daily_loss_ratio']:.2%} >= {params['daily_max_loss_ratio']:.2%})"
                ),
                **base,
            )

        # 3. MDD 한도
        if state["mdd_ratio"] >= params["mdd_limit_ratio"]:
            logger.debug(
                "risk_check: mdd %.4f >= limit %.4f",
                state["mdd_ratio"],
                params["mdd_limit_ratio"],
            )
            return RiskCheckResult(
                allowed=False,
                reason=(
                    f"MDD 한도 초과 "
                    f"({state['mdd_ratio']:.2%} >= {params['mdd_limit_ratio']:.2%})"
                ),
                **base,
            )

        # 4. 동시 포지션 수
        if active_position_count >= params["max_active_positions"]:
            logger.debug(
                "risk_check: positions %d >= max %d",
                active_position_count,
                params["max_active_positions"],
            )
            return RiskCheckResult(
                allowed=False,
                reason=(
                    f"최대 포지션 도달 "
                    f"({active_position_count} >= {params['max_active_positions']})"
                ),
                **base,
            )

        return RiskCheckResult(allowed=True, reason="OK", **base)

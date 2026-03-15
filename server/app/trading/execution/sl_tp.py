"""동적 손절/익절 + Trailing Stop 계산.

순수 계산 모듈 — 외부 의존성 없음.
v1-17 ExitParams 기반으로 StopLossParams + TrailingStopState 생성.
"""
from __future__ import annotations

from .constants import TRAILING_STOP_ATR_MULT, TRAILING_TRIGGER_RATIO
from .types import StopLossParams, TrailingStopState


class DynamicStopLoss:
    """동적 손절/익절 + Trailing Stop 계산.

    BUY  포지션: peak_price = 신고가 추적, current_stop = peak - ATR
    SELL 포지션: peak_price = 신저가 추적, current_stop = peak + ATR
    """

    @staticmethod
    def calculate(
        entry_price: float,
        stop_loss_price: float,
        take_profit_price: float,
        atr: float,
        stop_loss_atr_mult: float,
        take_profit_atr_mult: float,
    ) -> StopLossParams:
        """최종 SL/TP + Trailing Stop 파라미터 계산.

        Trailing Stop 활성화 기준:
        - 가격이 익절 50% 지점 도달 시 활성화 (BUY: 상방, SELL: 하방)
        - 활성화 후 ATR × 1.0 거리로 추적

        Note: tp_distance 부호로 BUY/SELL 방향 자동 처리
              BUY:  tp_distance > 0 → trigger > entry
              SELL: tp_distance < 0 → trigger < entry
        """
        tp_distance = take_profit_price - entry_price
        trailing_trigger_price = entry_price + tp_distance * TRAILING_TRIGGER_RATIO
        trailing_stop_distance = atr * TRAILING_STOP_ATR_MULT

        return StopLossParams(
            stop_loss_price=stop_loss_price,
            take_profit_price=take_profit_price,
            stop_loss_atr_mult=stop_loss_atr_mult,
            take_profit_atr_mult=take_profit_atr_mult,
            trailing_trigger_price=trailing_trigger_price,
            trailing_stop_distance=trailing_stop_distance,
        )

    @staticmethod
    def init_trailing_state(
        entry_price: float,
        stop_loss_params: StopLossParams,
    ) -> TrailingStopState:
        """체결 후 TrailingStopState 초기화."""
        return TrailingStopState(
            is_active=False,
            peak_price=entry_price,
            current_stop=stop_loss_params["stop_loss_price"],
            activation_threshold=stop_loss_params["trailing_trigger_price"],
        )

    @staticmethod
    def update_trailing_stop(
        state: TrailingStopState,
        current_price: float,
        atr: float,
        action: str = "buy",
    ) -> TrailingStopState:
        """Trailing Stop 상태 업데이트 (가격 모니터링 시 호출).

        BUY:  activation_threshold 이상 도달 → 활성화, 신고가 추적
        SELL: activation_threshold 이하 도달 → 활성화, 신저가 추적

        Args:
            state: 현재 TrailingStopState.
            current_price: 현재 시세.
            atr: 현재 ATR 값.
            action: "buy" 또는 "sell" (방향에 따라 추적 방식 결정).
        """
        is_active = state["is_active"]
        peak_price = state["peak_price"]
        current_stop = state["current_stop"]
        trailing_distance = atr * TRAILING_STOP_ATR_MULT

        if action == "buy":
            if not is_active and current_price >= state["activation_threshold"]:
                is_active = True
            if is_active:
                if current_price > peak_price:
                    peak_price = current_price
                current_stop = peak_price - trailing_distance
        else:  # sell
            if not is_active and current_price <= state["activation_threshold"]:
                is_active = True
            if is_active:
                if current_price < peak_price:
                    peak_price = current_price
                current_stop = peak_price + trailing_distance

        return TrailingStopState(
            is_active=is_active,
            peak_price=peak_price,
            current_stop=current_stop,
            activation_threshold=state["activation_threshold"],
        )

    @staticmethod
    def should_exit(
        state: TrailingStopState,
        current_price: float,
        stop_loss_price: float,
        take_profit_price: float,
        action: str = "buy",
    ) -> tuple[bool, str]:
        """청산 여부 판단.

        BUY:  price <= stop_loss(손절), price >= take_profit(익절)
        SELL: price >= stop_loss(손절), price <= take_profit(익절)

        Args:
            action: "buy" 또는 "sell".

        Returns:
            (should_exit, reason): "stop_loss" | "take_profit" | "trailing_stop"
        """
        if action == "buy":
            if current_price <= stop_loss_price:
                return True, "stop_loss"
            if current_price >= take_profit_price:
                return True, "take_profit"
            if state["is_active"] and current_price <= state["current_stop"]:
                return True, "trailing_stop"
        else:  # sell
            if current_price >= stop_loss_price:
                return True, "stop_loss"
            if current_price <= take_profit_price:
                return True, "take_profit"
            if state["is_active"] and current_price >= state["current_stop"]:
                return True, "trailing_stop"

        return False, ""

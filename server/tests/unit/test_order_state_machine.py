"""OrderStateMachine 단위 테스트."""
import pytest

from app.core.exceptions import AppError
from app.services.order_service import OrderStateMachine


class TestOrderStateMachineValidTransitions:
    """유효 상태 전이 테스트."""

    def test_pending_to_open(self):
        OrderStateMachine.validate_transition("pending", "open")  # 예외 없어야 함

    def test_pending_to_filled(self):
        OrderStateMachine.validate_transition("pending", "filled")

    def test_pending_to_failed(self):
        OrderStateMachine.validate_transition("pending", "failed")

    def test_open_to_filled(self):
        OrderStateMachine.validate_transition("open", "filled")

    def test_open_to_partial(self):
        OrderStateMachine.validate_transition("open", "partial")

    def test_open_to_cancelled(self):
        OrderStateMachine.validate_transition("open", "cancelled")

    def test_partial_to_filled(self):
        OrderStateMachine.validate_transition("partial", "filled")

    def test_partial_to_cancelled(self):
        OrderStateMachine.validate_transition("partial", "cancelled")

    def test_pending_to_cancelled(self):
        """pending → cancelled: cancel_order PENDING 분기에서 사용."""
        OrderStateMachine.validate_transition("pending", "cancelled")


class TestOrderStateMachineInvalidTransitions:
    """무효 상태 전이 테스트."""

    def test_filled_to_cancelled(self):
        with pytest.raises(AppError) as exc_info:
            OrderStateMachine.validate_transition("filled", "cancelled")
        assert exc_info.value.code == "INVALID_ORDER_TRANSITION"

    def test_cancelled_to_open(self):
        with pytest.raises(AppError) as exc_info:
            OrderStateMachine.validate_transition("cancelled", "open")
        assert exc_info.value.code == "INVALID_ORDER_TRANSITION"

    def test_failed_to_open(self):
        with pytest.raises(AppError) as exc_info:
            OrderStateMachine.validate_transition("failed", "open")
        assert exc_info.value.code == "INVALID_ORDER_TRANSITION"

    def test_open_to_failed(self):
        with pytest.raises(AppError) as exc_info:
            OrderStateMachine.validate_transition("open", "failed")
        assert exc_info.value.code == "INVALID_ORDER_TRANSITION"

    def test_error_message_contains_states(self):
        with pytest.raises(AppError) as exc_info:
            OrderStateMachine.validate_transition("filled", "open")
        assert "filled" in exc_info.value.message
        assert "open" in exc_info.value.message


class TestOrderStateMachineCanCancel:
    """can_cancel 상태별 테스트."""

    def test_pending_can_cancel(self):
        assert OrderStateMachine.can_cancel("pending") is True

    def test_open_can_cancel(self):
        assert OrderStateMachine.can_cancel("open") is True

    def test_partial_can_cancel(self):
        assert OrderStateMachine.can_cancel("partial") is True

    def test_filled_cannot_cancel(self):
        assert OrderStateMachine.can_cancel("filled") is False

    def test_cancelled_cannot_cancel(self):
        assert OrderStateMachine.can_cancel("cancelled") is False

    def test_failed_cannot_cancel(self):
        assert OrderStateMachine.can_cancel("failed") is False

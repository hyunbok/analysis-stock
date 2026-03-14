"""WebSocket 에러 팩토리 및 종료 코드 상수."""
from app.core.config import settings


class WSCloseCode:
    """WebSocket 종료 코드 — RFC 6455 §7.4.2 기준."""

    GOING_AWAY = 1001       # 서버 셧다운
    INTERNAL_ERROR = 1011   # 서버 내부 오류
    UNAUTHORIZED = 4001     # JWT 인증 실패/만료
    FORBIDDEN = 4003        # 연결 한계 초과


class WSErrors:
    """WS 에러 팩토리 — AppError와 별개, JSON 메시지로 전송.

    Note:
        WS 핸들러에서는 raise AppError 금지 — 항상 send_json(WSErrors.*()) 사용.
    """

    @staticmethod
    def unknown_action(action: str) -> dict:
        return {
            "action": "error",
            "code": "UNKNOWN_ACTION",
            "message": f"Unknown action: {action}",
        }

    @staticmethod
    def subscription_limit() -> dict:
        return {
            "action": "error",
            "code": "SUBSCRIPTION_LIMIT_EXCEEDED",
            "message": f"Maximum {settings.WS_MAX_SUBSCRIPTIONS_PER_CONN} subscriptions per connection",
        }

    @staticmethod
    def invalid_message(detail: str) -> dict:
        return {
            "action": "error",
            "code": "INVALID_MESSAGE",
            "message": detail,
        }

    @staticmethod
    def invalid_channel(channel: str) -> dict:
        return {
            "action": "error",
            "code": "INVALID_CHANNEL",
            "message": f"Unknown channel: {channel}",
        }

    @staticmethod
    def exchange_unavailable(exchange: str) -> dict:
        return {
            "action": "error",
            "code": "EXCHANGE_UNAVAILABLE",
            "message": f"Exchange stream unavailable: {exchange}",
        }

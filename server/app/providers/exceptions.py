"""거래소 Provider 도메인 예외.

AppError와 독립적인 내부 예외 계층.
서비스 레이어에서 AppError(ExchangeErrors 팩토리)로 변환하여 클라이언트에 반환.
"""
from __future__ import annotations


class ExchangeError(Exception):
    """거래소 관련 기본 예외."""

    def __init__(
        self,
        exchange: str,
        message: str,
        original_error: Exception | None = None,
    ) -> None:
        self.exchange = exchange
        self.original_error = original_error
        super().__init__(f"[{exchange}] {message}")


class ExchangeAuthError(ExchangeError):
    """API 키 인증 실패 — 키/시크릿 불일치, 만료."""


class ExchangePermissionError(ExchangeError):
    """API 키 권한 부족 — 필요한 권한 미설정."""


class ExchangeRateLimitError(ExchangeError):
    """거래소 서버 측 Rate Limit 초과 (HTTP 429)."""

    def __init__(
        self,
        exchange: str,
        retry_after_seconds: int | None = None,
        original_error: Exception | None = None,
    ) -> None:
        self.retry_after_seconds = retry_after_seconds
        super().__init__(exchange, "Rate limit exceeded", original_error)


class ExchangeOrderError(ExchangeError):
    """주문 처리 실패 — 최소 주문 금액 미달, 잘못된 수량 등."""


class ExchangeInsufficientBalanceError(ExchangeOrderError):
    """잔고 부족으로 인한 주문 실패."""


class ExchangeNetworkError(ExchangeError):
    """네트워크 연결 오류 — 타임아웃, DNS 실패, SSL 오류."""


class ExchangeUnavailableError(ExchangeError):
    """서비스 불가 — Circuit Breaker OPEN 또는 거래소 점검."""


class ExchangeInvalidSymbolError(ExchangeError):
    """지원하지 않는 심볼 또는 마켓 코드."""


class ExchangeDataError(ExchangeError):
    """응답 데이터 파싱 실패 또는 예상치 못한 응답 형식."""

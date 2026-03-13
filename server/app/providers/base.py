"""거래소 추상 클래스 정의."""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable

from .enums import ExchangeType
from .types import (
    ApiKeyInfo,
    Balance,
    Candle,
    Order,
    OrderBook,
    OrderResult,
    Ticker,
    TradingFee,
)


class ExchangeRestProvider(ABC):
    """거래소 REST API 추상 계층.

    계약(Contract):
    - 모든 메서드는 async여야 함
    - 거래소 응답을 providers/types.py의 공통 모델로 정규화하여 반환
    - 거래소 고유 예외를 providers/exceptions.py 계층으로 변환
    - 인증 정보(api_key, api_secret)는 __init__에서 주입받아 인스턴스 변수로 보관
    """

    @abstractmethod
    async def get_ticker(self, market: str) -> Ticker:
        """현재 시세 조회.

        Args:
            market: 거래소 내부 마켓 코드 (SymbolMapper.to_market() 변환 후 전달)

        Raises:
            ExchangeInvalidSymbolError: 미지원 마켓
            ExchangeNetworkError: 연결 오류
            ExchangeUnavailableError: Circuit Breaker OPEN
        """

    @abstractmethod
    async def get_orderbook(self, market: str, depth: int = 10) -> OrderBook:
        """호가창 조회.

        Args:
            market: 거래소 내부 마켓 코드
            depth: 조회할 호가 개수 (기본 10)
        """

    @abstractmethod
    async def get_candles(
        self, market: str, timeframe: str, count: int = 200
    ) -> list[Candle]:
        """OHLCV 캔들 데이터 조회.

        Args:
            market: 거래소 내부 마켓 코드
            timeframe: "1m" | "5m" | "15m" | "1h" | "4h" | "1d"
            count: 조회할 캔들 개수 (기본 200)

        Returns:
            list[Candle]: 최신순 정렬 (index 0 = 가장 최신 캔들)
        """

    @abstractmethod
    async def place_order(self, order: Order) -> OrderResult:
        """주문 실행.

        Raises:
            ExchangeAuthError: API 키 인증 실패
            ExchangePermissionError: TRADE 권한 없음
            ExchangeInsufficientBalanceError: 잔고 부족
            ExchangeOrderError: 최소 주문 금액 미달 등
            ExchangeNetworkError, ExchangeUnavailableError
        """

    @abstractmethod
    async def cancel_order(self, market: str, exchange_order_id: str) -> bool:
        """주문 취소.

        Returns:
            bool: 취소 성공 여부 (이미 체결된 주문은 False)
        """

    @abstractmethod
    async def get_balance(self) -> list[Balance]:
        """전체 잔고 조회.

        Returns:
            list[Balance]: 보유 자산 목록 (잔고 0인 자산 포함 여부는 거래소마다 상이)
        """

    @abstractmethod
    async def get_trading_fee(self, market: str) -> TradingFee:
        """수수료 조회."""

    @abstractmethod
    async def verify_api_key(self) -> ApiKeyInfo:
        """API 키 유효성 및 권한 검증.

        Returns:
            ApiKeyInfo: is_valid=True/False + permissions 목록 + error_message
            예외 대신 ApiKeyInfo로 결과 반환 (네트워크 오류만 예외)

        Raises:
            ExchangeNetworkError: 검증 자체 불가한 오류만
        """


class ExchangeStreamProvider(ABC):
    """거래소 WebSocket 스트림 추상 계층.

    계약(Contract):
    - connect() 호출 후에만 subscribe_* 가능
    - 연결 끊김 시 자동 재연결 (Exponential Backoff, 최대 EXCHANGE_WS_RECONNECT_MAX회)
    - disconnect() 호출 시 모든 구독 자동 해제
    """

    @abstractmethod
    async def connect(self) -> None:
        """WebSocket 연결 수립.

        Raises:
            ExchangeNetworkError: 연결 실패
            ExchangeUnavailableError: Circuit Breaker OPEN
        """

    @abstractmethod
    async def disconnect(self) -> None:
        """WebSocket 연결 종료 및 구독 정리."""

    @abstractmethod
    async def subscribe_ticker(
        self,
        markets: list[str],
        callback: Callable[[Ticker], Awaitable[None]],
    ) -> None:
        """실시간 시세 구독.

        Args:
            markets: 거래소 내부 마켓 코드 목록
            callback: 시세 수신 시 호출할 async 콜백
        """

    @abstractmethod
    async def subscribe_orderbook(
        self,
        markets: list[str],
        callback: Callable[[OrderBook], Awaitable[None]],
    ) -> None:
        """실시간 호가창 구독."""

    @abstractmethod
    async def unsubscribe(self, markets: list[str] | None = None) -> None:
        """구독 해제.

        Args:
            markets: 해제할 마켓 목록. None 시 전체 해제.
        """

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """WebSocket 연결 상태."""


class ExchangeProvider(ExchangeRestProvider, ExchangeStreamProvider):
    """REST + Stream 통합 추상 클래스. 모든 거래소 구현체의 최상위 타입."""

    @property
    @abstractmethod
    def exchange_type(self) -> ExchangeType:
        """거래소 식별자."""

    @abstractmethod
    async def initialize(self) -> None:
        """Provider 초기화 (lifespan startup 에서 호출).

        HTTP 클라이언트 초기화, API 키 사전 검증 등.
        """

    @abstractmethod
    async def close(self) -> None:
        """리소스 정리 (lifespan shutdown 에서 호출).

        HTTP 클라이언트 종료, WebSocket 연결 해제.
        """

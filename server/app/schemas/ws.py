"""WebSocket 메시지 스키마 — 클라이언트↔서버 메시지 타입 정의."""
from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, model_validator


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


# ── 채널 타입 열거형 ──────────────────────────────────────────────────────────


class WSChannel(StrEnum):
    """구독 가능한 채널 타입."""

    TICKER = "ticker"
    ORDERBOOK = "orderbook"
    TRADES = "trades"
    MY_ORDERS = "my-orders"
    AI_SIGNAL = "ai-signal"
    NOTIFICATION = "notification"
    PRICE_ALERT = "price-alert"
    SYSTEM = "system"


# exchange + market 필수인 공개 시장 채널
MARKET_CHANNELS: frozenset[WSChannel] = frozenset(
    {WSChannel.TICKER, WSChannel.ORDERBOOK, WSChannel.TRADES}
)

# user_id 기반 개인 채널 (exchange/market 불필요)
PERSONAL_CHANNELS: frozenset[WSChannel] = frozenset(
    {
        WSChannel.MY_ORDERS,
        WSChannel.AI_SIGNAL,
        WSChannel.NOTIFICATION,
        WSChannel.PRICE_ALERT,
    }
)


# ── Client → Server ───────────────────────────────────────────────────────────


class WSSubscribeRequest(BaseModel):
    """채널 구독 요청.

    Examples:
        시장 채널: {"action":"subscribe","channel":"ticker","exchange":"upbit","market":"KRW-BTC"}
        개인 채널: {"action":"subscribe","channel":"my-orders"}
    """

    action: Literal["subscribe"]
    channel: WSChannel
    exchange: str | None = Field(default=None, min_length=1, max_length=20)
    market: str | None = Field(default=None, min_length=1, max_length=20)

    @model_validator(mode="after")
    def _require_market_params(self) -> "WSSubscribeRequest":
        if self.channel in MARKET_CHANNELS and (not self.exchange or not self.market):
            raise ValueError(
                f"channel '{self.channel}' requires 'exchange' and 'market'"
            )
        return self


class WSUnsubscribeRequest(BaseModel):
    """채널 구독 해제 요청.

    Examples:
        {"action":"unsubscribe","channel":"ticker","exchange":"upbit","market":"KRW-BTC"}
        {"action":"unsubscribe","channel":"my-orders"}
    """

    action: Literal["unsubscribe"]
    channel: WSChannel
    exchange: str | None = Field(default=None, min_length=1, max_length=20)
    market: str | None = Field(default=None, min_length=1, max_length=20)

    @model_validator(mode="after")
    def _require_market_params(self) -> "WSUnsubscribeRequest":
        if self.channel in MARKET_CHANNELS and (not self.exchange or not self.market):
            raise ValueError(
                f"channel '{self.channel}' requires 'exchange' and 'market'"
            )
        return self


class WSPingRequest(BaseModel):
    """클라이언트 Heartbeat 요청.

    Examples:
        {"action":"ping"}
    """

    action: Literal["ping"]


# 인바운드 메시지 — Literal["action"] 기반 판별 유니온
WSInboundMessage = Annotated[
    WSSubscribeRequest | WSUnsubscribeRequest | WSPingRequest,
    Field(discriminator="action"),
]


# ── Server → Client (제어 메시지) ─────────────────────────────────────────────


class WSConnectedMessage(BaseModel):
    """연결 수락 직후 전송 — 클라이언트가 conn_id를 로깅/디버깅에 활용."""

    action: Literal["connected"] = "connected"
    conn_id: str
    timestamp: str = Field(default_factory=_now_iso)


class WSSubscribedMessage(BaseModel):
    """구독 성공 응답."""

    action: Literal["subscribed"] = "subscribed"
    channel: str  # WSChannel 값 그대로 ("ticker", "my-orders" 등)
    exchange: str | None = None
    market: str | None = None
    timestamp: str = Field(default_factory=_now_iso)


class WSUnsubscribedMessage(BaseModel):
    """구독 해제 성공 응답."""

    action: Literal["unsubscribed"] = "unsubscribed"
    channel: str
    exchange: str | None = None
    market: str | None = None
    timestamp: str = Field(default_factory=_now_iso)


class WSPongMessage(BaseModel):
    """Heartbeat 응답 — last_ping 갱신과 함께 전송."""

    action: Literal["pong"] = "pong"
    timestamp: str = Field(default_factory=_now_iso)


class WSErrorMessage(BaseModel):
    """에러 메시지 — 연결 유지, 해당 요청만 실패 처리."""

    action: Literal["error"] = "error"
    code: str  # WSErrors 코드 문자열
    message: str
    timestamp: str = Field(default_factory=_now_iso)


class WSSystemMessage(BaseModel):
    """시스템/거래소 상태 변경 알림 — system 채널 구독자에게 브로드캐스트."""

    action: Literal["system"] = "system"
    type: str  # "exchange_status" | "server_maintenance" | ...
    data: dict[str, Any]
    timestamp: str = Field(default_factory=_now_iso)

"""CoinOne WebSocket 단일 연결 + 다중 채널 구독 관리."""
from __future__ import annotations

import asyncio
import json
import logging
import random
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger(__name__)

# ── 타입 별칭 ─────────────────────────────────────────────────────────────────

_Callback = Callable[[Any], Awaitable[None]]


class _CoinOneWebSocketClient:
    """CoinOne WebSocket 단일 연결 + 다중 채널 구독 관리.

    CoinOne WS 특성:
    - SUBSCRIBE/UNSUBSCRIBE/PING 개별 메시지 방식 (Upbit의 배열 방식과 다름)
    - 채널별 구독: TICKER, ORDERBOOK
    - topic: {quote_currency, target_currency} 딕셔너리
    - 인증 불필요 (public 데이터)
    - 30분 idle timeout (Upbit 120초 대비 느슨)
    - IP당 최대 20 연결

    재연결 전략:
    - Exponential Backoff with jitter (Upbit과 동일)
    - 초기 1s → 2s → 4s → 8s → max 60s
    - 최대 reconnect_max 회 시도
    """

    WS_URL = "wss://stream.coinone.co.kr"

    def __init__(self, reconnect_max: int = 5, ping_interval: float = 300.0) -> None:
        """
        Args:
            reconnect_max: 최대 재연결 시도 횟수
            ping_interval: PING 전송 간격 (초).
                CoinOne은 30분 타임아웃 → 5분(300초) 간격 PING 충분.
        """
        self._ws: Any | None = None
        # channel → {"markets": [...], "callback": callable}
        self._subscriptions: dict[str, dict[str, Any]] = {}
        self._listen_task: asyncio.Task[None] | None = None
        self._ping_task: asyncio.Task[None] | None = None
        self._reconnect_max = reconnect_max
        self._ping_interval = ping_interval
        self._connected = False

    @property
    def is_connected(self) -> bool:
        """WebSocket 연결 상태."""
        return self._connected

    async def connect(self) -> None:
        """WebSocket 연결 수립 (재연결 포함).

        Raises:
            ExchangeNetworkError: 최대 재연결 횟수 초과 시
        """
        await self._connect_with_retry()

    async def disconnect(self) -> None:
        """WebSocket 연결 종료 및 구독 정리."""
        self._connected = False
        if self._listen_task and not self._listen_task.done():
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass
        if self._ping_task and not self._ping_task.done():
            self._ping_task.cancel()
            try:
                await self._ping_task
            except asyncio.CancelledError:
                pass
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None
        self._subscriptions.clear()

    async def subscribe(
        self,
        channel: str,
        markets: list[str],
        callback: _Callback,
    ) -> None:
        """구독 등록 + 즉시 개별 SUBSCRIBE 메시지 전송.

        CoinOne WS 구독 메시지 (마켓별 개별 전송):
        {
            "request_type": "SUBSCRIBE",
            "channel": "TICKER",
            "topic": {"quote_currency": "KRW", "target_currency": "BTC"}
        }

        Args:
            channel: "TICKER" | "ORDERBOOK"
            markets: target_currency 목록 e.g. ["BTC", "ETH"]
            callback: 데이터 수신 시 호출할 async 콜백

        Note:
            기존 같은 channel 구독은 덮어쓴다.
        """
        channel_upper = channel.upper()
        self._subscriptions[channel_upper] = {"markets": markets, "callback": callback}
        if self._connected and self._ws is not None:
            await self._send_subscribe_messages(channel_upper, markets)

    async def unsubscribe(self, markets: list[str] | None = None) -> None:
        """특정 마켓 또는 전체 구독 해제.

        Args:
            markets: 해제할 마켓 목록. None 시 전체 해제.
        """
        if markets is None:
            for channel, info in list(self._subscriptions.items()):
                if self._connected and self._ws is not None:
                    await self._send_unsubscribe_messages(channel, info["markets"])
            self._subscriptions.clear()
        else:
            market_set = set(m.upper() for m in markets)
            for channel, info in list(self._subscriptions.items()):
                to_remove = [m for m in info["markets"] if m.upper() in market_set]
                updated = [m for m in info["markets"] if m.upper() not in market_set]
                if to_remove and self._connected and self._ws is not None:
                    await self._send_unsubscribe_messages(channel, to_remove)
                if updated:
                    self._subscriptions[channel]["markets"] = updated
                else:
                    del self._subscriptions[channel]

    async def _connect_once(self) -> None:
        """단일 WebSocket 연결 시도."""
        import websockets  # type: ignore[import-untyped]

        self._ws = await websockets.connect(
            self.WS_URL,
            ping_interval=None,  # 자체 ping 루프 사용
        )
        self._connected = True
        logger.info("CoinOne WebSocket connected")

        # 구독 재전송 (재연결 시)
        if self._subscriptions:
            for channel, info in self._subscriptions.items():
                await self._send_subscribe_messages(channel, info["markets"])

        # 리스닝/핑 태스크 시작
        self._listen_task = asyncio.create_task(self._listen_loop())
        self._ping_task = asyncio.create_task(self._ping_loop())

    async def _connect_with_retry(self) -> None:
        """Exponential Backoff with jitter 재연결 루프.

        Raises:
            ExchangeNetworkError: 최대 재연결 횟수 초과 시
        """
        from ..exceptions import ExchangeNetworkError

        attempt = 0
        while attempt <= self._reconnect_max:
            try:
                await self._connect_once()
                return
            except Exception as exc:
                attempt += 1
                if attempt > self._reconnect_max:
                    raise ExchangeNetworkError(
                        "coinone",
                        f"WebSocket reconnect failed after {self._reconnect_max} attempts",
                        exc,
                    ) from exc
                delay = min(2 ** (attempt - 1), 60.0)
                jitter = delay * 0.1 * random.random()
                wait = delay + jitter
                logger.warning(
                    "CoinOne WS connection failed (attempt %d/%d), retrying in %.1fs: %s",
                    attempt,
                    self._reconnect_max,
                    wait,
                    exc,
                )
                await asyncio.sleep(wait)

    async def _send_subscribe_messages(
        self, channel: str, markets: list[str]
    ) -> None:
        """개별 SUBSCRIBE 메시지를 마켓별로 전송.

        CoinOne은 Upbit과 달리 마켓별 개별 SUBSCRIBE 메시지를 전송한다.

        Args:
            channel: "TICKER" | "ORDERBOOK"
            markets: target_currency 목록 e.g. ["BTC", "ETH"]
        """
        if not self._ws or not self._connected:
            return
        for target in markets:
            msg = {
                "request_type": "SUBSCRIBE",
                "channel": channel,
                "topic": {
                    "quote_currency": "KRW",
                    "target_currency": target.upper(),
                },
            }
            await self._ws.send(json.dumps(msg))
            logger.debug("CoinOne WS subscribed: channel=%s, target=%s", channel, target)

    async def _send_unsubscribe_messages(
        self, channel: str, markets: list[str]
    ) -> None:
        """개별 UNSUBSCRIBE 메시지 전송.

        Args:
            channel: "TICKER" | "ORDERBOOK"
            markets: target_currency 목록
        """
        if not self._ws or not self._connected:
            return
        for target in markets:
            msg = {
                "request_type": "UNSUBSCRIBE",
                "channel": channel,
                "topic": {
                    "quote_currency": "KRW",
                    "target_currency": target.upper(),
                },
            }
            await self._ws.send(json.dumps(msg))

    async def _ping_loop(self) -> None:
        """주기적 PING 전송 (30분 타임아웃 방지).

        CoinOne PING 메시지: {"request_type": "PING"}
        5분(300초) 간격 전송 — 30분 타임아웃 대비 충분한 여유.
        전송 실패 시 loop 종료 → _connect_with_retry()가 재연결 처리.
        """
        while self._ws and not getattr(self._ws, "closed", True):
            await asyncio.sleep(self._ping_interval)
            try:
                await self._ws.send(json.dumps({"request_type": "PING"}))
            except Exception:
                logger.debug("CoinOne WS ping failed, connection may be lost")
                break

    async def _listen_loop(self) -> None:
        """수신 루프 — 메시지 수신 → 파싱 → 콜백 실행."""
        if not self._ws:
            return
        try:
            async for raw in self._ws:
                await self._handle_message(raw)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("CoinOne WS listen loop error: %s", exc)
            self._connected = False
            # 고아 ping task 정리 후 재연결
            if self._ping_task and not self._ping_task.done():
                self._ping_task.cancel()
            if self._subscriptions:
                try:
                    await self._connect_with_retry()
                except Exception:
                    logger.exception("CoinOne WS reconnect failed")

    async def _handle_message(self, raw: str | bytes) -> None:
        """수신 메시지 파싱 → channel 필드 기반 분기 → mappers.py 함수 호출 → 콜백 실행.

        CoinOne WS 응답:
        {"response_type": "DATA", "channel": "TICKER", "data": {...}}
        {"response_type": "DATA", "channel": "ORDERBOOK", "data": {...}}
        {"response_type": "PONG"}  → 무시
        {"response_type": "CONNECTED"}  → 무시
        {"response_type": "ERROR", "error_code": ..., "message": ...}  → 로그

        Args:
            raw: 텍스트 JSON (CoinOne WS는 텍스트 JSON만 사용)
        """
        from .mappers import parse_orderbook, parse_ticker

        try:
            msg = self._decode_message(raw)
        except Exception as exc:
            logger.warning("CoinOne WS message decode error: %s", exc)
            return

        response_type = msg.get("response_type", "")

        # PONG/CONNECTED 응답 무시
        if response_type in ("PONG", "CONNECTED"):
            return

        # ERROR 응답 로깅
        if response_type == "ERROR":
            error_code = msg.get("error_code")
            error_msg = msg.get("message", "")
            logger.warning(
                "CoinOne WS error: code=%s, message=%s", error_code, error_msg
            )
            return

        # DATA 응답 처리
        if response_type != "DATA":
            logger.debug("CoinOne WS: unhandled response_type=%s", response_type)
            return

        channel = msg.get("channel", "")
        sub_info = self._subscriptions.get(channel)
        if sub_info is None:
            logger.debug("CoinOne WS: unhandled channel=%s", channel)
            return

        data = msg.get("data", {})
        callback = sub_info["callback"]

        try:
            from ..types import OrderBook, Ticker

            result: Ticker | OrderBook
            if channel == "TICKER":
                result = parse_ticker(data)
            elif channel == "ORDERBOOK":
                result = parse_orderbook(data)
            else:
                return
            await callback(result)
        except Exception as exc:
            logger.warning("CoinOne WS callback error (channel=%s): %s", channel, exc)

    @staticmethod
    def _decode_message(raw: bytes | str) -> dict:
        """텍스트/바이너리 JSON → dict 변환 (CoinOne WS는 텍스트 JSON만 사용)."""
        if isinstance(raw, bytes):
            return json.loads(raw.decode("utf-8"))
        return json.loads(raw)

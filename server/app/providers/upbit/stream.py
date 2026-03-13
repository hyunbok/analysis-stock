"""Upbit WebSocket 단일 연결 + 다중 채널 구독 관리.

TODO(exchange-api-expert): ST4 — WebSocket 스트리밍 구현 담당.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import random
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger(__name__)

# ── 타입 별칭 ─────────────────────────────────────────────────────────────────

_Callback = Callable[[Any], Awaitable[None]]


class _UpbitWebSocketClient:
    """Upbit WebSocket 단일 연결 + 다중 채널 구독 관리.

    Upbit WS 특성:
    - 단일 연결에서 다중 type(ticker, orderbook) 동시 구독 가능
    - 구독 변경 시 새 subscription 메시지 전송 (연결 유지)
    - 인증 불필요 (ticker, orderbook은 public 데이터)
    - 응답 형식: JSON (format 미지정 시 기본 SIMPLE 포맷)

    재연결 전략:
    - Exponential Backoff with jitter
    - 초기 1s → 2s → 4s → 8s → max 60s
    - 최대 reconnect_max 회 시도
    """

    WS_URL = "wss://api.upbit.com/websocket/v1"

    def __init__(self, reconnect_max: int = 5, ping_interval: float = 30.0) -> None:
        self._ws: Any | None = None
        # sub_type → {"markets": [...], "callback": callable}
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
        sub_type: str,
        markets: list[str],
        callback: _Callback,
    ) -> None:
        """구독 등록 + 즉시 subscription 메시지 전송.

        Args:
            sub_type: "ticker" | "orderbook"
            markets: 거래소 마켓 코드 목록 e.g. ["KRW-BTC", "KRW-ETH"]
            callback: 데이터 수신 시 호출할 async 콜백

        Note:
            기존 같은 type 구독은 덮어쓴다.
        """
        self._subscriptions[sub_type] = {"markets": markets, "callback": callback}
        if self._connected and self._ws is not None:
            await self._send_subscription_message()

    async def unsubscribe(self, markets: list[str] | None = None) -> None:
        """특정 마켓 또는 전체 구독 해제.

        Args:
            markets: 해제할 마켓 목록. None 시 전체 해제.
        """
        if markets is None:
            self._subscriptions.clear()
        else:
            market_set = set(markets)
            for sub_type, info in list(self._subscriptions.items()):
                updated = [m for m in info["markets"] if m not in market_set]
                if updated:
                    self._subscriptions[sub_type]["markets"] = updated
                else:
                    del self._subscriptions[sub_type]
        if self._connected and self._ws is not None:
            await self._send_subscription_message()

    async def _connect_once(self) -> None:
        """단일 WebSocket 연결 시도."""
        import websockets  # type: ignore[import]

        self._ws = await websockets.connect(
            self.WS_URL,
            ping_interval=None,  # 자체 ping 루프 사용
        )
        self._connected = True
        logger.info("Upbit WebSocket connected")

        # 구독 재전송 (재연결 시)
        if self._subscriptions:
            await self._send_subscription_message()

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
                        "upbit",
                        f"WebSocket reconnect failed after {self._reconnect_max} attempts",
                        exc,
                    ) from exc
                delay = min(2 ** (attempt - 1), 60.0)
                jitter = delay * 0.1 * random.random()
                wait = delay + jitter
                logger.warning(
                    "Upbit WS connection failed (attempt %d/%d), retrying in %.1fs: %s",
                    attempt,
                    self._reconnect_max,
                    wait,
                    exc,
                )
                await asyncio.sleep(wait)

    async def _send_subscription_message(self) -> None:
        """현재 _subscriptions 상태 기반으로 Upbit WS 구독 메시지 전송.

        포맷:
        [
          {"ticket": "<uuid4>"},
          {"type": "ticker", "codes": ["KRW-BTC", ...], "is_only_realtime": true},
          {"type": "orderbook", "codes": ["KRW-BTC", ...]},
          {"format": "DEFAULT"}
        ]
        구독 없는 type은 메시지에서 제외.
        """
        if not self._ws or not self._connected:
            return

        message: list[dict[str, Any]] = [{"ticket": str(uuid.uuid4())}]
        for sub_type, info in self._subscriptions.items():
            entry: dict[str, Any] = {"type": sub_type, "codes": info["markets"]}
            if sub_type == "ticker":
                entry["is_only_realtime"] = True
            message.append(entry)
        message.append({"format": "DEFAULT"})

        await self._ws.send(json.dumps(message))
        logger.debug("Upbit WS subscription sent: %d channels", len(self._subscriptions))

    async def _ping_loop(self) -> None:
        """주기적 PING 전송 (Upbit 120초 무통신 타임아웃 방지).

        EXCHANGE_WS_PING_INTERVAL(기본 30초) 간격으로 "PING" 문자열 전송.
        전송 실패 시 loop 종료 → _connect_with_retry()가 재연결 처리.
        """
        while self._ws and not getattr(self._ws, "closed", True):
            await asyncio.sleep(self._ping_interval)
            try:
                await self._ws.send("PING")
            except Exception:
                logger.debug("Upbit WS ping failed, connection may be lost")
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
            logger.warning("Upbit WS listen loop error: %s", exc)
            self._connected = False
            # 고아 ping task 정리 후 재연결
            if self._ping_task and not self._ping_task.done():
                self._ping_task.cancel()
            if self._subscriptions:
                try:
                    await self._connect_with_retry()
                except Exception:
                    logger.exception("Upbit WS reconnect failed")

    async def _handle_message(self, raw: str | bytes) -> None:
        """수신 메시지 파싱 → type 필드 기반 분기 → mappers.py 함수 호출 → 콜백 실행.

        Args:
            raw: 바이너리 또는 텍스트 JSON.

        Note:
            type="ticker"    → mappers.parse_ticker(data) → ticker 콜백
            type="orderbook" → mappers.parse_orderbook(data) → orderbook 콜백
            type 미매칭      → 로그 경고 후 무시
        """
        from .mappers import parse_orderbook, parse_ticker

        try:
            data = self._decode_message(raw)
        except Exception as exc:
            logger.warning("Upbit WS message decode error: %s", exc)
            return

        msg_type = data.get("type")
        sub_info = self._subscriptions.get(msg_type)
        if sub_info is None:
            logger.debug("Upbit WS: unhandled message type=%s", msg_type)
            return

        callback = sub_info["callback"]
        try:
            if msg_type == "ticker":
                result = parse_ticker(data)
            elif msg_type == "orderbook":
                result = parse_orderbook(data)
            else:
                return
            await callback(result)
        except Exception as exc:
            logger.warning("Upbit WS callback error (type=%s): %s", msg_type, exc)

    @staticmethod
    def _decode_message(raw: bytes | str) -> dict:
        """바이너리/텍스트 JSON → dict 변환."""
        if isinstance(raw, bytes):
            return json.loads(raw.decode("utf-8"))
        return json.loads(raw)

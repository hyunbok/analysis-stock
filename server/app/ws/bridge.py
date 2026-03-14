"""거래소 WebSocket → Redis Pub/Sub 브리지 — 참조 카운팅 스트림 관리."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from app.core.pubsub import RedisPublisher
from app.core.redis_keys import RedisTTL, RedisKey

if TYPE_CHECKING:
    from redis.asyncio import Redis

    from app.providers.base import ExchangeProvider
    from app.providers.factory import ExchangeProviderFactory
    from app.providers.types import OrderBook, Ticker

logger = logging.getLogger(__name__)


@dataclass
class StreamState:
    """개별 (exchange, channel_type, market) 스트림 상태."""

    exchange: str
    market: str
    channel_type: str         # "ticker" | "orderbook" | "trades"
    ref_count: int = 0


class ExchangeStreamBridge:
    """거래소 WS → Redis Pub/Sub 브리지.

    참조 카운팅으로 중복 스트림 방지:
        - 1,000개 클라이언트가 같은 BTC/KRW 티커를 구독해도 거래소 WS 연결은 1개.
        - 마지막 구독자가 해제하면 해당 마켓 구독 종료.
    """

    def __init__(
        self,
        factory: ExchangeProviderFactory,
        publisher: RedisPublisher,
        redis: "Redis | None" = None,
    ) -> None:
        self._factory = factory
        self._publisher = publisher
        self._redis = redis
        # exchange name → provider (public stream용, API 키 불필요)
        self._providers: dict[str, ExchangeProvider] = {}
        # "exchange:channel_type:market" → StreamState
        self._streams: dict[str, StreamState] = {}
        # "exchange:channel_type" → 현재 구독 중인 마켓 집합
        self._active_markets: dict[str, set[str]] = {}

    # ── Public API ─────────────────────────────────────────────────────────────

    async def ensure_stream(
        self, exchange: str, market: str, channel_type: str
    ) -> None:
        """구독 참조 카운트 증가. 신규 마켓이면 Provider.subscribe_*() 호출."""
        key = self._stream_key(exchange, channel_type, market)
        if key not in self._streams:
            self._streams[key] = StreamState(
                exchange=exchange,
                market=market,
                channel_type=channel_type,
            )

        state = self._streams[key]
        state.ref_count += 1

        if state.ref_count == 1:
            # 새 마켓 추가 → active_markets 갱신 → 재구독
            mk = self._markets_key(exchange, channel_type)
            self._active_markets.setdefault(mk, set()).add(market)
            await self._resubscribe(exchange, channel_type)

    async def release_stream(
        self, exchange: str, market: str, channel_type: str
    ) -> None:
        """구독 참조 카운트 감소. 0이 되면 해당 마켓 구독 해제."""
        key = self._stream_key(exchange, channel_type, market)
        state = self._streams.get(key)
        if state is None:
            return

        state.ref_count -= 1
        if state.ref_count <= 0:
            del self._streams[key]
            mk = self._markets_key(exchange, channel_type)
            markets = self._active_markets.get(mk)
            if markets:
                markets.discard(market)
                if markets:
                    await self._resubscribe(exchange, channel_type)
                else:
                    del self._active_markets[mk]
                    await self._clear_channel(exchange, channel_type)

    async def close_all(self) -> None:
        """lifespan shutdown — 모든 스트림 정리."""
        for provider in self._providers.values():
            try:
                await provider.disconnect()
                await provider.close()
            except Exception:
                logger.exception(
                    "ExchangeStreamBridge close failed provider=%s",
                    provider.exchange_type,
                )
        self._providers.clear()
        self._streams.clear()
        self._active_markets.clear()

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _stream_key(self, exchange: str, channel_type: str, market: str) -> str:
        return f"{exchange}:{channel_type}:{market}"

    def _markets_key(self, exchange: str, channel_type: str) -> str:
        return f"{exchange}:{channel_type}"

    async def _get_or_create_provider(self, exchange: str) -> ExchangeProvider:
        if exchange not in self._providers:
            from app.providers.enums import ExchangeType

            exchange_type = ExchangeType(exchange)
            # 시장 데이터는 공개 스트림 — API 키 불필요
            provider = self._factory.create(exchange_type, "", "", "bridge")
            await provider.initialize()
            await provider.connect()
            self._providers[exchange] = provider
            logger.info(
                "ExchangeStreamBridge: created stream provider exchange=%s", exchange
            )
        return self._providers[exchange]

    async def _resubscribe(self, exchange: str, channel_type: str) -> None:
        """현재 active_markets 전체로 provider 재구독."""
        try:
            provider = await self._get_or_create_provider(exchange)
            mk = self._markets_key(exchange, channel_type)
            markets = list(self._active_markets.get(mk, set()))
            if not markets:
                return

            if channel_type == "ticker":
                await provider.subscribe_ticker(markets, self._on_ticker)
            elif channel_type == "orderbook":
                await provider.subscribe_orderbook(markets, self._on_orderbook)
            else:
                logger.warning(
                    "ExchangeStreamBridge: unsupported channel_type=%s", channel_type
                )
        except Exception:
            logger.exception(
                "ExchangeStreamBridge _resubscribe failed exchange=%s channel=%s",
                exchange,
                channel_type,
            )

    async def _clear_channel(self, exchange: str, channel_type: str) -> None:
        """해당 exchange+channel_type의 모든 구독 해제."""
        provider = self._providers.get(exchange)
        if provider and provider.is_connected:
            try:
                await provider.unsubscribe(None)
            except Exception:
                logger.exception(
                    "ExchangeStreamBridge _clear_channel failed exchange=%s", exchange
                )

    # ── Callbacks ──────────────────────────────────────────────────────────────

    async def _on_ticker(self, ticker: Ticker) -> None:
        try:
            data = {
                "symbol": ticker.symbol,
                "price": float(ticker.price),
                "open_price": float(ticker.open_price),
                "high_price": float(ticker.high_price),
                "low_price": float(ticker.low_price),
                "volume": float(ticker.volume),
                "trade_value": float(ticker.trade_value),
                "change_rate": float(ticker.change_rate),
                "timestamp": ticker.timestamp.isoformat(),
            }
            # WS 클라이언트용 Pub/Sub 발행
            await self._publisher.publish_ticker(
                ticker.exchange.value, ticker.market, data
            )
            # REST API용 스냅샷 저장 (coin_service._enrich_with_prices에서 읽음)
            if self._redis is not None:
                snapshot = {
                    "current_price": float(ticker.price),
                    "open_price": float(ticker.open_price),
                    "high_price": float(ticker.high_price),
                    "low_price": float(ticker.low_price),
                    "volume_24h": float(ticker.volume),
                    "change_rate_24h": float(ticker.change_rate),
                    "price_updated_at": ticker.timestamp.isoformat(),
                }
                await self._redis.setex(
                    RedisKey.ticker(ticker.exchange.value, ticker.market),
                    RedisTTL.TICKER,
                    json.dumps(snapshot),
                )
        except Exception:
            logger.exception(
                "ExchangeStreamBridge _on_ticker publish failed exchange=%s market=%s",
                getattr(ticker, "exchange", "?"),
                getattr(ticker, "market", "?"),
            )

    async def _on_orderbook(self, orderbook: OrderBook) -> None:
        try:
            data = {
                "symbol": orderbook.symbol,
                "asks": [
                    {"price": float(e.price), "quantity": float(e.quantity)}
                    for e in orderbook.asks
                ],
                "bids": [
                    {"price": float(e.price), "quantity": float(e.quantity)}
                    for e in orderbook.bids
                ],
                "timestamp": orderbook.timestamp.isoformat(),
            }
            await self._publisher.publish_orderbook(
                orderbook.exchange.value, orderbook.market, data
            )
        except Exception:
            logger.exception(
                "ExchangeStreamBridge _on_orderbook publish failed exchange=%s market=%s",
                getattr(orderbook, "exchange", "?"),
                getattr(orderbook, "market", "?"),
            )

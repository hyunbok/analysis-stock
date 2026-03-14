"""코인 검색/조회 및 관심 코인 CRUD 통합 서비스."""
from __future__ import annotations

import json
import uuid
from decimal import Decimal

from redis.asyncio import Redis

from app.core.exceptions import CoinErrors
from app.core.redis_keys import RedisKey
from app.models.coin import Coin, WatchlistCoin
from app.repositories.coin_repository import CoinRepository
from app.repositories.exchange_account_repository import ExchangeAccountRepository
from app.repositories.watchlist_repository import WatchlistRepository
from app.schemas.coin import (
    AddWatchlistRequest,
    CoinDetailResponse,
    CoinResponse,
    PaginatedCoins,
    ReorderItem,
    WatchlistCoinResponse,
)


class CoinService:
    """코인 검색/조회 + 관심 코인 CRUD 통합 서비스."""

    def __init__(
        self,
        coin_repo: CoinRepository,
        watchlist_repo: WatchlistRepository,
        exchange_account_repo: ExchangeAccountRepository,
        redis: Redis,
    ) -> None:
        self._coin_repo = coin_repo
        self._watchlist_repo = watchlist_repo
        self._exchange_account_repo = exchange_account_repo
        self._redis = redis

    # ── 코인 검색/조회 ─────────────────────────────────────────────────────────

    async def search_coins(
        self,
        query: str | None,
        exchange_type: str | None,
        is_active: bool,
        page: int,
        size: int,
    ) -> PaginatedCoins:
        coins, total = await self._coin_repo.search(
            query=query,
            exchange_type=exchange_type,
            is_active=is_active,
            page=page,
            size=size,
        )
        enriched = await self._enrich_with_prices(coins)
        return PaginatedCoins.build(items=enriched, total=total, page=page, size=size)

    async def get_coin(self, coin_id: uuid.UUID) -> CoinDetailResponse:
        coin = await self._coin_repo.get_by_id(coin_id)
        if coin is None:
            raise CoinErrors.not_found()

        ticker = await self._get_ticker_snapshot(coin.exchange_type, coin.market_code)
        base = self._build_coin_response(coin, ticker)
        return CoinDetailResponse(
            **base.model_dump(),
            created_at=coin.created_at,
            updated_at=coin.updated_at,
        )

    # ── 관심 코인 CRUD ──────────────────────────────────────────────────────────

    async def get_watchlist(
        self,
        user_id: uuid.UUID,
        exchange_account_id: uuid.UUID | None,
    ) -> list[WatchlistCoinResponse]:
        items = await self._watchlist_repo.get_by_user(user_id, exchange_account_id)
        coins = [item.coin for item in items]
        enriched = await self._enrich_with_prices(coins)
        coin_map = {c.id: r for c, r in zip(coins, enriched)}

        return [
            WatchlistCoinResponse(
                id=item.id,
                coin_id=item.coin_id,
                coin=coin_map[item.coin_id],
                exchange_account_id=item.exchange_account_id,
                sort_order=item.sort_order,
                created_at=item.created_at,
            )
            for item in items
        ]

    async def add_to_watchlist(
        self,
        user_id: uuid.UUID,
        body: AddWatchlistRequest,
    ) -> WatchlistCoinResponse:
        # 1. coin 존재 확인
        coin = await self._coin_repo.get_by_id(body.coin_id)
        if coin is None:
            raise CoinErrors.not_found()

        # 2. exchange_account 소유권 확인
        if body.exchange_account_id is not None:
            account = await self._exchange_account_repo.get_by_id(
                body.exchange_account_id
            )
            if account is None or account.user_id != user_id:
                raise CoinErrors.exchange_account_mismatch()

        # 3. sort_order 자동 배정
        max_order = await self._watchlist_repo.get_max_sort_order(user_id)
        next_order = max_order + 1

        # 4. ON CONFLICT DO NOTHING
        wc = await self._watchlist_repo.create_or_conflict(
            user_id=user_id,
            coin_id=body.coin_id,
            exchange_account_id=body.exchange_account_id,
            sort_order=next_order,
        )
        if wc is None:
            raise CoinErrors.watchlist_duplicate()

        # 5. 시세 enrichment 후 응답
        ticker = await self._get_ticker_snapshot(coin.exchange_type, coin.market_code)
        coin_resp = self._build_coin_response(wc.coin, ticker)
        return WatchlistCoinResponse(
            id=wc.id,
            coin_id=wc.coin_id,
            coin=coin_resp,
            exchange_account_id=wc.exchange_account_id,
            sort_order=wc.sort_order,
            created_at=wc.created_at,
        )

    async def remove_from_watchlist(
        self,
        user_id: uuid.UUID,
        watchlist_id: uuid.UUID,
    ) -> None:
        wc = await self._watchlist_repo.get_by_user_and_id(user_id, watchlist_id)
        if wc is None:
            raise CoinErrors.watchlist_not_found()
        await self._watchlist_repo.delete(watchlist_id)

    async def reorder_watchlist(
        self,
        user_id: uuid.UUID,
        items: list[ReorderItem],
    ) -> list[WatchlistCoinResponse]:
        # 1. 소유권 일괄 확인
        existing = await self._watchlist_repo.get_by_user(user_id)
        owned_ids = {wc.id for wc in existing}
        requested_ids = {item.id for item in items}

        if not requested_ids.issubset(owned_ids):
            raise CoinErrors.watchlist_access_denied()

        # 2. CASE WHEN 배치 UPDATE
        pairs = [(item.id, item.sort_order) for item in items]
        await self._watchlist_repo.bulk_update_sort_order(user_id, pairs)

        # 3. 업데이트된 목록 반환
        return await self.get_watchlist(user_id, None)

    # ── Private: 시세 병합 ──────────────────────────────────────────────────────

    async def _enrich_with_prices(self, coins: list[Coin]) -> list[CoinResponse]:
        """Redis pipeline으로 ticker 일괄 조회 → CoinResponse 병합.

        Redis 연결 실패 시 price=None으로 graceful degradation.
        """
        if not coins:
            return []

        keys = [RedisKey.ticker(c.exchange_type, c.market_code) for c in coins]
        pipe = self._redis.pipeline(transaction=False)
        for key in keys:
            pipe.get(key)

        try:
            results = await pipe.execute()
        except Exception:
            results = [None] * len(coins)

        return [
            self._build_coin_response(coin, json.loads(raw) if raw else None)
            for coin, raw in zip(coins, results)
        ]

    async def _get_ticker_snapshot(
        self, exchange_type: str, market_code: str
    ) -> dict | None:
        """단건 ticker 조회."""
        try:
            raw = await self._redis.get(
                RedisKey.ticker(exchange_type, market_code)
            )
            return json.loads(raw) if raw else None
        except Exception:
            return None

    @staticmethod
    def _build_coin_response(coin: Coin, ticker: dict | None) -> CoinResponse:
        def _dec(val: object) -> Decimal | None:
            if val is None:
                return None
            try:
                return Decimal(str(val))
            except Exception:
                return None

        return CoinResponse(
            id=coin.id,
            symbol=coin.symbol,
            name_ko=coin.name_ko,
            name_en=coin.name_en,
            exchange_type=coin.exchange_type,
            market_code=coin.market_code,
            is_active=coin.is_active,
            current_price=_dec(ticker.get("current_price")) if ticker else None,
            change_rate_24h=_dec(ticker.get("change_rate_24h")) if ticker else None,
            volume_24h=_dec(ticker.get("volume_24h")) if ticker else None,
            open_price=_dec(ticker.get("open_price")) if ticker else None,
            high_price=_dec(ticker.get("high_price")) if ticker else None,
            low_price=_dec(ticker.get("low_price")) if ticker else None,
            price_updated_at=ticker.get("price_updated_at") if ticker else None,
        )

"""포트폴리오 조회 비즈니스 로직 서비스."""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from redis.asyncio import Redis

from app.core.exceptions import ExchangeErrors, PortfolioErrors
from app.core.redis_keys import RedisKey, RedisTTL
from app.providers.enums import ExchangeType
from app.providers.types import Balance, SymbolMapper
from app.repositories.exchange_account_repository import ExchangeAccountRepository
from app.repositories.portfolio_repository import PortfolioRepository
from app.schemas.portfolio import (
    AvgEntryPrice,
    CoinHolding,
    ExchangePortfolioResponse,
    ExchangeSummary,
    PortfolioSummaryResponse,
    TopCoin,
    TradeCounts,
)
from app.services.market_cache_service import MarketCacheService

if TYPE_CHECKING:
    from app.core.config import Settings
    from app.models.exchange import UserExchangeAccount
    from app.providers.factory import ExchangeProviderFactory

logger = logging.getLogger(__name__)

_ZERO = Decimal("0")
_HUNDRED = Decimal("100")
_TWO_PLACES = Decimal("0.01")


class PortfolioService:
    """포트폴리오 조회 비즈니스 로직.

    거래소 잔고 수집, 시세 조회, PnL 계산, Redis 캐시 관리를 오케스트레이션한다.
    """

    def __init__(
        self,
        portfolio_repo: PortfolioRepository,
        exchange_account_repo: ExchangeAccountRepository,
        factory: ExchangeProviderFactory,
        market_cache: MarketCacheService,
        redis: Redis,
        settings: Settings,
    ) -> None:
        self._portfolio_repo = portfolio_repo
        self._exchange_account_repo = exchange_account_repo
        self._factory = factory
        self._market_cache = market_cache
        self._redis = redis
        self._settings = settings

    # ── Public API ────────────────────────────────────────────────────────────

    async def get_portfolio_summary(
        self, user_id: uuid.UUID
    ) -> PortfolioSummaryResponse:
        """전체 자산 요약 — 모든 거래소 합산.

        Redis 캐시 HIT 시 즉시 반환. MISS 시 거래소별 병렬 수집 후 캐시 저장.
        거래소 조회 부분 실패 허용: 특정 거래소 실패 시 해당 거래소 제외, 나머지 반환.

        Args:
            user_id: 사용자 ID.

        Returns:
            PortfolioSummaryResponse

        Raises:
            AppError(PORTFOLIO_NO_EXCHANGE_ACCOUNTS): 등록된 거래소 계정 없음.
        """
        cache_key = RedisKey.portfolio_summary(str(user_id))
        cached = await self._get_cached(cache_key)
        if cached is not None:
            return PortfolioSummaryResponse(**cached)

        accounts = await self._exchange_account_repo.get_by_user_id(user_id)

        # 거래소 계정 없으면 빈 포트폴리오 반환 (404 대신 빈 데이터)
        if not accounts:
            response = PortfolioSummaryResponse(
                total_balance_krw=None,
                total_pnl_amount=None,
                total_pnl_ratio=None,
                total_trade_count=0,
                ai_pnl_amount=None,
                ai_pnl_ratio=None,
                ai_trade_count=0,
                manual_pnl_amount=None,
                manual_pnl_ratio=None,
                manual_trade_count=0,
                by_exchange=[],
                top_coins=[],
                cached_at=None,
            )
            return response

        # 거래소별 데이터 병렬 수집 (부분 실패 허용)
        results = await asyncio.gather(
            *[self._fetch_exchange_data(account) for account in accounts],
            return_exceptions=True,
        )

        by_exchange: list[ExchangeSummary] = []
        all_coins: list[tuple[TopCoin, Decimal | None]] = []  # (coin, value_krw)
        total_balance = _ZERO
        total_pnl = _ZERO
        total_cost = _ZERO  # 총 투자 원금 (비율 계산용)

        for account, result in zip(accounts, results, strict=False):
            if isinstance(result, Exception):
                logger.warning(
                    "Exchange data fetch failed for account %s (%s): %s",
                    account.id,
                    account.exchange_type,
                    result,
                )
                continue

            holdings, avg_prices = result
            exchange_balance = _ZERO
            exchange_pnl = _ZERO
            exchange_cost = _ZERO

            for holding in holdings:
                if holding.value_krw is not None:
                    exchange_balance += holding.value_krw
                if holding.pnl_amount is not None:
                    exchange_pnl += holding.pnl_amount
                if holding.avg_entry_price is not None and holding.quantity > _ZERO:
                    exchange_cost += holding.avg_entry_price * holding.quantity

                # top_coins 후보 (KRW 제외)
                if holding.currency != "KRW":
                    top_coin = TopCoin(
                        symbol=holding.symbol,
                        exchange_type=account.exchange_type,
                        quantity=holding.quantity,
                        avg_price=holding.avg_entry_price,
                        current_price=holding.current_price,
                        pnl_amount=holding.pnl_amount,
                    )
                    all_coins.append((top_coin, holding.value_krw))

            exchange_pnl_ratio = self._calc_pnl_ratio_from_cost(exchange_pnl, exchange_cost)
            by_exchange.append(
                ExchangeSummary(
                    exchange_account_id=account.id,
                    exchange_type=account.exchange_type,
                    nickname=account.nickname,
                    balance_krw=exchange_balance if exchange_balance > _ZERO else None,
                    pnl_amount=exchange_pnl if exchange_pnl != _ZERO else None,
                    pnl_ratio=exchange_pnl_ratio,
                )
            )
            total_balance += exchange_balance
            total_pnl += exchange_pnl
            total_cost += exchange_cost

        # 거래 통계
        trade_stats = await self._portfolio_repo.get_trade_stats(user_id)

        # 총 수익률 계산 (투자 원금 기준)
        total_pnl_ratio = self._calc_pnl_ratio_from_cost(total_pnl, total_cost)

        # AI/수동 PnL 분리는 현재 TradeOrder로만 집계 (미실현 분리 없음)
        # AI/수동 수익률은 N/A (청산 PnL은 TradeLog에서 관리, 범위 외)
        ai_pnl: Decimal | None = None
        ai_pnl_ratio: Decimal | None = None
        manual_pnl: Decimal | None = None
        manual_pnl_ratio: Decimal | None = None

        # 상위 5 코인 (value_krw 기준 내림차순)
        all_coins.sort(key=lambda x: x[1] or _ZERO, reverse=True)
        top_coins = [coin for coin, _ in all_coins[:5]]

        response = PortfolioSummaryResponse(
            total_balance_krw=total_balance if total_balance > _ZERO else None,
            total_pnl_amount=total_pnl if total_pnl != _ZERO else None,
            total_pnl_ratio=total_pnl_ratio,
            total_trade_count=trade_stats.total,
            ai_pnl_amount=ai_pnl,
            ai_pnl_ratio=ai_pnl_ratio,
            ai_trade_count=trade_stats.ai_count,
            manual_pnl_amount=manual_pnl,
            manual_pnl_ratio=manual_pnl_ratio,
            manual_trade_count=trade_stats.manual_count,
            by_exchange=by_exchange,
            top_coins=top_coins,
            cached_at=None,  # fresh 응답 — None 유지
        )

        # 캐시 저장 시 cached_at을 저장 시각으로 설정 → HIT 시 non-null 반환
        cache_data = json.loads(response.model_dump_json())
        cache_data["cached_at"] = datetime.now(UTC).isoformat()
        await self._set_cache(cache_key, cache_data, RedisTTL.PORTFOLIO_SUMMARY)
        return response

    async def get_exchange_portfolio(
        self, user_id: uuid.UUID, exchange_account_id: uuid.UUID
    ) -> ExchangePortfolioResponse:
        """거래소별 상세 포트폴리오.

        Args:
            user_id: 현재 사용자 ID.
            exchange_account_id: 조회할 거래소 계정 ID.

        Returns:
            ExchangePortfolioResponse

        Raises:
            AppError(EXCHANGE_ACCOUNT_NOT_FOUND): 계정 존재하지 않음.
            AppError(PORTFOLIO_EXCHANGE_ACCOUNT_NOT_OWNED): 타 사용자 소유 계정.
            AppError(PORTFOLIO_BALANCE_FETCH_FAILED): 잔고 조회 실패.
        """
        account = await self._exchange_account_repo.get_by_id(exchange_account_id)
        if account is None:
            raise ExchangeErrors.account_not_found()
        if account.user_id != user_id:
            raise PortfolioErrors.exchange_account_not_owned()

        cache_key = RedisKey.portfolio_exchange(str(user_id), str(exchange_account_id))
        cached = await self._get_cached(cache_key)
        if cached is not None:
            return ExchangePortfolioResponse(**cached)

        balances = await self._fetch_balances(account)
        balance_fetched_at = datetime.now(UTC)

        avg_prices = await self._get_avg_prices_cached(user_id, exchange_account_id)

        # KRW 잔고 분리
        krw_balance: Decimal | None = None
        coin_balances = []
        for b in balances:
            if b.currency == "KRW":
                krw_balance = b.total
            else:
                coin_balances.append(b)

        # 코인별 현재가 조회
        exchange_type = account.exchange_type
        symbols = [f"{b.currency}/KRW" for b in coin_balances]
        current_prices = await self._get_current_prices(exchange_type, symbols)

        # 총자산 계산 (비중 계산용)
        total_value = krw_balance or _ZERO
        for b in coin_balances:
            symbol = f"{b.currency}/KRW"
            price = current_prices.get(symbol)
            if price is not None:
                total_value += price * b.total

        # CoinHolding 목록 생성
        holdings: list[CoinHolding] = []

        for b in coin_balances:
            symbol = f"{b.currency}/KRW"
            current_price = current_prices.get(symbol)
            value_krw = (current_price * b.total) if current_price is not None else None

            # 평균 매입가: avg_prices는 currency 키 (e.g. "BTC") 로 직접 조회
            avg_entry = avg_prices.get(b.currency)
            avg_entry_price = avg_entry.avg_price if avg_entry is not None else None

            pnl_amount: Decimal | None = None
            pnl_ratio: Decimal | None = None
            if current_price is not None and avg_entry_price is not None:
                pnl_amount, pnl_ratio = self._calculate_coin_pnl(
                    current_price, avg_entry_price, b.total
                )

            # 비중 계산: 총자산(KRW 포함) 대비 해당 코인 가치 비율
            # KRW는 krw_balance 필드로 별도 제공 — 클라이언트에서 KRW 슬라이스 추가
            # coins[].weight_percent + KRW 암묵 비중 = 100% (클라이언트 합산 기준)
            weight_percent: Decimal | None = None
            if total_value > _ZERO and value_krw is not None:
                weight_percent = (value_krw / total_value * _HUNDRED).quantize(_TWO_PLACES)

            holdings.append(
                CoinHolding(
                    symbol=symbol,
                    currency=b.currency,
                    quantity=b.total,
                    available=b.available,
                    locked=b.locked,
                    avg_entry_price=avg_entry_price,
                    current_price=current_price,
                    value_krw=value_krw,
                    pnl_amount=pnl_amount,
                    pnl_ratio=pnl_ratio,
                    weight_percent=weight_percent,
                )
            )

        total_balance_krw = total_value if total_value > _ZERO else None

        response = ExchangePortfolioResponse(
            exchange_account_id=exchange_account_id,
            exchange_type=exchange_type,
            nickname=account.nickname,
            total_balance_krw=total_balance_krw,
            krw_balance=krw_balance,
            coins=holdings,
            balance_fetched_at=balance_fetched_at,
            cached_at=None,  # fresh 응답 — None 유지
        )

        # 캐시 저장 시 cached_at을 저장 시각으로 설정 → HIT 시 non-null 반환
        cache_data = json.loads(response.model_dump_json())
        cache_data["cached_at"] = datetime.now(UTC).isoformat()
        await self._set_cache(cache_key, cache_data, RedisTTL.PORTFOLIO_EXCHANGE)
        return response

    async def invalidate_cache(
        self, user_id: uuid.UUID, exchange_account_id: uuid.UUID
    ) -> None:
        """캐시 무효화 — 주문 체결(filled) 시 OrderService에서 호출.

        Args:
            user_id: 사용자 ID.
            exchange_account_id: 거래소 계정 ID.
        """
        try:
            await self._redis.delete(
                RedisKey.portfolio_summary(str(user_id)),
                RedisKey.portfolio_exchange(str(user_id), str(exchange_account_id)),
                RedisKey.portfolio_avg_price(str(user_id), str(exchange_account_id)),
            )
        except Exception:
            logger.warning(
                "Cache invalidation failed: user=%s, account=%s", user_id, exchange_account_id
            )

    # ── 내부 헬퍼 ────────────────────────────────────────────────────────────

    async def _fetch_exchange_data(
        self, account: UserExchangeAccount
    ) -> tuple[list[CoinHolding], dict[str, AvgEntryPrice]]:
        """단일 거래소 계정의 보유 현황 + 평균 매입가 조회.

        Args:
            account: 거래소 계정 ORM 객체.

        Returns:
            (holdings, avg_prices) 튜플.

        Raises:
            Exception: 거래소 API 호출 실패 시 (상위에서 return_exceptions=True로 처리).
        """
        user_id = account.user_id
        exchange_account_id = account.id

        balances, avg_prices = await asyncio.gather(
            self._fetch_balances(account),
            self._get_avg_prices_cached(user_id, exchange_account_id),
            return_exceptions=False,
        )

        exchange_type = account.exchange_type
        coin_balances = [b for b in balances if b.currency != "KRW"]
        krw_balances = [b for b in balances if b.currency == "KRW"]

        symbols = [f"{b.currency}/KRW" for b in coin_balances]
        current_prices = await self._get_current_prices(exchange_type, symbols)

        holdings: list[CoinHolding] = []

        # KRW 잔고도 포함 (총자산 계산용)
        for b in krw_balances:
            holdings.append(
                CoinHolding(
                    symbol="KRW",
                    currency="KRW",
                    quantity=b.total,
                    available=b.available,
                    locked=b.locked,
                    avg_entry_price=None,
                    current_price=Decimal("1"),
                    value_krw=b.total,
                    pnl_amount=None,
                    pnl_ratio=None,
                    weight_percent=None,
                )
            )

        # 코인 잔고 — avg_prices는 currency 키 (e.g. "BTC")로 직접 조회
        for b in coin_balances:
            symbol = f"{b.currency}/KRW"
            current_price = current_prices.get(symbol)
            value_krw = (current_price * b.total) if current_price is not None else None

            avg_entry = avg_prices.get(b.currency)
            avg_entry_price = avg_entry.avg_price if avg_entry is not None else None

            pnl_amount: Decimal | None = None
            pnl_ratio: Decimal | None = None
            if current_price is not None and avg_entry_price is not None:
                pnl_amount, pnl_ratio = self._calculate_coin_pnl(
                    current_price, avg_entry_price, b.total
                )

            holdings.append(
                CoinHolding(
                    symbol=symbol,
                    currency=b.currency,
                    quantity=b.total,
                    available=b.available,
                    locked=b.locked,
                    avg_entry_price=avg_entry_price,
                    current_price=current_price,
                    value_krw=value_krw,
                    pnl_amount=pnl_amount,
                    pnl_ratio=pnl_ratio,
                    weight_percent=None,
                )
            )

        return holdings, avg_prices

    async def _fetch_balances(
        self, account: UserExchangeAccount
    ) -> list[Balance]:
        """거래소 잔고 조회 (Provider API 호출).

        1. Factory.create_from_account() → provider.get_balance()
        2. finally: provider.close() 보장

        Args:
            account: 거래소 계정 ORM 객체.

        Returns:
            Balance 목록.

        Raises:
            AppError: 거래소 API 호출 실패 또는 Circuit Breaker OPEN.
        """
        enc_key = self._get_encryption_key()
        provider = None
        try:
            provider = await self._factory.create_from_account(account, enc_key)
            return await provider.get_balance()
        except Exception as exc:
            logger.warning(
                "Balance fetch failed for account %s (%s): %s",
                account.id,
                account.exchange_type,
                exc,
            )
            raise PortfolioErrors.balance_fetch_failed(account.exchange_type) from exc
        finally:
            if provider is not None:
                try:
                    await provider.close()
                except Exception:
                    pass

    async def _get_avg_prices_cached(
        self,
        user_id: uuid.UUID,
        exchange_account_id: uuid.UUID,
    ) -> dict[str, AvgEntryPrice]:
        """평균 매입가 조회 (Redis 캐시 10분 TTL).

        Args:
            user_id: 사용자 ID.
            exchange_account_id: 거래소 계정 ID.

        Returns:
            {currency: AvgEntryPrice} e.g. {"BTC": AvgEntryPrice(...)}
        """
        cache_key = RedisKey.portfolio_avg_price(str(user_id), str(exchange_account_id))
        cached = await self._get_cached(cache_key)
        if cached is not None:
            return {k: AvgEntryPrice(**v) for k, v in cached.items()}

        avg_prices = await self._portfolio_repo.get_avg_entry_prices(
            user_id, exchange_account_id
        )

        serialized = {
            str(k): v.model_dump(mode="json") for k, v in avg_prices.items()
        }
        await self._set_cache(cache_key, serialized, RedisTTL.PORTFOLIO_AVG_PRICE)
        return avg_prices

    async def _get_current_prices(
        self, exchange_type: str, symbols: list[str]
    ) -> dict[str, Decimal]:
        """심볼별 현재가 일괄 조회 (MarketCacheService 우선).

        KRW 기축 거래소만 지원 (별도 환율 변환 불필요).

        Args:
            exchange_type: 거래소 타입 문자열 (e.g. "upbit").
            symbols: 정규화 심볼 목록 (e.g. ["BTC/KRW", "ETH/KRW"]).

        Returns:
            {symbol: current_price (KRW)}
        """
        prices: dict[str, Decimal] = {}
        try:
            exchange_enum = ExchangeType(exchange_type)
        except ValueError:
            logger.warning("Unknown exchange type: %s", exchange_type)
            return prices

        for symbol in symbols:
            try:
                market = SymbolMapper.to_market(exchange_enum, symbol)
                ticker_data = await self._market_cache.get_ticker(exchange_type, market)
                if ticker_data is not None:
                    prices[symbol] = Decimal(str(ticker_data["price"]))
            except Exception:
                logger.debug("Price lookup failed for symbol %s on %s", symbol, exchange_type)
                # graceful degradation: 해당 심볼 가격 없음 → None 처리

        return prices

    @staticmethod
    def _calculate_coin_pnl(
        current_price: Decimal,
        avg_entry_price: Decimal,
        quantity: Decimal,
    ) -> tuple[Decimal, Decimal]:
        """단일 코인 미실현 PnL 계산 (순수 함수).

        Args:
            current_price: 현재가 (KRW).
            avg_entry_price: 가중 평균 매입가 (KRW).
            quantity: 보유 수량.

        Returns:
            (pnl_amount, pnl_ratio)
            pnl_amount = (current_price - avg_entry_price) * quantity
            pnl_ratio  = (current_price - avg_entry_price) / avg_entry_price * 100
            avg_entry_price == 0 → pnl_ratio = Decimal("0")
        """
        pnl_amount = (current_price - avg_entry_price) * quantity
        if avg_entry_price == _ZERO:
            pnl_ratio = _ZERO
        else:
            pnl_ratio = (current_price - avg_entry_price) / avg_entry_price * _HUNDRED
        return pnl_amount, pnl_ratio

    # ── 캐시 헬퍼 ─────────────────────────────────────────────────────────────

    async def _get_cached(self, key: str) -> dict | None:
        """Redis 캐시 조회 (graceful degradation).

        Args:
            key: Redis 키.

        Returns:
            dict 또는 None (캐시 없음 또는 오류).
        """
        try:
            raw = await self._redis.get(key)
            return json.loads(raw) if raw else None
        except Exception:
            return None

    async def _set_cache(self, key: str, data: dict, ttl: int) -> None:
        """Redis 캐시 저장 (graceful degradation).

        Args:
            key: Redis 키.
            data: 직렬화 가능한 dict.
            ttl: 만료 시간(초).
        """
        try:
            await self._redis.set(key, json.dumps(data, default=str), ex=ttl)
        except Exception:
            logger.warning("Cache write failed: %s", key)

    def _get_encryption_key(self) -> bytes:
        """EXCHANGE_API_KEY_SECRET → 32바이트 AES 키 반환.

        Raises:
            AppError(EXCHANGE_ENCRYPTION_NOT_CONFIGURED): 키 미설정.
        """
        secret = self._settings.EXCHANGE_API_KEY_SECRET
        if not secret:
            raise ExchangeErrors.encryption_key_not_configured()
        return bytes.fromhex(secret)

    @staticmethod
    def _calc_pnl_ratio_from_cost(
        pnl_amount: Decimal, cost: Decimal
    ) -> Decimal | None:
        """투자 원금 기준 수익률 계산.

        Args:
            pnl_amount: 평가손익.
            cost: 총 투자 원금.

        Returns:
            수익률 % 또는 None (원금 없음).
        """
        if cost == _ZERO:
            return None
        return (pnl_amount / cost * _HUNDRED).quantize(_TWO_PLACES)

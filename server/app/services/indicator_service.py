"""기술적 지표 계산 + Redis 캐싱 오케스트레이션 서비스."""
from __future__ import annotations

import logging
from datetime import UTC, datetime

from bson import Decimal128
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.exceptions import IndicatorErrors
from app.services.market_cache_service import MarketCacheService
from app.trading.indicators import CandleInput, IndicatorResult, calculate_all_indicators

logger = logging.getLogger(__name__)

# MongoDB 시계열 컬렉션명 패턴
_CANDLE_COLLECTION = "candle_data_{timeframe}"


def _dec128_to_float(value: object) -> float:
    """Decimal128 또는 기타 값을 float으로 변환."""
    if isinstance(value, Decimal128):
        return float(str(value))
    return float(value)


def _doc_to_candle(doc: dict) -> CandleInput:
    """MongoDB 캔들 도큐먼트 → CandleInput 변환."""
    ts = doc["timestamp"]
    if isinstance(ts, datetime):
        if ts.tzinfo is None:
            timestamp = ts.replace(tzinfo=UTC).timestamp()
        else:
            timestamp = ts.timestamp()
    else:
        timestamp = float(ts)

    return CandleInput(
        timestamp=timestamp,
        open=_dec128_to_float(doc["open"]),
        high=_dec128_to_float(doc["high"]),
        low=_dec128_to_float(doc["low"]),
        close=_dec128_to_float(doc["close"]),
        volume=_dec128_to_float(doc["volume"]),
    )


class IndicatorService:
    """기술적 지표 계산 + Redis 캐싱 오케스트레이션."""

    def __init__(self, market_cache: MarketCacheService, db: AsyncIOMotorDatabase) -> None:
        self._cache = market_cache
        self._db = db

    async def get_indicators(
        self,
        exchange: str,
        market: str,
        timeframe: str,
        limit: int = 200,
    ) -> IndicatorResult:
        """캐시 우선 조회, MISS 시 MongoDB 캔들로 계산.

        Args:
            exchange: 거래소 코드 (예: upbit).
            market: 마켓 코드 (예: KRW-BTC).
            timeframe: 타임프레임 (예: 1h).
            limit: 조회할 캔들 수. 기본 200.

        Returns:
            IndicatorResult: 계산된 기술적 지표.

        Raises:
            AppError(INSUFFICIENT_CANDLES): 캔들 수 부족.
            AppError(INDICATOR_CALCULATION_FAILED): 계산 오류.
        """
        # 1. 캐시 조회
        cached = await self._cache.get_indicators(exchange, market, timeframe)
        if cached is not None:
            return cached  # type: ignore[return-value]

        # 2. MongoDB에서 캔들 조회
        candles = await self._fetch_candles(exchange, market, timeframe, limit)

        if not candles:
            raise IndicatorErrors.insufficient_candles(required=1, actual=0)

        # 3. 지표 계산
        try:
            result = calculate_all_indicators(candles)
        except ValueError as e:
            logger.warning("Indicator calculation ValueError: %s", e)
            raise IndicatorErrors.insufficient_candles(required=1, actual=0)
        except Exception as e:
            logger.error("Indicator calculation failed: %s", e, exc_info=True)
            raise IndicatorErrors.calculation_failed()

        # 4. 캐시 저장 (fire-and-forget 방식으로 실패해도 결과는 반환)
        try:
            await self._cache.set_indicators(exchange, market, timeframe, result)  # type: ignore[arg-type]
        except Exception as e:
            logger.warning("Failed to cache indicators: %s", e)

        return result

    async def _fetch_candles(
        self,
        exchange: str,
        market: str,
        timeframe: str,
        limit: int,
    ) -> list[CandleInput]:
        """MongoDB 시계열 컬렉션에서 캔들 데이터 조회.

        Args:
            exchange: 거래소 코드.
            market: 마켓 코드.
            timeframe: 타임프레임.
            limit: 최대 캔들 수.

        Returns:
            시간순 정렬된 CandleInput 리스트 (오래된 것 먼저).
        """
        collection_name = _CANDLE_COLLECTION.format(timeframe=timeframe)
        collection = self._db[collection_name]

        cursor = (
            collection.find(
                {"meta.exchange_type": exchange, "meta.market_code": market},
                {"_id": 0, "timestamp": 1, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1},
            )
            .sort("timestamp", -1)
            .limit(limit)
        )

        docs = await cursor.to_list(length=limit)
        if not docs:
            return []

        # 내림차순 → 오름차순 (오래된 것 먼저)
        docs.reverse()
        return [_doc_to_candle(doc) for doc in docs]

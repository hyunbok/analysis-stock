"""
MongoDB Time Series collections for candle (OHLCV) data.

Uses Motor directly instead of Beanie Document, as MongoDB Time Series
collections have restrictions incompatible with Beanie's document model.
"""

from datetime import datetime, timezone
from typing import Optional

from bson import Decimal128
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, Field


class CandleMeta(BaseModel):
    """Embedded metadata for time series candle documents."""

    exchange_type: str  # upbit / coinone / coinbase / binance
    market_code: str  # e.g. KRW-BTC


class CandleData(BaseModel):
    """
    Pydantic model for a single candle (OHLCV) document stored in a
    MongoDB Time Series collection.  Motor is used directly for reads/writes;
    this class handles serialisation only.
    """

    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Candle open time (UTC-aware)",
    )
    meta: CandleMeta
    open: Decimal128
    high: Decimal128
    low: Decimal128
    close: Decimal128
    volume: Decimal128
    trade_count: Optional[int] = None

    model_config = {"arbitrary_types_allowed": True}


# ---------------------------------------------------------------------------
# Time-frame configuration
# ---------------------------------------------------------------------------

TIMEFRAME_CONFIG: dict[str, dict] = {
    "1m": {"granularity": "seconds", "ttl_seconds": 604800},       # 7 days
    "5m": {"granularity": "minutes", "ttl_seconds": 7776000},      # 90 days
    "15m": {"granularity": "minutes", "ttl_seconds": 15552000},    # 180 days
    "1h": {"granularity": "hours", "ttl_seconds": 31536000},       # 1 year
    "4h": {"granularity": "hours", "ttl_seconds": 63072000},       # 2 years
    "1d": {"granularity": "hours", "ttl_seconds": 157680000},      # 5 years
}


# ---------------------------------------------------------------------------
# Collection initialisation
# ---------------------------------------------------------------------------

async def init_timeseries_collections(db: AsyncIOMotorDatabase) -> None:
    """Create MongoDB Time Series collections for each candle timeframe.

    Skips creation if the collection already exists.  Also ensures a compound
    index on (meta.exchange_type, meta.market_code, timestamp DESC) for
    efficient range queries per market.

    Args:
        db: An active Motor ``AsyncIOMotorDatabase`` instance.
    """
    existing_collections: list[str] = await db.list_collection_names()

    for timeframe, cfg in TIMEFRAME_CONFIG.items():
        coll_name = f"candle_data_{timeframe}"

        if coll_name not in existing_collections:
            await db.create_collection(
                coll_name,
                timeseries={
                    "timeField": "timestamp",
                    "metaField": "meta",
                    "granularity": cfg["granularity"],
                },
                expireAfterSeconds=cfg["ttl_seconds"],
            )

        collection = db[coll_name]
        await collection.create_index(
            [
                ("meta.exchange_type", 1),
                ("meta.market_code", 1),
                ("timestamp", -1),
            ],
        )

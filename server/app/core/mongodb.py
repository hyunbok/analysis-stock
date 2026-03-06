from beanie import init_beanie
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.core.config import settings
from app.documents import (
    TradeLog,
    AiDecision,
    DailyPnlReport,
    Notification,
    AuditLog,
    NewsData,
    init_timeseries_collections,
)

ALL_DOCUMENT_MODELS = [
    TradeLog,
    AiDecision,
    DailyPnlReport,
    Notification,
    AuditLog,
    NewsData,
]

mongo_client: AsyncIOMotorClient | None = None
_mongodb: AsyncIOMotorDatabase | None = None


async def init_mongodb() -> None:
    global mongo_client, _mongodb
    mongo_client = AsyncIOMotorClient(
        settings.MONGODB_URL,
        maxPoolSize=settings.MONGODB_MAX_POOL_SIZE,
        minPoolSize=1,
    )
    db = mongo_client[settings.MONGODB_DB_NAME]
    _mongodb = db

    await init_beanie(
        database=db,
        document_models=ALL_DOCUMENT_MODELS,
    )

    # Time Series 컬렉션 초기화 (존재하지 않으면 생성)
    await init_timeseries_collections(db)


async def close_mongodb() -> None:
    global mongo_client, _mongodb
    if mongo_client:
        mongo_client.close()
        mongo_client = None
        _mongodb = None


def get_mongo_client() -> AsyncIOMotorClient:
    if mongo_client is None:
        raise RuntimeError("MongoDB not initialized")
    return mongo_client


def get_mongodb() -> AsyncIOMotorDatabase:
    """MongoDB 데이터베이스 인스턴스 반환 (DI용)."""
    if _mongodb is None:
        raise RuntimeError("MongoDB not initialized")
    return _mongodb

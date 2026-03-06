from beanie import init_beanie
from motor.motor_asyncio import AsyncIOMotorClient

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


async def init_mongodb() -> None:
    global mongo_client
    mongo_client = AsyncIOMotorClient(
        settings.MONGODB_URL,
        maxPoolSize=settings.MONGODB_MAX_POOL_SIZE,
        minPoolSize=1,
    )
    db = mongo_client[settings.MONGODB_DB_NAME]

    await init_beanie(
        database=db,
        document_models=ALL_DOCUMENT_MODELS,
    )

    # Time Series 컬렉션 초기화 (존재하지 않으면 생성)
    await init_timeseries_collections(db)


async def close_mongodb() -> None:
    global mongo_client
    if mongo_client:
        mongo_client.close()
        mongo_client = None


def get_mongo_client() -> AsyncIOMotorClient:
    if mongo_client is None:
        raise RuntimeError("MongoDB not initialized")
    return mongo_client

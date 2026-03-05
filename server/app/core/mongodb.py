from motor.motor_asyncio import AsyncIOMotorClient

_client: AsyncIOMotorClient | None = None


async def init_mongodb(db_url: str, db_name: str) -> None:
    global _client
    _client = AsyncIOMotorClient(
        db_url,
        maxPoolSize=20,
        minPoolSize=1,
    )
    # Beanie init will be called here once document models are defined:
    # from beanie import init_beanie
    # from app.documents import ALL_DOCUMENTS
    # await init_beanie(database=_client[db_name], document_models=ALL_DOCUMENTS)


def get_mongo_client() -> AsyncIOMotorClient:
    if _client is None:
        raise RuntimeError("MongoDB client not initialized. Call init_mongodb first.")
    return _client


async def close_mongodb() -> None:
    global _client
    if _client is not None:
        _client.close()
        _client = None

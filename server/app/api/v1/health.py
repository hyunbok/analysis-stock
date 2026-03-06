import asyncio
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.database import engine
from app.core.mongodb import get_mongo_client
from app.core.redis import get_redis
from app.schemas.health import ComponentStatus, HealthResponse

router = APIRouter()
logger = structlog.get_logger(__name__)


async def _check_postgres() -> str:
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return "up"
    except Exception as e:
        logger.error("postgres_health_check_failed", error=str(e))
        return "down"


async def _check_mongodb() -> str:
    try:
        client = get_mongo_client()
        await client.admin.command("ping")
        return "up"
    except Exception as e:
        logger.error("mongodb_health_check_failed", error=str(e))
        return "down"


async def _check_redis() -> str:
    try:
        redis = get_redis()
        await redis.ping()
        return "up"
    except Exception as e:
        logger.error("redis_health_check_failed", error=str(e))
        return "down"


@router.get("/health", response_model=HealthResponse)
async def health_check():
    pg_status, mongo_status, redis_status = await asyncio.gather(
        _check_postgres(),
        _check_mongodb(),
        _check_redis(),
    )

    all_healthy = all(s == "up" for s in [pg_status, mongo_status, redis_status])
    status = "healthy" if all_healthy else "unhealthy"

    response = HealthResponse(
        status=status,
        components=ComponentStatus(
            postgres=pg_status,
            mongodb=mongo_status,
            redis=redis_status,
        ),
        timestamp=datetime.now(timezone.utc),
    )

    http_status = 200 if all_healthy else 503
    return JSONResponse(
        content=response.model_dump(mode="json"),
        status_code=http_status,
    )

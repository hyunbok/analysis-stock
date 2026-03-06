"""공통 pytest fixtures: PostgreSQL + MongoDB."""

import os

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.database import Base

# 모든 PG 모델 등록
import app.models  # noqa: F401


def _get_test_pg_url() -> str:
    """TEST_DATABASE_URL 환경변수 우선, 없으면 기본 DB에 _test suffix."""
    if url := os.getenv("TEST_DATABASE_URL"):
        return url
    # postgresql+asyncpg://user:pass@host:port/dbname → .../dbname_test
    parts = settings.DATABASE_URL.rsplit("/", 1)
    return f"{parts[0]}/{parts[1]}_test"


def _get_test_mongo_db() -> str:
    return os.getenv("TEST_MONGODB_DB", "cointrader_test")


# ── PostgreSQL fixtures ───────────────────────────────────────────────────────

@pytest.fixture(scope="session")
async def pg_engine():
    """세션 시작 시 테스트 DB 테이블 생성, 종료 시 삭제."""
    engine = create_async_engine(_get_test_pg_url(), echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def db_session(pg_engine):
    """함수 범위 세션 - 테스트 후 자동 롤백."""
    async_session = async_sessionmaker(pg_engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        transaction = await session.begin()
        try:
            yield session
        finally:
            await transaction.rollback()


# ── MongoDB fixtures ──────────────────────────────────────────────────────────

def _build_mongo_document_models() -> list:
    from app.documents.trading_logs import AiDecision, DailyPnlReport, TradeLog
    from app.documents.notifications import Notification
    from app.documents.audit_logs import AuditLog
    from app.documents.news_data import NewsData

    return [TradeLog, AiDecision, DailyPnlReport, Notification, AuditLog, NewsData]


@pytest.fixture(scope="session")
async def mongo_client():
    """세션 범위 MongoDB 목 클라이언트 + Beanie 초기화."""
    try:
        from mongomock_motor import AsyncMongoMockClient
    except ImportError:
        pytest.skip("mongomock-motor not installed; skipping MongoDB tests")

    from beanie import init_beanie

    client = AsyncMongoMockClient()
    await init_beanie(
        database=client.get_database(_get_test_mongo_db()),
        document_models=_build_mongo_document_models(),
    )
    yield client


@pytest.fixture
async def mongo_db(mongo_client):
    """함수 범위 MongoDB - 테스트 후 컬렉션 초기화."""
    db = mongo_client.get_database(_get_test_mongo_db())
    yield db
    for coll_name in ["trade_logs", "ai_decisions", "daily_pnl_reports", "notifications", "audit_logs", "news_data"]:
        await db[coll_name].delete_many({})

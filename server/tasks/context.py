"""TaskContext: Celery 태스크에서 DB/Redis/MongoDB 연결 관리.

Celery worker 프로세스는 FastAPI lifespan과 독립적.
각 태스크는 asyncio.run()으로 진입하며, TaskContext.get()으로 연결 풀 재사용.
프로세스 내 싱글턴 — worker_max_tasks_per_child=100 시점에 자연 교체.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings
from app.core.mongodb import init_mongodb

logger = logging.getLogger(__name__)

_task_context: TaskContext | None = None


@dataclass
class TaskContext:
    """Worker 프로세스 내 공유 리소스 컨테이너."""

    redis: Redis
    engine: AsyncEngine
    motor_db: AsyncIOMotorDatabase
    _sessionmaker: async_sessionmaker = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._sessionmaker = async_sessionmaker(
            self.engine, class_=AsyncSession, expire_on_commit=False
        )

    @classmethod
    async def initialize(cls) -> TaskContext:
        """DB + Redis + MongoDB 연결 초기화.

        첫 태스크 진입 시 1회 호출, 이후 프로세스 내 재사용.
        """
        # Sentry (조건부)
        if settings.SENTRY_DSN:
            import sentry_sdk
            from sentry_sdk.integrations.celery import CeleryIntegration
            sentry_sdk.init(
                dsn=settings.SENTRY_DSN,
                integrations=[CeleryIntegration()],
                traces_sample_rate=0.1,
                environment=settings.ENV,
            )

        # SQLAlchemy AsyncEngine (worker 전용 — 작은 풀)
        engine = create_async_engine(
            settings.DATABASE_URL,
            pool_size=5,
            max_overflow=2,
        )

        # Redis (앱 캐시 DB 0 — Pub/Sub 발행 + 락 + 캐시 조회용)
        redis = Redis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            max_connections=10,
        )

        # Beanie 전역 초기화 (AiDecision.insert() 등 Document 직접 사용)
        await init_mongodb()

        # Motor 직접 클라이언트 (IndicatorService 의존)
        motor_client = AsyncIOMotorClient(settings.MONGODB_URL)
        motor_db = motor_client[settings.MONGODB_DB_NAME]

        # Exchange Provider Factory 싱글턴
        from app.providers.factory import ExchangeProviderFactory
        factory = ExchangeProviderFactory.init(redis=redis)
        factory.register_defaults()

        logger.info("TaskContext initialized (PG pool=5, Redis max=10)")
        return cls(redis=redis, engine=engine, motor_db=motor_db)

    @classmethod
    async def get(cls) -> TaskContext:
        """싱글턴 TaskContext 반환. 미초기화 시 자동 초기화."""
        global _task_context
        if _task_context is None:
            _task_context = await cls.initialize()
        return _task_context

    def create_session(self) -> AsyncSession:
        """SQLAlchemy AsyncSession 팩토리 (매 태스크 호출마다 새 세션)."""
        return self._sessionmaker()

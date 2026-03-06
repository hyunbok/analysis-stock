import logging
from contextlib import asynccontextmanager

import sentry_sdk
import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sentry_sdk.integrations.fastapi import FastApiIntegration

from app.core.config import settings
from app.core.database import init_db
from app.core.metrics import instrumentator
from app.core.mongodb import close_mongodb, init_mongodb
from app.core.redis import close_redis, init_redis
from app.middleware.correlation_id import CorrelationIdMiddleware
from app.middleware.error_handler import register_error_handlers
from app.middleware.rate_limit import RateLimitMiddleware

if settings.SENTRY_DSN:
    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        traces_sample_rate=0.1,
        profiles_sample_rate=0.1,
        integrations=[FastApiIntegration()],
        environment=settings.ENV,
    )


def configure_logging() -> None:
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer() if settings.DEBUG else structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(settings.LOG_LEVEL)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    # Startup
    await init_db()
    await init_mongodb()
    await init_redis(settings.REDIS_URL)

    yield

    # Shutdown
    await close_mongodb()
    await close_redis()


app = FastAPI(
    title="CoinTrader API",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
)

# 글로벌 에러 핸들러 등록
register_error_handlers(app)

# 미들웨어 등록 (순서 중요 — LIFO: 마지막 등록이 가장 외부에서 실행)
# 1. Prometheus instrumentator (가장 내부)
instrumentator.instrument(app).expose(app, endpoint="/metrics")

# 2. RateLimitMiddleware
app.add_middleware(RateLimitMiddleware)

# 3. CorrelationIdMiddleware
app.add_middleware(CorrelationIdMiddleware)

# 4. CORSMiddleware (가장 외부 — 마지막 등록)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Correlation-ID", "X-RateLimit-Remaining", "X-RateLimit-Retry-After-Ms"],
)

from app.api.v1 import router as v1_router  # noqa: E402

app.include_router(v1_router, prefix="/api/v1")

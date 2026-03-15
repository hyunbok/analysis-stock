# v1-19: Celery 비동기 작업 및 스케줄 구성

> **Status**: Done (구현 완료, 코드 리뷰 통과)
> **Branch**: `feature/v1-19_celery-async-tasks-schedule`
> **선행 태스크**: v1-15 (기술적 지표), v1-16 (장세 분류), v1-17 (전략 엔진), v1-18 (실행 엔진)
> **참조**: PRD §7.1, §7.2, §7.8

---

## 1. 개요

Celery Beat + Worker를 통해 AI 매매(5분 주기), 뉴스 스크랩(1시간), 일별 PnL 리포트, 만료 토큰 정리를 비동기 실행한다.

**핵심 아키텍처:**
```
┌─────────────┐         ┌──────────────────────┐         ┌─────────────┐
│  FastAPI     │◄───────►│       Redis           │◄───────►│  Celery      │
│  Server      │         │  DB 0: 캐시/Pub/Sub   │         │  Worker      │
│  - REST API  │         │  DB 1: Celery Broker  │         │  - ai_trading│
│  - WS Hub    │         │  DB 2: Celery Result  │         │  - news_scrap│
│  - 주문 실행 │         │                       │         │  - pnl_report│
└──────┬───────┘         └───────────────────────┘         └──────┬───────┘
       │                                                          │
       └──────────────────►  PostgreSQL + MongoDB  ◄──────────────┘
```

**v1-18과의 핵심 차이점**: v1-18은 `trading/execution/` 패키지 (ExecutionEngine 순수 오케스트레이터). v1-19는 Celery worker 프로세스에서 v1-15~18 모듈을 **조립하여 호출**하는 태스크 레이어.

**AI 매매 5단계 파이프라인 (5분 주기):**
```
Beat(5분) → run_all_active_configs()
  ├─ 마스터 스위치 체크 (settings.AI_TRADING_ENABLED + Redis kill switch)
  ├─ Redis Lock 획득 (중복 실행 방지)
  ├─ 활성 configs 조회 (user.ai_trading_enabled + config.is_enabled)
  └─ for each config:
       └─ run_single_config.delay(config_id)
            1. 데이터 수집: IndicatorService.get_indicators() → 5m/1h/4h 캔들+지표
            2. 장세 분석: RegimeService.detect() → RegimeResult
            3. 전략 선택: SignalGenerator.generate() → TradingSignal | None
            4. 주문 실행: ExecutionEngine.execute() → ExecutionResult
            5. 결과 알림: AICacheService → Redis Pub/Sub → WS Hub → Client
```

---

## 2. 패키지 구조

```
server/tasks/                          # Celery 패키지 (app/ 밖 — 독립 프로세스)
├── __init__.py                        # 패키지 마커 (비어있음)
├── celery_app.py                      # Celery 앱 초기화, 큐 라우팅, Beat 스케줄
├── context.py                         # TaskContext: 워커 프로세스 초기화, DB/Redis 싱글턴
├── ai_trading.py                      # AI 매매 태스크 (run_all, run_single, run_backtest)
├── news_scraper.py                    # 뉴스 스크랩 태스크
├── reports.py                         # 일별 PnL 리포트 태스크
└── cleanup.py                         # 만료 토큰 정리 태스크
```

**의존성 방향 (단방향):**
```
tasks/ → app.trading.execution.ExecutionEngine    (v1-18)
tasks/ → app.services.indicator_service           (v1-15)
tasks/ → app.services.regime_service              (v1-16)
tasks/ → app.trading.strategy.SignalGenerator      (v1-17)
tasks/ → app.services.ai_cache_service            (캐시/알림)
tasks/ → app.services.market_cache_service        (캐시)
tasks/ → app.core.database                        (PG — TaskContext에서 독립 engine 생성)
tasks/ → app.core.mongodb                         (Beanie 초기화)
tasks/ → app.core.config.settings                 (설정)
tasks/ → app.repositories.*                       (Repository)
tasks/ → app.providers.factory                    (거래소 Provider)

금지: tasks/ → app.api.*
금지: tasks/ → app.services.auth_service
금지: app.*  → tasks/  (역방향)
```

---

## 3. 상세 설계

### 3.1 celery_app.py — Celery 앱 초기화

```python
"""Celery 앱 설정 + Beat 스케줄 + 큐 라우팅.

실행 명령:
  Worker: celery -A tasks.celery_app.celery_app worker -l info -c 4 -Q ai,scraper,default
  Beat:   celery -A tasks.celery_app.celery_app beat -l info --scheduler celery.beat.PersistentScheduler
"""
from celery import Celery
from celery.schedules import crontab
from kombu import Queue

from app.core.config import settings

# ── Celery 앱 초기화 ──────────────────────────────────────────────────────────

celery_app = Celery("cointrader")

celery_app.conf.update(
    # Broker / Result Backend (Redis DB 분리)
    broker_url=settings.celery_broker_url,          # DB 1
    result_backend=settings.celery_result_backend,   # DB 2

    # 직렬화
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,

    # 큐 정의 (kombu Queue)
    task_queues=[
        Queue("ai"),
        Queue("scraper"),
        Queue("default"),
    ],
    task_default_queue="default",

    # 태스크 라우팅
    task_routes={
        "tasks.ai_trading.*":     {"queue": "ai"},
        "tasks.news_scraper.*":   {"queue": "scraper"},
        "tasks.reports.*":        {"queue": "default"},
        "tasks.cleanup.*":        {"queue": "default"},
    },

    # Beat 스케줄
    beat_schedule={
        "run-all-active-configs-every-5min": {
            "task": "tasks.ai_trading.run_all_active_configs",
            "schedule": 300.0,                          # 5분 (300초)
            "options": {"queue": "ai"},
        },
        "scrape-news-hourly": {
            "task": "tasks.news_scraper.scrape_news",
            "schedule": 3600.0,                         # 1시간
            "options": {"queue": "scraper"},
        },
        "generate-daily-pnl-reports": {
            "task": "tasks.reports.generate_daily_pnl_reports",
            "schedule": crontab(minute=5, hour=0),      # 매일 00:05 UTC
            "options": {"queue": "default"},
        },
        "cleanup-expired-tokens-daily": {
            "task": "tasks.cleanup.cleanup_expired_tokens",
            "schedule": crontab(minute=0, hour=3),      # 매일 03:00 UTC
            "options": {"queue": "default"},
        },
    },

    # Worker 설정
    worker_concurrency=settings.CELERY_WORKER_CONCURRENCY,  # 기본 4
    worker_prefetch_multiplier=1,           # 공정 분배 (긴 태스크 대비)
    worker_max_tasks_per_child=100,         # 메모리 누수 방지 (주기적 child 교체)
    worker_max_memory_per_child=512_000,    # 512MB 제한

    # 태스크 기본 타임아웃
    task_soft_time_limit=240,               # 4분 (soft — SoftTimeLimitExceeded 발생)
    task_time_limit=300,                    # 5분 (hard kill)

    # 안정성
    task_acks_late=True,                    # 실행 완료 후 ACK (worker 크래시 시 재실행)
    task_reject_on_worker_lost=True,        # worker 비정상 종료 시 재큐잉
    worker_send_task_events=True,           # 모니터링용 이벤트 전송
    task_send_sent_event=True,

    # Result backend
    result_expires=3600,                    # 1시간 후 결과 만료
)

# ── 태스크 모듈 자동 탐색 ──────────────────────────────────────────────────────

celery_app.autodiscover_tasks(["tasks"])
```

**설정 결정 근거:**

| 항목 | 결정 | 근거 |
|------|------|------|
| Broker | Redis DB 1 | 앱 캐시(DB 0)와 키 네임스페이스 충돌 방지 |
| Result Backend | Redis DB 2 | Broker와도 분리하여 완전한 격리 |
| 큐 정의 | kombu Queue | PRD §7.8.3 준수 (ai, scraper, default 3개) |
| `task_acks_late` | True | Worker 크래시 시 미완료 태스크 재실행 보장 |
| `worker_prefetch_multiplier` | 1 | AI 매매처럼 긴 태스크 공정 분배 |
| `worker_max_tasks_per_child` | 100 | 메모리 누수 방지 (worker 프로세스 주기적 교체) |
| Beat PnL | 00:05 UTC | KST 09:05, 거래일 정산 후 약간의 여유 |
| Worker pool | prefork (기본) | `asyncio.run()` 호환 (gevent/eventlet 충돌 방지) |

### 3.2 context.py — TaskContext (워커 프로세스 초기화)

Celery worker는 FastAPI lifespan과 분리된 별도 프로세스. **`asyncio.run()` per-task 패턴** 사용, 연결 풀은 프로세스 내 싱글턴으로 재사용.

```python
"""TaskContext: Celery 태스크에서 DB/Redis/MongoDB 연결 관리.

Celery worker 프로세스는 FastAPI lifespan과 독립적.
각 태스크는 asyncio.run()으로 진입하며, TaskContext.get()으로 연결 풀 재사용.
프로세스 내 싱글턴 — worker_max_tasks_per_child=100 시점에 자연 교체.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

import sentry_sdk
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from redis.asyncio import Redis
from sentry_sdk.integrations.celery import CeleryIntegration
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

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

    @classmethod
    async def initialize(cls) -> TaskContext:
        """DB + Redis + MongoDB 연결 초기화.

        첫 태스크 진입 시 1회 호출, 이후 프로세스 내 재사용.
        """
        # Sentry (조건부)
        if settings.SENTRY_DSN:
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
        return AsyncSession(bind=self.engine, expire_on_commit=False)
```

**설계 결정:**

| 항목 | 결정 | 근거 |
|------|------|------|
| 이벤트 루프 | `asyncio.run()` per-task | Celery prefork pool에서 안전, 루프 충돌 없음 |
| TaskContext | 프로세스 내 싱글턴 | 연결 풀 재사용, `worker_max_tasks_per_child`로 자연 갱신 |
| PG pool_size | 5 (worker 전용) | FastAPI의 20보다 작게 — worker는 동시 쿼리 적음 |
| Redis | 앱 DB 0 사용 | 캐시 조회, Pub/Sub 발행, 락은 앱과 동일 네임스페이스 필요 |
| Motor | 별도 클라이언트 | IndicatorService가 AsyncIOMotorDatabase 직접 의존 |
| Sentry | TaskContext.initialize() 내 | worker_process_init 시그널 대신 lazy 초기화 |
| 파일명 | `context.py` | `deps.py`는 FastAPI DI 관례, Celery 컨텍스트임을 명확화 |

### 3.3 ai_trading.py — AI 매매 태스크

```python
"""AI 매매 Celery 태스크.

Beat(5분) → run_all_active_configs()
  → for each active config: run_single_config.delay(config_id)
"""
import asyncio
import logging
import time
from decimal import Decimal
from uuid import UUID

from celery import Task
from celery.exceptions import SoftTimeLimitExceeded

from app.core.config import settings
from app.core.pubsub import RedisPublisher
from app.documents.trading_logs import AiDecision
from app.models.coin import Coin, WatchlistCoin
from app.models.exchange import UserExchangeAccount
from app.models.trading import AiTradingConfig
from app.models.user import User
from app.providers.exceptions import ExchangeNetworkError, ExchangeUnavailableError
from app.providers.factory import ExchangeProviderFactory
from app.repositories.order_repository import OrderRepository
from app.services.ai_cache_service import AICacheService
from app.services.indicator_service import IndicatorService
from app.services.market_cache_service import MarketCacheService
from app.services.regime_service import RegimeService
from app.trading.execution import ExecutionEngine
from app.trading.execution.drawdown_manager import DrawdownManager
from app.trading.execution.order_tracker import OrderTracker
from app.trading.execution.risk_manager import RiskManager
from app.trading.execution.trade_logger import TradeLogger
from app.trading.execution.types import RiskParams, TradeExecutionContext
from app.trading.strategy import SignalGenerator

from .celery_app import celery_app
from .context import TaskContext

logger = logging.getLogger(__name__)

# ── 중복 실행 방지 Redis Lock TTL ──────────────────────────────────────────────

_CYCLE_LOCK_TTL = 280       # 4분 40초 (5분 주기 - 20초 여유)
_SINGLE_LOCK_TTL = 270      # 4분 30초 (5분 주기 전 반드시 만료)


# ── 베이스 태스크 ──────────────────────────────────────────────────────────────

class BaseAsyncTask(Task):
    """asyncio.run() 래퍼 베이스 태스크."""
    abstract = True


# ── run_all_active_configs ─────────────────────────────────────────────────────

@celery_app.task(
    bind=True,
    base=BaseAsyncTask,
    name="tasks.ai_trading.run_all_active_configs",
    max_retries=0,               # Beat 스케줄 → 재시도 불필요 (다음 주기 재실행)
    queue="ai",
    soft_time_limit=240,         # 4분
    time_limit=300,              # 5분 hard kill
)
def run_all_active_configs(self) -> dict:
    """전체 활성 AI 매매 설정 순회 → 개별 태스크 dispatch.

    Flow 제어:
      - settings.AI_TRADING_ENABLED == False → 즉시 반환 (시스템 마스터 스위치)
      - Redis kill switch 존재 → 즉시 반환 (긴급 중지)
      - Redis Lock 미획득 → 스킵 (이전 사이클 진행 중)
      - user.ai_trading_enabled == False → 해당 사용자 config 제외
      - config.is_enabled == False → 해당 코인 제외
      - exchange_account.is_active/is_verified == False → 제외

    Returns:
        {"status": str, "dispatched": int, "skipped": int, "reason": str | None}
    """
    return asyncio.run(_run_all_active_configs_async(self))


async def _run_all_active_configs_async(task) -> dict:
    """run_all_active_configs의 async 구현."""
    ctx = await TaskContext.get()

    # 시스템 마스터 스위치 (Settings)
    if not settings.AI_TRADING_ENABLED:
        logger.info("AI trading disabled (settings)")
        return {"status": "skipped", "dispatched": 0, "skipped": 0, "reason": "master_switch_off"}

    # Redis 긴급 킬 스위치
    kill = await ctx.redis.get("system:ai_trading:kill")
    if kill:
        logger.warning("AI trading globally disabled (kill switch)")
        return {"status": "skipped", "dispatched": 0, "skipped": 0, "reason": "kill_switch"}

    # 중복 실행 방지 (SET NX)
    lock_key = "celery:lock:ai_trading_cycle"
    acquired = await ctx.redis.set(lock_key, task.request.id, nx=True, ex=_CYCLE_LOCK_TTL)
    if not acquired:
        logger.info("AI trading cycle already running, skipping.")
        return {"status": "skipped", "dispatched": 0, "skipped": 0, "reason": "lock_held"}

    try:
        from sqlalchemy import select
        from sqlalchemy.orm import joinedload

        async with ctx.create_session() as session:
            stmt = (
                select(AiTradingConfig)
                .join(AiTradingConfig.watchlist_coin)
                .join(WatchlistCoin.coin)
                .join(WatchlistCoin.exchange_account)
                .join(UserExchangeAccount.user)
                .where(
                    AiTradingConfig.is_enabled.is_(True),
                    User.ai_trading_enabled.is_(True),
                    UserExchangeAccount.is_active.is_(True),
                    UserExchangeAccount.is_verified.is_(True),
                )
                .options(
                    joinedload(AiTradingConfig.watchlist_coin)
                    .joinedload(WatchlistCoin.coin),
                    joinedload(AiTradingConfig.watchlist_coin)
                    .joinedload(WatchlistCoin.exchange_account),
                )
            )
            result = await session.execute(stmt)
            configs = result.scalars().unique().all()

        dispatched = 0
        for config in configs:
            run_single_config.delay(str(config.id))
            dispatched += 1

        logger.info("AI trading cycle: dispatched %d configs", dispatched)
        return {"status": "ok", "dispatched": dispatched, "skipped": 0, "reason": None}

    finally:
        await ctx.redis.delete(lock_key)


# ── run_single_config ──────────────────────────────────────────────────────────

@celery_app.task(
    bind=True,
    base=BaseAsyncTask,
    name="tasks.ai_trading.run_single_config",
    max_retries=3,
    queue="ai",
    soft_time_limit=90,          # 90초 (개별 코인)
    time_limit=120,              # 120초 hard kill
)
def run_single_config(self, config_id: str) -> dict:
    """단일 AI 매매 설정에 대한 5단계 파이프라인 실행.

    AI 매매 사이클:
      1. AiTradingConfig + WatchlistCoin + Coin + UserExchangeAccount 로드
      2. ExchangeProviderFactory → ExchangeRestProvider 획득
      3. IndicatorService.get_indicators() → 기술적 지표 (5m, 1h, 4h)
      4. RegimeService.detect() → 장세 분류 + GPT 검증
      5. SignalGenerator.generate() → 매매 신호 (None = HOLD)
      6. signal 있으면 → ExecutionEngine.execute()
      7. AiDecision Document insert (MongoDB)
      8. AICacheService.set_ai_decision() → Redis 캐시 + Pub/Sub

    Args:
        config_id: AiTradingConfig UUID (str)

    Returns:
        {"config_id": str, "status": str, "signal_action": str | None, ...}

    Retries:
        ExchangeNetworkError/ExchangeUnavailableError → countdown=2**attempt*60
    """
    try:
        return asyncio.run(_run_single_config_async(self, config_id))
    except SoftTimeLimitExceeded:
        logger.error("Single config timed out: %s", config_id)
        return {"config_id": config_id, "status": "timeout", "signal_action": None}
    except (ExchangeNetworkError, ExchangeUnavailableError) as exc:
        logger.warning("Retryable error for config %s: %s", config_id, exc)
        raise self.retry(
            exc=exc,
            countdown=2 ** self.request.retries * 60,  # 60s → 120s → 240s
        )
    except Exception as exc:
        logger.exception("Single config failed: %s", config_id)
        # Sentry 자동 캡처 (CeleryIntegration)
        return {"config_id": config_id, "status": "failed", "signal_action": None,
                "skipped_reason": str(exc)}


async def _run_single_config_async(task, config_id: str) -> dict:
    """run_single_config의 async 구현 — 5단계 파이프라인."""
    start_time = time.monotonic()
    ctx = await TaskContext.get()

    # 개별 config Redis Lock (동일 config 중복 실행 방지)
    lock_key = f"celery:lock:ai_trading:{config_id}"
    acquired = await ctx.redis.set(lock_key, task.request.id, nx=True, ex=_SINGLE_LOCK_TTL)
    if not acquired:
        return {"config_id": config_id, "status": "skipped", "signal_action": None,
                "skipped_reason": "duplicate_lock"}

    try:
        # ── 0. 설정 로드 ──────────────────────────────────────────────────────
        from sqlalchemy import select
        from sqlalchemy.orm import joinedload

        async with ctx.create_session() as session:
            stmt = (
                select(AiTradingConfig)
                .where(AiTradingConfig.id == UUID(config_id))
                .options(
                    joinedload(AiTradingConfig.watchlist_coin)
                    .joinedload(WatchlistCoin.coin),
                    joinedload(AiTradingConfig.watchlist_coin)
                    .joinedload(WatchlistCoin.exchange_account),
                )
            )
            result = await session.execute(stmt)
            config = result.scalar_one_or_none()

        if config is None or not config.is_enabled:
            return {"config_id": config_id, "status": "skipped", "signal_action": None,
                    "skipped_reason": "config_not_found_or_disabled"}

        watchlist_coin = config.watchlist_coin
        coin: Coin = watchlist_coin.coin
        exchange_account: UserExchangeAccount = watchlist_coin.exchange_account
        user_id = str(exchange_account.user_id)
        exchange_type = exchange_account.exchange_type
        market_code = coin.market_code
        symbol = coin.symbol

        # ── 의존성 조립 (매 태스크, 경량 생성자) ──────────────────────────────
        publisher = RedisPublisher(ctx.redis)
        market_cache = MarketCacheService(ctx.redis)
        ai_cache = AICacheService(ctx.redis, publisher)
        indicator_service = IndicatorService(market_cache, ctx.motor_db)
        regime_service = RegimeService(market_cache, ai_cache, settings)

        # ── 1. 데이터 수집 — 기술적 지표 계산 ─────────────────────────────────
        primary_tf = config.primary_timeframe  # 기본 "5m"
        indicators_5m = await indicator_service.get_indicators(
            exchange_type, market_code, primary_tf, limit=576,
        )
        if indicators_5m is None:
            return {"config_id": config_id, "status": "skipped", "signal_action": None,
                    "skipped_reason": "insufficient_candle_data"}

        # MTF 보조 타임프레임 (1h, 4h)
        confirmation_tfs = config.confirmation_timeframes or ["1h", "4h"]
        mtf_indicators = {}
        for tf in confirmation_tfs:
            ind = await indicator_service.get_indicators(
                exchange_type, market_code, tf, limit=200,
            )
            if ind is not None:
                mtf_indicators[tf] = ind

        # ── 2. 장세 분석 ──────────────────────────────────────────────────────
        regime_result = await regime_service.detect(
            exchange=exchange_type, market=market_code, indicators=indicators_5m,
            user_id=user_id, coin_symbol=symbol,
        )

        # ── 3. 전략 선택 + 신호 생성 ──────────────────────────────────────────
        candles_5m = await _fetch_candles(ctx.motor_db, exchange_type, market_code, primary_tf, 576)
        signal_generator = SignalGenerator()
        signal = signal_generator.generate(
            candles=candles_5m,
            indicators=indicators_5m,
            regime=regime_result,
            mtf_indicators=mtf_indicators,
        )

        # AI Decision 기록 (MongoDB)
        duration_ms = int((time.monotonic() - start_time) * 1000)
        ai_decision = AiDecision(
            user_id=UUID(user_id),
            coin_symbol=symbol,
            market_regime=regime_result["regime"],
            regime_confidence=regime_result["confidence"],
            selected_strategy=signal["strategy_name"] if signal else None,
            action=signal["action"] if signal else "hold",
            celery_task_id=task.request.id,
            analysis_duration_ms=duration_ms,
        )
        await ai_decision.insert()

        if signal is None:
            await ai_cache.set_ai_decision(user_id, market_code, {
                "regime": regime_result["regime"],
                "action": "hold",
                "reason": "no_signal",
            })
            await ai_cache.set_last_run(user_id, symbol)
            return {"config_id": config_id, "status": "hold", "signal_action": "hold",
                    "duration_ms": duration_ms}

        # ── 4. 주문 실행 ──────────────────────────────────────────────────────
        factory = ExchangeProviderFactory.instance()
        provider = await factory.get_provider(exchange_account)

        balance_info = await provider.get_balance()
        total_capital = balance_info.get("total_krw", 0)
        available_balance = balance_info.get("available_krw", 0)

        risk_params = RiskParams(
            max_investment_ratio=float(config.max_investment_ratio),
            stop_loss_ratio=float(config.stop_loss_ratio),
            take_profit_ratio=float(config.take_profit_ratio),
            daily_max_loss_ratio=float(config.daily_max_loss_ratio),
            max_active_positions=3,
            max_consecutive_losses=3,
            mdd_limit_ratio=0.15,
            win_rate_estimate=0.5,
            avg_rr_ratio=1.5,
        )

        context = TradeExecutionContext(
            user_id=user_id,
            exchange_account_id=str(exchange_account.id),
            coin_id=str(coin.id),
            market=market_code,
            symbol=symbol,
            signal=signal,
            risk_params=risk_params,
            total_capital=Decimal(str(total_capital)),
            available_balance=Decimal(str(available_balance)),
        )

        async with ctx.create_session() as session:
            order_repo = OrderRepository(session)
            engine = ExecutionEngine(
                risk_manager=RiskManager(),
                drawdown_manager=DrawdownManager(ctx.redis),
                order_tracker=OrderTracker(order_repo),
                trade_logger=TradeLogger(),
                provider=provider,
            )
            exec_result = await engine.execute(context)

        # ── 5. 결과 알림 ──────────────────────────────────────────────────────
        await ai_cache.set_ai_decision(user_id, market_code, {
            "regime": regime_result["regime"],
            "action": signal["action"],
            "strategy": signal["strategy_name"],
            "status": exec_result["status"],
            "order_id": exec_result.get("order_id"),
        })
        await ai_cache.set_last_run(user_id, symbol)

        if exec_result["status"] == "skipped":
            ai_decision.execution_skipped_reason = exec_result.get("skipped_reason")
            await ai_decision.save()

        total_duration_ms = int((time.monotonic() - start_time) * 1000)
        return {
            "config_id": config_id,
            "status": exec_result["status"],
            "signal_action": signal["action"],
            "execution_status": exec_result["status"],
            "skipped_reason": exec_result.get("skipped_reason"),
            "duration_ms": total_duration_ms,
        }

    finally:
        await ctx.redis.delete(lock_key)


async def _fetch_candles(motor_db, exchange_type, market_code, timeframe, limit):
    """MongoDB에서 캔들 데이터 조회 → CandleInput 리스트 변환."""
    from app.services.indicator_service import _doc_to_candle
    collection_name = f"candle_data_{timeframe}"
    collection = motor_db[collection_name]
    cursor = collection.find(
        {"exchange_type": exchange_type, "market_code": market_code},
        sort=[("timestamp", -1)],
        limit=limit,
    )
    docs = await cursor.to_list(length=limit)
    docs.reverse()  # 시간순 정렬
    return [_doc_to_candle(doc) for doc in docs]


# ── run_backtest (M9 스텁) ─────────────────────────────────────────────────────

@celery_app.task(
    bind=True,
    base=BaseAsyncTask,
    name="tasks.ai_trading.run_backtest",
    max_retries=0,
    queue="ai",
    time_limit=3600,             # 1시간 hard (M9 실제 구현 시)
)
def run_backtest(self, config_id: str, start_date: str, end_date: str) -> dict:
    """백테스트 실행 (M9 스텁).

    Args:
        config_id: AiTradingConfig UUID (str)
        start_date: 시작일 (YYYY-MM-DD)
        end_date:   종료일 (YYYY-MM-DD)

    Returns:
        M9 구현 후: total_trades, win_rate, total_pnl_ratio, max_drawdown, sharpe_ratio, trades
    """
    logger.info("Backtest stub called: config=%s, %s~%s", config_id, start_date, end_date)
    return {
        "config_id": config_id,
        "period": {"start": start_date, "end": end_date},
        "status": "not_implemented",
        "message": "백테스트 엔진은 M9에서 구현 예정",
    }
```

### 3.4 news_scraper.py — 뉴스 스크랩 태스크

```python
"""뉴스 수집 + GPT 감성 분석 태스크.

Beat(1시간) → scrape_news()
"""
import asyncio
import logging

from celery.exceptions import SoftTimeLimitExceeded

from .celery_app import celery_app
from .context import TaskContext

logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    name="tasks.news_scraper.scrape_news",
    max_retries=2,
    default_retry_delay=60,          # 1분 후 재시도
    queue="scraper",
    soft_time_limit=540,             # 9분
    time_limit=600,                  # 10분
)
def scrape_news(self, symbols: list[str] | None = None) -> dict:
    """뉴스 수집 + GPT 감성 분석.

    Flow:
      1. 활성 코인 목록 조회 (symbols=None이면 DB에서 전체)
      2. 외부 뉴스 API (CryptoPanic / NewsAPI) 크롤링
      3. NewsData Document insert (URL 중복 시 skip — unique index)
      4. GPT 감성 분석 → sentiment_score 업데이트
      5. AICacheService.set_news_sentiment() → Redis 캐시

    Args:
        symbols: 특정 심볼 리스트 (None이면 전체 활성 코인)

    Returns:
        {"scraped": int, "duplicates": int, "sentiment_updated": int, "failed": int}
    """
    from app.core.config import settings
    if not settings.NEWS_SCRAPER_ENABLED:
        return {"scraped": 0, "duplicates": 0, "sentiment_updated": 0, "failed": 0,
                "reason": "disabled"}

    try:
        return asyncio.run(_scrape_news_async(self, symbols))
    except SoftTimeLimitExceeded:
        logger.error("News scraper timed out")
        return {"scraped": 0, "duplicates": 0, "sentiment_updated": 0, "failed": 0,
                "reason": "timeout"}
    except Exception as exc:
        logger.exception("News scraper failed")
        raise self.retry(exc=exc)


async def _scrape_news_async(task, symbols: list[str] | None) -> dict:
    """scrape_news async 구현.

    v1-19 범위: 스캐폴딩 + 인터페이스만.
    실제 뉴스 소스 크롤러 및 GPT 감성 분석은 별도 태스크(v2)에서 구현.
    """
    ctx = await TaskContext.get()

    from app.core.pubsub import RedisPublisher
    from app.services.ai_cache_service import AICacheService
    publisher = RedisPublisher(ctx.redis)
    ai_cache = AICacheService(ctx.redis, publisher)

    # TODO: 뉴스 소스별 크롤링 로직 (CryptoPanic, NewsAPI, RSS)
    # TODO: GPT 감성 분석 배치 호출
    # TODO: NewsData.insert_many() + 중복 필터링
    # TODO: ai_cache.set_news_sentiment() 코인별 갱신

    logger.info("News scraper: stub completed (no sources configured)")
    return {"scraped": 0, "duplicates": 0, "sentiment_updated": 0, "failed": 0}
```

### 3.5 reports.py — 일별 PnL 리포트

```python
"""일별 PnL 리포트 생성 태스크.

Beat(매일 00:05 UTC) → generate_daily_pnl_reports()
"""
import asyncio
import logging
from datetime import date, datetime, timedelta, UTC
from decimal import Decimal
from uuid import UUID

from bson import Decimal128
from celery.exceptions import SoftTimeLimitExceeded

from .celery_app import celery_app
from .context import TaskContext

logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    name="tasks.reports.generate_daily_pnl_reports",
    max_retries=2,
    default_retry_delay=300,         # 5분 후 재시도
    queue="default",
    soft_time_limit=540,             # 9분
    time_limit=600,                  # 10분
)
def generate_daily_pnl_reports(self, report_date: str | None = None) -> dict:
    """전체 사용자 일일 PnL 리포트 생성.

    Flow:
      1. report_date 계산 (None → 어제 UTC 기준)
      2. TradeOrder에서 해당 날짜 체결 주문 조회 (user_id별 그룹)
      3. AI/수동 매매 분리 집계
      4. TradeLog에서 PnL/장세/전략별 통계 조회 (MongoDB)
      5. DailyPnlReport Document upsert (user_id + report_date unique)

    Args:
        report_date: 리포트 날짜 "YYYY-MM-DD" (None이면 전날)

    Returns:
        {"report_date": str, "users_processed": int, "reports_created": int}
    """
    try:
        return asyncio.run(_generate_daily_pnl_reports_async(self, report_date))
    except SoftTimeLimitExceeded:
        logger.error("PnL report generation timed out")
        return {"report_date": report_date, "users_processed": 0, "reports_created": 0}
    except Exception as exc:
        logger.exception("Daily PnL report generation failed")
        raise self.retry(exc=exc)


async def _generate_daily_pnl_reports_async(task, report_date_str: str | None) -> dict:
    """일별 PnL 리포트 async 구현."""
    from sqlalchemy import select, func, case
    from app.documents.trading_logs import DailyPnlReport, TradeLog
    from app.models.trading import TradeOrder

    ctx = await TaskContext.get()

    # 대상 날짜
    if report_date_str:
        report_dt = date.fromisoformat(report_date_str)
    else:
        report_dt = (datetime.now(UTC) - timedelta(days=1)).date()

    day_start = datetime(report_dt.year, report_dt.month, report_dt.day, tzinfo=UTC)
    day_end = day_start + timedelta(days=1)

    # 활성 사용자 (해당 날짜 체결 이력이 있는 사용자)
    async with ctx.create_session() as session:
        stmt = (
            select(TradeOrder.user_id)
            .where(
                TradeOrder.created_at >= day_start,
                TradeOrder.created_at < day_end,
                TradeOrder.status.in_(["filled", "partial"]),
            )
            .distinct()
        )
        result = await session.execute(stmt)
        user_ids = [row[0] for row in result.all()]

    generated = 0
    for uid in user_ids:
        try:
            await _generate_single_user_report(ctx, uid, report_dt, day_start, day_end)
            generated += 1
        except Exception as exc:
            logger.warning("PnL report failed for user %s: %s", uid, exc)

    logger.info("Daily PnL reports: generated %d for %s", generated, report_dt)
    return {"report_date": str(report_dt), "users_processed": len(user_ids),
            "reports_created": generated}


async def _generate_single_user_report(
    ctx: TaskContext, user_id: UUID, report_dt: date,
    day_start: datetime, day_end: datetime,
) -> None:
    """단일 사용자 일별 PnL 리포트 생성/업데이트."""
    from sqlalchemy import select, func, case
    from app.documents.trading_logs import DailyPnlReport, TradeLog
    from app.models.trading import TradeOrder

    # PG: 체결 주문 건수 집계 (AI/수동 분리)
    async with ctx.create_session() as session:
        stmt = select(
            func.count().label("total_count"),
            func.sum(case((TradeOrder.is_ai_order.is_(True), 1), else_=0)).label("ai_count"),
            func.sum(case((TradeOrder.is_ai_order.is_(False), 1), else_=0)).label("manual_count"),
        ).where(
            TradeOrder.user_id == user_id,
            TradeOrder.created_at >= day_start,
            TradeOrder.created_at < day_end,
            TradeOrder.status.in_(["filled", "partial"]),
        )
        result = await session.execute(stmt)
        row = result.one()
        trade_count = row.total_count or 0
        ai_trade_count = row.ai_count or 0
        manual_trade_count = row.manual_count or 0

    # MongoDB: TradeLog PnL 집계
    pipeline = [
        {"$match": {
            "user_id": str(user_id),
            "created_at": {"$gte": day_start, "$lt": day_end},
            "status": "closed",
        }},
        {"$group": {
            "_id": "$is_ai_order",
            "total_pnl": {"$sum": "$pnl_amount"},
            "win_count": {"$sum": {"$cond": [{"$gt": ["$pnl_amount", Decimal128("0")]}, 1, 0]}},
            "count": {"$sum": 1},
        }},
    ]
    trade_log_stats = await TradeLog.aggregate(pipeline).to_list()

    ai_pnl = Decimal("0")
    ai_win_count = 0
    manual_pnl = Decimal("0")
    for stat in trade_log_stats:
        pnl = float(str(stat["total_pnl"])) if stat["total_pnl"] else 0
        if stat["_id"] is True:
            ai_pnl = Decimal(str(pnl))
            ai_win_count = stat.get("win_count", 0)
        else:
            manual_pnl = Decimal(str(pnl))

    total_pnl = ai_pnl + manual_pnl
    win_count = sum(s.get("win_count", 0) for s in trade_log_stats)
    win_rate = Decimal(str(win_count / trade_count)) if trade_count > 0 else Decimal("0")

    # 누적 PnL (이전 리포트에서 조회)
    prev_report = await DailyPnlReport.find_one(
        DailyPnlReport.user_id == user_id,
        DailyPnlReport.report_date < report_dt,
        sort=[("report_date", -1)],
    )
    prev_cumulative = float(str(prev_report.cumulative_pnl)) if prev_report else 0
    cumulative_pnl = Decimal(str(prev_cumulative)) + total_pnl

    # Upsert (user_id + report_date unique index)
    existing = await DailyPnlReport.find_one(
        DailyPnlReport.user_id == user_id,
        DailyPnlReport.report_date == report_dt,
    )
    now = datetime.now(UTC)
    if existing:
        existing.total_pnl = Decimal128(str(total_pnl))
        existing.trade_count = trade_count
        existing.win_rate = Decimal128(str(win_rate))
        existing.ai_pnl = Decimal128(str(ai_pnl))
        existing.ai_trade_count = ai_trade_count
        existing.ai_win_count = ai_win_count
        existing.manual_pnl = Decimal128(str(manual_pnl))
        existing.manual_trade_count = manual_trade_count
        existing.cumulative_pnl = Decimal128(str(cumulative_pnl))
        existing.updated_at = now
        await existing.save()
    else:
        await DailyPnlReport(
            user_id=user_id,
            report_date=report_dt,
            total_pnl=Decimal128(str(total_pnl)),
            trade_count=trade_count,
            win_rate=Decimal128(str(win_rate)),
            ai_pnl=Decimal128(str(ai_pnl)),
            ai_trade_count=ai_trade_count,
            ai_win_count=ai_win_count,
            manual_pnl=Decimal128(str(manual_pnl)),
            manual_trade_count=manual_trade_count,
            cumulative_pnl=Decimal128(str(cumulative_pnl)),
        ).insert()
```

### 3.6 cleanup.py — 만료 토큰 정리

```python
"""만료 토큰/데이터 정리 태스크.

Beat(매일 03:00 UTC) → cleanup_expired_tokens()
"""
import asyncio
import logging
from datetime import datetime, timedelta, UTC

from .celery_app import celery_app
from .context import TaskContext

logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    name="tasks.cleanup.cleanup_expired_tokens",
    max_retries=1,
    default_retry_delay=300,
    queue="default",
    soft_time_limit=120,             # 2분
    time_limit=180,                  # 3분
)
def cleanup_expired_tokens(self) -> dict:
    """만료된 인증 관련 Redis 키 + soft deleted 사용자 정리.

    대상:
      1. soft_deleted 30일 경과 사용자의 refresh token 인덱스 정리
      2. 고아 상태 2FA pending 키 스캔 (TTL 없는 키 삭제)
      3. (향후) soft_deleted 사용자 hard delete

    Returns:
        {"refresh_index_cleaned": int, "orphan_2fa": int, "soft_deleted_users_purged": int}
    """
    try:
        return asyncio.run(_cleanup_expired_tokens_async(self))
    except Exception as exc:
        logger.exception("Token cleanup failed")
        raise self.retry(exc=exc)


async def _cleanup_expired_tokens_async(task) -> dict:
    """cleanup_expired_tokens async 구현."""
    from sqlalchemy import select
    from app.models.user import User

    ctx = await TaskContext.get()
    cleaned = 0

    # 1. soft_deleted 30일 경과 사용자의 refresh token 인덱스 삭제
    async with ctx.create_session() as session:
        cutoff = datetime.now(UTC) - timedelta(days=30)
        stmt = select(User.id).where(
            User.soft_deleted_at.isnot(None),
            User.soft_deleted_at < cutoff,
        )
        result = await session.execute(stmt)
        deleted_user_ids = [str(row[0]) for row in result.all()]

    for uid in deleted_user_ids:
        idx_key = f"auth:refresh_index:{uid}"
        client_ids = await ctx.redis.smembers(idx_key)
        if client_ids:
            keys_to_delete = [f"auth:refresh:{uid}:{cid}" for cid in client_ids]
            keys_to_delete.append(idx_key)
            await ctx.redis.delete(*keys_to_delete)
            cleaned += len(keys_to_delete)

    # 2. 고아 2FA pending 키 스캔 (TTL 없는 키 삭제)
    orphan_count = 0
    async for key in ctx.redis.scan_iter("auth:2fa_pending:*", count=100):
        ttl = await ctx.redis.ttl(key)
        if ttl == -1:
            await ctx.redis.delete(key)
            orphan_count += 1

    logger.info(
        "Token cleanup: cleaned %d refresh keys, %d orphan 2FA keys, %d soft-deleted users",
        cleaned, orphan_count, len(deleted_user_ids),
    )
    return {
        "refresh_index_cleaned": cleaned,
        "orphan_2fa": orphan_count,
        "soft_deleted_users_purged": len(deleted_user_ids),
    }
```

---

## 4. Settings 확장

`app/core/config.py`에 Celery 관련 설정 추가:

```python
# Celery
CELERY_BROKER_URL: str = ""              # 비어있으면 REDIS_URL 기반 DB 1
CELERY_RESULT_BACKEND: str = ""          # 비어있으면 REDIS_URL 기반 DB 2
CELERY_WORKER_CONCURRENCY: int = 4      # Worker 동시성

# Feature Switches
AI_TRADING_ENABLED: bool = True          # AI 매매 시스템 마스터 스위치
NEWS_SCRAPER_ENABLED: bool = True        # 뉴스 스크랩 마스터 스위치

@property
def celery_broker_url(self) -> str:
    """Celery broker URL (Redis DB 1)."""
    if self.CELERY_BROKER_URL:
        return self.CELERY_BROKER_URL
    # REDIS_URL에서 DB 번호를 1로 교체
    base = self.REDIS_URL.rstrip("/").rsplit("/", 1)[0]
    return f"{base}/1"

@property
def celery_result_backend(self) -> str:
    """Celery result backend URL (Redis DB 2)."""
    if self.CELERY_RESULT_BACKEND:
        return self.CELERY_RESULT_BACKEND
    base = self.REDIS_URL.rstrip("/").rsplit("/", 1)[0]
    return f"{base}/2"
```

---

## 5. Redis 키/TTL 추가

`app/core/redis_keys.py`에 Celery 관련 키 추가:

```python
class RedisTTL:
    # Celery
    AI_CYCLE_LOCK = 280         # 4분 40초 (5분 주기 - 20초 여유)
    AI_SINGLE_LOCK = 270        # 4분 30초 (개별 config 중복 방지)


class RedisKey:
    # ── Celery ──────────────────────────────────────────────────────────────

    @staticmethod
    def celery_lock(task_name: str) -> str:
        """Celery 태스크 중복 실행 방지 Lock."""
        return f"celery:lock:{task_name}"

    @staticmethod
    def ai_config_lock(config_id: str) -> str:
        """개별 AI config 중복 실행 방지 Lock."""
        return f"celery:lock:ai_trading:{config_id}"

    @staticmethod
    def ai_kill_switch() -> str:
        """AI 매매 글로벌 긴급 중지 키 (값 있으면 전체 중지)."""
        return "system:ai_trading:kill"
```

---

## 6. 에러 처리 전략

### 6.1 태스크별 에러 처리

| 태스크 | 재시도 | 전략 |
|--------|--------|------|
| `run_all_active_configs` | 0회 | Beat 주기 5분 → 다음 주기에 자연 재실행 |
| `run_single_config` | 3회 | 거래소 네트워크 오류만 재시도 (지수 백오프: 60→120→240초) |
| `scrape_news` | 2회 | 1분 간격 재시도 (네트워크 오류 대비) |
| `generate_daily_pnl_reports` | 2회 | 5분 간격 재시도 (DB 부하 대비) |
| `cleanup_expired_tokens` | 1회 | 5분 간격 재시도 |

### 6.2 에러 처리 패턴

```python
# run_single_config 에러 분류
try:
    return asyncio.run(_run_single_config_async(self, config_id))
except (ExchangeNetworkError, ExchangeUnavailableError) as exc:
    # 재시도 가능 (거래소 일시 장애)
    raise self.retry(exc=exc, countdown=2 ** self.request.retries * 60)
except SoftTimeLimitExceeded:
    # 타임아웃 → 결과 반환 (재시도 안 함)
    return {"status": "timeout", ...}
except Exception as exc:
    # 비복구 오류 → Sentry 자동 보고, 결과 반환
    return {"status": "failed", ...}
```

### 6.3 DLQ 전략

**DLQ 대신 Sentry 의존**: Celery DLQ는 설정 복잡도 높고 모니터링 어려움.
- `CeleryIntegration`이 모든 실패를 자동 Sentry 보고
- `task_acks_late=True`로 크래시 시 자동 재큐잉
- Beat 태스크는 재시도 없이 다음 주기에 자연 재실행

### 6.4 GPT 폴백

AI 매매 태스크에서 GPT 호출 실패 시:
- `RegimeService.detect()`는 내부적으로 GPT 실패 시 규칙 기반 결과만 반환 (v1-16 설계)
- GPT 실패가 전체 파이프라인을 차단하지 않음 (non-blocking)

---

## 7. Flow 제어 — 마스터 스위치

### 7.1 3계층 제어

| 계층 | 메커니즘 | 체크 위치 | 동작 |
|------|---------|-----------|------|
| 시스템 | `settings.AI_TRADING_ENABLED` | `run_all_active_configs` 시작 | 전체 AI 매매 비활성화 |
| 긴급 | Redis `system:ai_trading:kill` | `run_all_active_configs` 시작 | 런타임 긴급 중지 |
| 사용자 | `users.ai_trading_enabled` | SQL JOIN WHERE | 해당 사용자 config 제외 |
| 코인 | `ai_trading_configs.is_enabled` | SQL WHERE | 해당 코인 제외 |
| 거래소 | `exchange_account.is_active/is_verified` | SQL JOIN WHERE | 미인증/비활성 계정 제외 |

### 7.2 긴급 중지 API (향후 Admin 엔드포인트)

```python
# Redis SET으로 즉시 활성화
await redis.set("system:ai_trading:kill", "emergency_stop")
# 해제
await redis.delete("system:ai_trading:kill")
```

---

## 8. 중복 실행 방지

### 8.1 2단계 Redis Lock

| Lock | 키 패턴 | TTL | 대상 |
|------|---------|-----|------|
| Cycle Lock | `celery:lock:ai_trading_cycle` | 280초 | `run_all_active_configs` 전체 |
| Config Lock | `celery:lock:ai_trading:{config_id}` | 270초 | `run_single_config` 개별 |

```
Beat(5분) → run_all_active_configs()
  SET celery:lock:ai_trading_cycle NX EX 280
  → 미획득: 즉시 리턴 (이전 사이클 진행 중)
  → 획득: configs 순회 → 각 config에 delay()
  → finally: DEL lock

run_single_config(config_id)
  SET celery:lock:ai_trading:{config_id} NX EX 270
  → 미획득: 스킵 (동일 config 이미 실행 중)
  → 획득: 5단계 파이프라인 실행
  → finally: DEL lock
```

### 8.2 Lock 안전성

- TTL 만료 시 자동 해제 (데드락 방지)
- `finally` 블록에서 명시적 DEL (정상 종료 시 즉시 해제)
- Worker 크래시 시 TTL 대기 후 자동 해제

---

## 9. Docker Compose 확장

```yaml
# docker-compose.yml 추가
celery-worker:
  build:
    context: ./server
  command: >
    celery -A tasks.celery_app.celery_app worker
    -l info
    -c 4
    -Q ai,scraper,default
  depends_on:
    - redis
    - postgres
    - mongodb
  env_file:
    - .env
  volumes:
    - ./server:/app
  restart: unless-stopped

celery-beat:
  build:
    context: ./server
  command: >
    celery -A tasks.celery_app.celery_app beat
    -l info
    --scheduler celery.beat.PersistentScheduler
  depends_on:
    - redis
  env_file:
    - .env
  volumes:
    - ./server:/app
  restart: unless-stopped
```

---

## 10. 모니터링

### 10.1 Sentry + CeleryIntegration

```python
# context.py의 TaskContext.initialize()에서 자동 설정
sentry_sdk.init(
    dsn=settings.SENTRY_DSN,
    integrations=[CeleryIntegration()],
    ...
)
```

- 태스크별 트랜잭션 자동 추적
- 실패/재시도/타임아웃 자동 보고
- 성능 메트릭 (duration, queue time)

### 10.2 헬스체크 확장

기존 `/api/v1/health`에 Celery worker 상태 확인 추가:

```python
async def check_celery() -> dict:
    """Celery worker 활성 상태 확인."""
    try:
        result = await asyncio.to_thread(celery_app.control.ping, timeout=2)
        return {"celery": "ok", "workers": len(result)}
    except Exception:
        return {"celery": "error", "workers": 0}
```

### 10.3 Prometheus (향후)

- `celery-exporter` 별도 서비스 또는 커스텀 `task_success`/`task_failure` 시그널 사용
- `worker_send_task_events=True`로 이벤트 수집 가능

---

## 11. 테스트 전략

### 11.1 단위 테스트 (~30건)

| 테스트 | 파일 | 내용 |
|--------|------|------|
| Celery 앱 설정 | test_celery_app.py | 큐 라우팅, Beat 스케줄, 설정값 검증 |
| TaskContext | test_context.py | 싱글턴 초기화, 세션 생성, 리소스 관리 |
| AI Cycle Lock | test_ai_trading.py | Redis lock 획득/해제, 중복 실행 방지 |
| AI Config Lock | test_ai_trading.py | 개별 config lock 획득/해제 |
| AI 파이프라인 | test_ai_trading.py | config 로드 → 5단계 흐름 mock 검증 |
| 마스터 스위치 | test_ai_trading.py | settings/Redis kill switch 체크 |
| 뉴스 스크랩 | test_news_scraper.py | 스텁 동작, feature flag 체크 |
| PnL 리포트 | test_reports.py | 집계 로직, upsert 멱등성 |
| 토큰 정리 | test_cleanup.py | soft_deleted 사용자 키 삭제, 고아 키 |
| Backtest 스텁 | test_ai_trading.py | not_implemented 반환 확인 |

### 11.2 통합 테스트 (~8건)

| 테스트 | 내용 |
|--------|------|
| AI 사이클 E2E | dispatch → single config 완료 (mock provider) |
| PnL 리포트 생성 | 실제 DB 데이터 → DailyPnlReport 생성/검증 |
| 토큰 정리 | Redis 키 생성 → cleanup → 삭제 확인 |
| 중복 실행 (cycle) | 동시 2회 호출 → 1회만 실행 확인 |
| 중복 실행 (config) | 동일 config_id 동시 호출 → 1회만 실행 |
| 마스터 스위치 OFF | settings 비활성화 → 즉시 리턴 확인 |
| Kill Switch | Redis 키 설정 → 즉시 리턴 확인 |
| Backtest 호출 | 스텁 호출 → not_implemented 반환 |

### 11.3 테스트 파일 구조

```
server/tests/
├── unit/
│   └── tasks/
│       ├── test_celery_app.py
│       ├── test_context.py
│       ├── test_ai_trading.py
│       ├── test_news_scraper.py
│       ├── test_reports.py
│       └── test_cleanup.py
└── integration/
    └── tasks/
        ├── test_ai_cycle_e2e.py
        ├── test_pnl_report_e2e.py
        └── test_cleanup_e2e.py
```

### 11.4 테스트 설정

```python
# conftest.py
@pytest.fixture
def celery_config():
    return {"task_always_eager": True, "task_eager_propagates": True}
```

---

## 12. 구현 서브태스크 매핑

| ST | 서브태스크 | 주요 파일 | 의존 |
|----|-----------|----------|------|
| ST1 | Celery 앱 초기화 + TaskContext | `celery_app.py`, `context.py`, `__init__.py` | 없음 |
| ST2 | Beat 스케줄 + Settings 확장 | `celery_app.py`, `config.py`, `redis_keys.py` | ST1 |
| ST3 | AI 매매 태스크 (run_all + run_single + backtest 스텁) | `ai_trading.py` | ST1 |
| ST4 | 뉴스 스크랩 태스크 (스텁) | `news_scraper.py` | ST1 |
| ST5 | PnL 리포트 + 토큰 정리 | `reports.py`, `cleanup.py` | ST1 |
| ST6 | Docker Compose + 모니터링 + 테스트 | docker-compose, health, tests | ST1~5 |

---

## 13. ADR (기술 결정 기록)

### ADR-19-1: Celery Worker에서 async 코드 실행 방식

**상태**: 승인됨
**맥락**: Celery worker는 sync 환경(prefork pool). 기존 서비스/리포지토리는 모두 async.
**선택지**:
1. `asyncio.run()` per-task — 태스크마다 새 루프, 깔끔한 격리
2. Worker child별 단일 이벤트 루프 유지 — 연결 풀 재사용 가능하지만 루프 상태 관리 복잡
3. `asgiref.sync_to_async` — Django 전용, 불필요한 의존성

**결정**: 선택지 1. `asyncio.run()` per-task + `TaskContext` 프로세스 싱글턴으로 연결 풀 재사용.
**영향**: prefork pool 고수 필수 (gevent/eventlet에서 asyncio.run() 충돌). TaskContext 싱글턴이 연결 풀 재사용 보장.

### ADR-19-2: tasks/ 디렉토리 위치

**상태**: 승인됨
**맥락**: `server/app/tasks/` vs `server/tasks/`
**결정**: `server/tasks/` (PRD 구조 준수). Celery worker는 FastAPI와 별개 프로세스라는 의미 명확화.
**영향**: sys.path에 `server/` 포함 필요. Docker에서 WORKDIR=/app으로 해결.

### ADR-19-3: DLQ 전략

**상태**: 승인됨
**맥락**: 실패 태스크 처리 방식
**결정**: Sentry CeleryIntegration + task_acks_late. 별도 DLQ 인프라 불필요.
**영향**: 모든 실패 자동 Sentry 보고. Beat 태스크는 다음 주기 재실행.

### ADR-19-4: 중복 실행 방지

**상태**: 승인됨
**맥락**: Beat 5분 주기 + 이전 사이클 미완료 가능
**결정**: 2단계 Redis SET NX Lock (cycle: 280초, config: 270초).
**영향**: 이전 사이클/동일 config 미완료 시 자동 스킵. TTL 만료 시 자동 해제 (데드락 방지).

### ADR-19-5: Redis DB 분리

**상태**: 승인됨
**맥락**: 앱 캐시와 Celery broker/result 키 충돌 위험
**결정**: DB 0 = 앱 캐시/Pub/Sub, DB 1 = Celery Broker, DB 2 = Celery Result Backend
**영향**: Settings에 `celery_broker_url`/`celery_result_backend` property 추가. 기본값은 REDIS_URL 기반 자동 계산.

### ADR-19-6: 뉴스 스크랩 범위

**상태**: 승인됨
**맥락**: v1-19에서 뉴스 소스 크롤러까지 구현할지
**결정**: v1-19는 Celery 인프라 + 태스크 스캐폴딩만. 실제 크롤러는 별도(v2).
**영향**: `scrape_news()` 프레임 + feature flag만 구현. `NEWS_SCRAPER_ENABLED` 스위치 추가.

### ADR-19-7: TaskContext vs worker_process_init 시그널

**상태**: 승인됨
**맥락**: DB/Redis 초기화 시점
**선택지**:
1. `worker_process_init` 시그널 — 프로세스 시작 시 1회, 확실하지만 시그널 관리 복잡
2. `TaskContext` lazy 싱글턴 — 첫 태스크 진입 시 초기화, 코드 단순

**결정**: 선택지 2. TaskContext.get()에서 lazy 초기화. 파일명 `context.py` (deps.py는 FastAPI 관례).
**영향**: 시그널 코드 없음. 첫 태스크 진입 시 약간의 지연 (1회성). worker_max_tasks_per_child=100으로 자연 갱신.

### ADR-19-8: run_backtest 시그니처

**상태**: 승인됨
**맥락**: M9 백테스트 태스크 파라미터 설계
**결정**: `(config_id, start_date, end_date)` 직접 전달. `backtest_run_id` 방식은 BacktestRun 모델 생성(M9) 후 변경.
**영향**: M9까지 스텁. 실제 구현 시 시그니처 변경 가능.

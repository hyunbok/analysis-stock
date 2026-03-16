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
from app.core.redis_keys import RedisKey
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
    # 시스템 마스터 스위치 (Settings) — context 초기화 전 체크 (early return 최적화)
    if not settings.AI_TRADING_ENABLED:
        logger.info("AI trading disabled (settings)")
        return {"status": "skipped", "dispatched": 0, "skipped": 0, "reason": "master_switch_off"}

    ctx = await TaskContext.get()

    # Redis 긴급 킬 스위치
    kill = await ctx.redis.get(RedisKey.ai_kill_switch())
    if kill:
        logger.warning("AI trading globally disabled (kill switch)")
        return {"status": "skipped", "dispatched": 0, "skipped": 0, "reason": "kill_switch"}

    # 중복 실행 방지 (SET NX)
    lock_key = RedisKey.celery_lock("ai_trading_cycle")
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
    except Exception:
        logger.exception("Single config failed: %s", config_id)
        # Sentry 자동 캡처 (CeleryIntegration)
        return {"config_id": config_id, "status": "failed", "signal_action": None}


async def _run_single_config_async(task, config_id: str) -> dict:
    """run_single_config의 async 구현 — 5단계 파이프라인."""
    start_time = time.monotonic()
    ctx = await TaskContext.get()

    # 개별 config Redis Lock (동일 config 중복 실행 방지)
    lock_key = RedisKey.ai_config_lock(config_id)
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

        # TODO(v1-22): AI 매매 신호 알림 — PushService를 TaskContext에 주입 후 아래 코드 활성화
        # if exec_result["status"] not in ("skipped",) and push_service:
        #     try:
        #         await push_service.send_ai_trading_signal(
        #             user_id=UUID(user_id),
        #             signal_type=signal["action"].upper(),
        #             coin_symbol=symbol,
        #             reason=signal.get("reason", "AI 매매 신호 발생"),
        #         )
        #     except Exception:
        #         logger.warning("AI trading signal push failed: user=%s", user_id)

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


async def _fetch_candles(motor_db, exchange_type: str, market_code: str, timeframe: str, limit: int) -> list:
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

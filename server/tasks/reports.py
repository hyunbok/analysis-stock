"""일별 PnL 리포트 생성 태스크.

Beat(매일 00:05 UTC) → generate_daily_pnl_reports()
"""
import asyncio
import logging
from datetime import UTC, date, datetime, timedelta
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
    from sqlalchemy import select
    from app.documents.trading_logs import DailyPnlReport, TradeLog  # noqa: F401
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
    from sqlalchemy import func, case, select
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
        # float 경유 없이 직접 Decimal 변환 (금융 정밀도 보존)
        raw = stat["total_pnl"]
        pnl_dec = Decimal(str(raw)) if raw else Decimal("0")
        if stat["_id"] is True:
            ai_pnl = pnl_dec
            ai_win_count = stat.get("win_count", 0)
        else:
            manual_pnl = pnl_dec

    total_pnl = ai_pnl + manual_pnl
    win_count = sum(s.get("win_count", 0) for s in trade_log_stats)
    # Decimal 나눗셈으로 win_rate 계산 (float 정밀도 손실 방지)
    win_rate = Decimal(win_count) / Decimal(trade_count) if trade_count > 0 else Decimal("0")

    # 누적 PnL (이전 리포트에서 조회)
    prev_report = await DailyPnlReport.find_one(
        DailyPnlReport.user_id == user_id,
        DailyPnlReport.report_date < report_dt,
        sort=[("report_date", -1)],
    )
    # float 경유 없이 직접 Decimal 변환 (금융 정밀도 보존)
    prev_cumulative = Decimal(str(prev_report.cumulative_pnl)) if prev_report else Decimal("0")
    cumulative_pnl = prev_cumulative + total_pnl

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

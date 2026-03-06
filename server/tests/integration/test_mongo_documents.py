"""MongoDB Beanie 도큐먼트 통합 테스트.

mongomock-motor를 사용하여 실제 MongoDB 없이 실행 가능.
"""

import uuid
from datetime import UTC, date, datetime

import pytest
from bson import Decimal128

from app.documents.notifications import Notification
from app.documents.trading_logs import AiDecision, DailyPnlReport, TradeLog


# ── helpers ───────────────────────────────────────────────────────────────────

def make_trade_log(user_id: uuid.UUID | None = None) -> TradeLog:
    return TradeLog(
        user_id=user_id or uuid.uuid4(),
        trade_order_id=uuid.uuid4(),
        coin_symbol="BTC",
        market_code="KRW-BTC",
        exchange_type="upbit",
        order_type="buy",
        order_method="market",
        price=Decimal128("50000000"),
        quantity=Decimal128("0.001"),
        fee=Decimal128("50"),
        is_ai_order=False,
        entry_price=Decimal128("50000000"),
        status="open",
    )


def make_ai_decision(user_id: uuid.UUID | None = None) -> AiDecision:
    return AiDecision(
        user_id=user_id or uuid.uuid4(),
        coin_symbol="BTC",
        market_regime="trend",
        regime_confidence={"trend": 0.7, "range": 0.2, "transition": 0.1},
        selected_strategy="trend_following",
        action="buy",
        action_confidence=Decimal128("0.85"),
        gpt_model="gpt-4o-mini",
        gpt_prompt_tokens=500,
        gpt_completion_tokens=200,
    )


def make_daily_pnl(user_id: uuid.UUID | None = None, report_date: date | None = None) -> DailyPnlReport:
    return DailyPnlReport(
        user_id=user_id or uuid.uuid4(),
        report_date=report_date or date.today(),
        total_pnl=Decimal128("100000"),
        trade_count=5,
        win_rate=Decimal128("0.60"),
        ai_pnl=Decimal128("80000"),
        ai_trade_count=3,
        ai_win_count=2,
        manual_pnl=Decimal128("20000"),
        manual_trade_count=2,
        cumulative_pnl=Decimal128("500000"),
    )


# ── tests ─────────────────────────────────────────────────────────────────────

async def test_trade_log_crud(mongo_db):
    """TradeLog 생성/조회/업데이트."""
    user_id = uuid.uuid4()
    log = make_trade_log(user_id)
    await log.save()

    assert log.id is not None

    # 조회
    fetched = await TradeLog.get(log.id)
    assert fetched is not None
    assert str(fetched.user_id) == str(user_id)
    assert fetched.coin_symbol == "BTC"
    assert fetched.status == "open"

    # 업데이트
    fetched.status = "closed"
    fetched.pnl_amount = Decimal128("5000")
    await fetched.save()

    updated = await TradeLog.get(log.id)
    assert updated.status == "closed"
    assert updated.pnl_amount == Decimal128("5000")


async def test_ai_decision_crud(mongo_db):
    """AiDecision 생성/조회."""
    user_id = uuid.uuid4()
    decision = make_ai_decision(user_id)
    await decision.save()

    assert decision.id is not None

    fetched = await AiDecision.get(decision.id)
    assert fetched is not None
    assert str(fetched.user_id) == str(user_id)
    assert fetched.action == "buy"
    assert fetched.market_regime == "trend"
    assert fetched.regime_confidence["trend"] == pytest.approx(0.7)


async def test_daily_pnl_report_upsert(mongo_db):
    """DailyPnlReport upsert 멱등성 - 동일 (user_id, report_date)에 1개만 유지."""
    user_id = uuid.uuid4()
    report_date = date(2025, 1, 1)

    # 초기 생성
    report = make_daily_pnl(user_id, report_date)
    await report.save()

    # 동일 user_id + report_date 조회 후 업데이트 (upsert 패턴)
    existing = await DailyPnlReport.find_one(
        DailyPnlReport.user_id == user_id,
        DailyPnlReport.report_date == report_date,
    )
    assert existing is not None

    existing.total_pnl = Decimal128("200000")
    existing.trade_count = 10
    existing.updated_at = datetime.now(UTC)
    await existing.save()

    # 도큐먼트 수 = 1 (중복 생성 없음)
    count = await DailyPnlReport.find(
        DailyPnlReport.user_id == user_id,
        DailyPnlReport.report_date == report_date,
    ).count()
    assert count == 1

    # 값 검증
    final = await DailyPnlReport.get(report.id)
    assert final.total_pnl == Decimal128("200000")
    assert final.trade_count == 10


async def test_notification_crud(mongo_db):
    """Notification 생성/조회/읽음 처리."""
    user_id = uuid.uuid4()

    notif = Notification(
        user_id=user_id,
        type="price_alert",
        title="BTC 목표가 도달",
        body="비트코인이 설정한 목표가에 도달했습니다.",
        data={"coin": "BTC", "price": 50000000},
        is_read=False,
    )
    await notif.save()

    assert notif.id is not None

    fetched = await Notification.get(notif.id)
    assert fetched is not None
    assert str(fetched.user_id) == str(user_id)
    assert fetched.type == "price_alert"
    assert fetched.is_read is False
    assert fetched.data["coin"] == "BTC"

    # 읽음 처리
    fetched.is_read = True
    await fetched.save()

    updated = await Notification.get(notif.id)
    assert updated.is_read is True

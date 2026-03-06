VERSION = "001"
DESCRIPTION = "Initial collections and indexes"


async def upgrade(db):
    # trade_logs 인덱스
    await db.trade_logs.create_index([("user_id", 1), ("created_at", -1)])
    await db.trade_logs.create_index([("user_id", 1), ("status", 1), ("created_at", -1)])
    await db.trade_logs.create_index("trade_order_id")

    # ai_decisions TTL + 인덱스
    await db.ai_decisions.create_index(
        "created_at", expireAfterSeconds=15552000  # 180일
    )
    await db.ai_decisions.create_index([("user_id", 1), ("coin_symbol", 1), ("created_at", -1)])

    # daily_pnl_reports unique 인덱스
    await db.daily_pnl_reports.create_index(
        [("user_id", 1), ("report_date", 1)], unique=True
    )

    # notifications TTL + 인덱스
    await db.notifications.create_index(
        "created_at", expireAfterSeconds=7776000  # 90일
    )
    await db.notifications.create_index([("user_id", 1), ("is_read", 1), ("created_at", -1)])

    # audit_logs 인덱스
    await db.audit_logs.create_index([("user_id", 1), ("created_at", -1)])
    await db.audit_logs.create_index("action")

    # news_data 인덱스
    await db.news_data.create_index("url", unique=True)
    await db.news_data.create_index([("coin_symbols", 1), ("published_at", -1)])


async def downgrade(db):
    # 인덱스 삭제 (필요 시)
    pass

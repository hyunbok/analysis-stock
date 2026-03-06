"""Index optimization and CHECK constraints

Revision ID: b2c3d4e5f6a1
Revises: a1b2c3d4e5f6
Create Date: 2026-03-05 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "b2c3d4e5f6a1"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enable pg_trgm for GIN trigram indexes (symbol search)
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # -------------------------------------------------------------------------
    # coins: GIN trgm index for symbol fuzzy/prefix search
    # -------------------------------------------------------------------------
    op.execute(
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_coins_symbol_trgm "
        "ON coins USING gin (symbol gin_trgm_ops)"
    )

    # -------------------------------------------------------------------------
    # watchlist_coins: Covering index (user_id) INCLUDE (coin_id, sort_order)
    # -------------------------------------------------------------------------
    op.execute(
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_watchlist_coins_user_id_covering "
        "ON watchlist_coins (user_id) INCLUDE (coin_id, sort_order)"
    )

    # -------------------------------------------------------------------------
    # ai_trading_configs: Partial index (is_enabled=true) + GIN on strategy_params
    # -------------------------------------------------------------------------
    op.execute(
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_ai_trading_configs_is_enabled_partial "
        "ON ai_trading_configs (watchlist_coin_id) WHERE is_enabled = true"
    )
    op.execute(
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_ai_trading_configs_strategy_params_gin "
        "ON ai_trading_configs USING gin (strategy_params)"
    )

    # CHECK constraints: ai_trading_configs ratio fields (0.0 ~ 1.0)
    op.create_check_constraint(
        "ck_ai_config_max_investment_ratio",
        "ai_trading_configs",
        "max_investment_ratio >= 0.0 AND max_investment_ratio <= 1.0",
    )
    op.create_check_constraint(
        "ck_ai_config_stop_loss_ratio",
        "ai_trading_configs",
        "stop_loss_ratio >= 0.0 AND stop_loss_ratio <= 1.0",
    )
    op.create_check_constraint(
        "ck_ai_config_take_profit_ratio",
        "ai_trading_configs",
        "take_profit_ratio >= 0.0 AND take_profit_ratio <= 1.0",
    )
    op.create_check_constraint(
        "ck_ai_config_daily_max_loss_ratio",
        "ai_trading_configs",
        "daily_max_loss_ratio >= 0.0 AND daily_max_loss_ratio <= 1.0",
    )

    # -------------------------------------------------------------------------
    # trade_orders: composite indexes + partial index + CHECK constraints
    # -------------------------------------------------------------------------
    op.execute(
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_trade_orders_user_status_created "
        "ON trade_orders (user_id, status, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_trade_orders_user_ai_created "
        "ON trade_orders (user_id, is_ai_order, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_trade_orders_pending "
        "ON trade_orders (user_id, created_at DESC) WHERE status = 'pending'"
    )

    op.create_check_constraint(
        "ck_trade_orders_status",
        "trade_orders",
        "status IN ('pending', 'filled', 'cancelled', 'partial')",
    )
    op.create_check_constraint(
        "ck_trade_orders_order_type",
        "trade_orders",
        "order_type IN ('buy', 'sell')",
    )
    op.create_check_constraint(
        "ck_trade_orders_order_method",
        "trade_orders",
        "order_method IN ('market', 'limit')",
    )

    # -------------------------------------------------------------------------
    # price_alerts: partial index (active + untriggered) + CHECK constraint
    # -------------------------------------------------------------------------
    op.execute(
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_price_alerts_active_untriggered "
        "ON price_alerts (user_id, coin_id) WHERE is_active = true AND is_triggered = false"
    )
    op.create_check_constraint(
        "ck_price_alerts_condition",
        "price_alerts",
        "condition IN ('above', 'below')",
    )


def downgrade() -> None:
    # CHECK constraints
    op.drop_constraint("ck_price_alerts_condition", "price_alerts")
    op.drop_constraint("ck_trade_orders_order_method", "trade_orders")
    op.drop_constraint("ck_trade_orders_order_type", "trade_orders")
    op.drop_constraint("ck_trade_orders_status", "trade_orders")
    op.drop_constraint("ck_ai_config_daily_max_loss_ratio", "ai_trading_configs")
    op.drop_constraint("ck_ai_config_take_profit_ratio", "ai_trading_configs")
    op.drop_constraint("ck_ai_config_stop_loss_ratio", "ai_trading_configs")
    op.drop_constraint("ck_ai_config_max_investment_ratio", "ai_trading_configs")

    # Indexes
    op.drop_index("ix_price_alerts_active_untriggered", table_name="price_alerts")
    op.drop_index("ix_trade_orders_pending", table_name="trade_orders")
    op.drop_index("ix_trade_orders_user_ai_created", table_name="trade_orders")
    op.drop_index("ix_trade_orders_user_status_created", table_name="trade_orders")
    op.drop_index("ix_ai_trading_configs_strategy_params_gin", table_name="ai_trading_configs")
    op.drop_index("ix_ai_trading_configs_is_enabled_partial", table_name="ai_trading_configs")
    op.drop_index("ix_watchlist_coins_user_id_covering", table_name="watchlist_coins")
    op.drop_index("ix_coins_symbol_trgm", table_name="coins")

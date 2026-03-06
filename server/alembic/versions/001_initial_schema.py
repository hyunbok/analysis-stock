"""Initial schema

Revision ID: a1b2c3d4e5f6
Revises:
Create Date: 2026-03-05 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enable pgcrypto for gen_random_uuid() on PostgreSQL < 13
    # (no-op on PG 13+ where it's built-in, safe to run regardless)
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto"')

    # 1. users
    op.create_table(
        "users",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=True),
        sa.Column("nickname", sa.String(50), nullable=True),
        sa.Column("avatar_url", sa.String(500), nullable=True),
        sa.Column("language", sa.String(5), server_default="ko", nullable=False),
        sa.Column("theme", sa.String(10), server_default="system", nullable=False),
        sa.Column(
            "price_color_style", sa.String(10), server_default="korean", nullable=False
        ),
        sa.Column(
            "ai_trading_enabled",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("totp_secret_encrypted", sa.LargeBinary(), nullable=True),
        sa.Column(
            "is_2fa_enabled",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_index("ix_users_created_at", "users", ["created_at"])

    # 2. user_social_accounts
    op.create_table(
        "user_social_accounts",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("provider", sa.String(20), nullable=False),
        sa.Column("provider_id", sa.String(255), nullable=False),
        sa.Column("provider_email", sa.String(255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "provider_id", name="uq_social_provider_id"),
    )

    # 3. clients
    op.create_table(
        "clients",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("device_type", sa.String(20), nullable=False),
        sa.Column("fcm_token", sa.String(500), nullable=True),
        sa.Column("last_active_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_clients_user_id", "clients", ["user_id"])
    op.create_index("ix_clients_fcm_token", "clients", ["fcm_token"])

    # 4. user_consents
    op.create_table(
        "user_consents",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("consent_type", sa.String(20), nullable=False),
        sa.Column("agreed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.String(10), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "consent_type",
            "version",
            name="uq_consent_user_type_version",
        ),
    )

    # 5. user_exchange_accounts
    op.create_table(
        "user_exchange_accounts",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("exchange_type", sa.String(20), nullable=False),
        sa.Column("api_key_encrypted", sa.LargeBinary(), nullable=False),
        sa.Column("api_secret_encrypted", sa.LargeBinary(), nullable=False),
        sa.Column("permissions", postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "exchange_type", name="uq_exchange_account_user_type"
        ),
    )
    op.create_index(
        "ix_user_exchange_accounts_user_id", "user_exchange_accounts", ["user_id"]
    )

    # 6. coins
    op.create_table(
        "coins",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("name_ko", sa.String(100), nullable=True),
        sa.Column("name_en", sa.String(100), nullable=True),
        sa.Column("exchange_type", sa.String(20), nullable=False),
        sa.Column("market_code", sa.String(30), nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "exchange_type", "market_code", name="uq_coin_exchange_market"
        ),
    )
    op.create_index("ix_coins_symbol", "coins", ["symbol"])
    op.create_index("ix_coins_exchange_type", "coins", ["exchange_type"])

    # 7. watchlist_coins
    op.create_table(
        "watchlist_coins",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("coin_id", sa.UUID(), nullable=False),
        sa.Column("exchange_account_id", sa.UUID(), nullable=True),
        sa.Column(
            "sort_order", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["coin_id"], ["coins.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["exchange_account_id"],
            ["user_exchange_accounts.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "coin_id",
            "exchange_account_id",
            name="uq_watchlist_user_coin_account",
        ),
    )
    op.create_index(
        "ix_watchlist_coins_user_id_sort_order",
        "watchlist_coins",
        ["user_id", "sort_order"],
    )

    # 8. ai_trading_configs
    op.create_table(
        "ai_trading_configs",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("watchlist_coin_id", sa.UUID(), nullable=False),
        sa.Column(
            "is_enabled",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "max_investment_ratio",
            sa.Numeric(5, 4),
            server_default=sa.text("0.10"),
            nullable=False,
        ),
        sa.Column(
            "stop_loss_ratio",
            sa.Numeric(5, 4),
            server_default=sa.text("0.02"),
            nullable=False,
        ),
        sa.Column(
            "take_profit_ratio",
            sa.Numeric(5, 4),
            server_default=sa.text("0.03"),
            nullable=False,
        ),
        sa.Column(
            "daily_max_loss_ratio",
            sa.Numeric(5, 4),
            server_default=sa.text("0.05"),
            nullable=False,
        ),
        sa.Column(
            "primary_timeframe", sa.String(10), server_default="5m", nullable=False
        ),
        sa.Column(
            "confirmation_timeframes",
            postgresql.ARRAY(sa.String()),
            server_default=sa.text("ARRAY['15m','1h']"),
            nullable=False,
        ),
        sa.Column(
            "strategy_params",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("enabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("disable_reason", sa.String(200), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["watchlist_coin_id"], ["watchlist_coins.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "watchlist_coin_id", name="uq_ai_trading_configs_watchlist_coin_id"
        ),
    )
    op.create_index(
        "ix_ai_trading_configs_watchlist_coin_id",
        "ai_trading_configs",
        ["watchlist_coin_id"],
        unique=True,
    )
    op.create_index(
        "ix_ai_trading_configs_is_enabled", "ai_trading_configs", ["is_enabled"]
    )

    # 9. ai_trading_config_histories
    op.create_table(
        "ai_trading_config_histories",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("config_id", sa.UUID(), nullable=False),
        sa.Column("action", sa.String(30), nullable=False),
        sa.Column("changed_by", sa.String(10), nullable=False),
        sa.Column(
            "change_detail",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["config_id"], ["ai_trading_configs.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ai_trading_config_histories_config_id",
        "ai_trading_config_histories",
        ["config_id"],
    )
    op.create_index(
        "ix_ai_trading_config_histories_created_at",
        "ai_trading_config_histories",
        ["created_at"],
    )

    # 10. trade_orders
    op.create_table(
        "trade_orders",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("exchange_account_id", sa.UUID(), nullable=False),
        sa.Column("coin_id", sa.UUID(), nullable=False),
        sa.Column("order_type", sa.String(10), nullable=False),
        sa.Column("order_method", sa.String(10), nullable=False),
        sa.Column("price", sa.Numeric(20, 8), nullable=True),
        sa.Column("quantity", sa.Numeric(20, 8), nullable=False),
        sa.Column(
            "executed_quantity",
            sa.Numeric(20, 8),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "fee",
            sa.Numeric(20, 8),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column(
            "is_ai_order",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("exchange_order_id", sa.String(100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["exchange_account_id"],
            ["user_exchange_accounts.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["coin_id"], ["coins.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_trade_orders_user_id", "trade_orders", ["user_id"])
    op.create_index("ix_trade_orders_status", "trade_orders", ["status"])
    op.create_index("ix_trade_orders_created_at", "trade_orders", ["created_at"])
    op.create_index("ix_trade_orders_is_ai_order", "trade_orders", ["is_ai_order"])

    # 11. price_alerts
    op.create_table(
        "price_alerts",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("coin_id", sa.UUID(), nullable=False),
        sa.Column("exchange_account_id", sa.UUID(), nullable=True),
        sa.Column("condition", sa.String(10), nullable=False),
        sa.Column("target_price", sa.Numeric(20, 8), nullable=False),
        sa.Column(
            "is_triggered",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column("triggered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["coin_id"], ["coins.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["exchange_account_id"],
            ["user_exchange_accounts.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_price_alerts_user_id", "price_alerts", ["user_id"])
    op.create_index("ix_price_alerts_is_active", "price_alerts", ["is_active"])
    op.create_index("ix_price_alerts_coin_id", "price_alerts", ["coin_id"])


def downgrade() -> None:
    # Drop in reverse dependency order (indexes dropped automatically with tables)
    op.drop_table("price_alerts")
    op.drop_table("trade_orders")
    op.drop_table("ai_trading_config_histories")
    op.drop_table("ai_trading_configs")
    op.drop_table("watchlist_coins")
    op.drop_table("coins")
    op.drop_table("user_exchange_accounts")
    op.drop_table("user_consents")
    op.drop_table("clients")
    op.drop_table("user_social_accounts")
    op.drop_table("users")

import uuid
from datetime import datetime

import sqlalchemy.dialects.postgresql as pg
from sqlalchemy import Boolean, DateTime, ForeignKey, Index, LargeBinary, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.core.database import Base


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        Index("ix_users_created_at", "created_at"),
        Index("ix_users_soft_deleted_at", "soft_deleted_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    nickname: Mapped[str | None] = mapped_column(String(50), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    language: Mapped[str] = mapped_column(String(5), default="ko", server_default="ko")
    theme: Mapped[str] = mapped_column(String(10), default="system", server_default="system")
    price_color_style: Mapped[str] = mapped_column(
        String(10), default="korean", server_default="korean"
    )
    ai_trading_enabled: Mapped[bool] = mapped_column(
        pg.BOOLEAN, default=False, server_default=text("false")
    )
    totp_secret_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    is_2fa_enabled: Mapped[bool] = mapped_column(
        pg.BOOLEAN, default=False, server_default=text("false")
    )
    email_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    soft_deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    social_accounts: Mapped[list["UserSocialAccount"]] = relationship(
        "UserSocialAccount", back_populates="user", cascade="all, delete-orphan"
    )
    clients: Mapped[list["Client"]] = relationship(
        "Client", back_populates="user", cascade="all, delete-orphan"
    )
    consents: Mapped[list["UserConsent"]] = relationship(
        "UserConsent", back_populates="user", cascade="all, delete-orphan"
    )
    exchange_accounts: Mapped[list["UserExchangeAccount"]] = relationship(
        "UserExchangeAccount", back_populates="user", cascade="all, delete-orphan"
    )
    watchlist_coins: Mapped[list["WatchlistCoin"]] = relationship(
        "WatchlistCoin", back_populates="user", cascade="all, delete-orphan"
    )
    trade_orders: Mapped[list["TradeOrder"]] = relationship(
        "TradeOrder", back_populates="user", cascade="all, delete-orphan"
    )
    price_alerts: Mapped[list["PriceAlert"]] = relationship(
        "PriceAlert", back_populates="user", cascade="all, delete-orphan"
    )
    totp_backup_codes: Mapped[list["UserTotpBackupCode"]] = relationship(
        "UserTotpBackupCode", back_populates="user", cascade="all, delete-orphan"
    )


class UserSocialAccount(Base):
    __tablename__ = "user_social_accounts"
    __table_args__ = (
        UniqueConstraint("provider", "provider_id", name="uq_social_provider_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    provider_id: Mapped[str] = mapped_column(String(255), nullable=False)
    provider_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped["User"] = relationship("User", back_populates="social_accounts")


class Client(Base):
    __tablename__ = "clients"
    __table_args__ = (
        Index("ix_clients_user_id", "user_id"),
        Index("ix_clients_fcm_token", "fcm_token"),
        Index("ix_clients_user_fingerprint", "user_id", "device_fingerprint"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    device_type: Mapped[str] = mapped_column(String(20), nullable=False)
    device_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    fcm_token: Mapped[str | None] = mapped_column(String(500), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    device_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true"), nullable=False
    )
    last_active_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped["User"] = relationship("User", back_populates="clients")


class UserTotpBackupCode(Base):
    """TOTP 비상 백업 코드 (1회 사용 후 무효화)"""

    __tablename__ = "user_totp_backup_codes"
    __table_args__ = (Index("ix_totp_backup_codes_user_id", "user_id"),)

    id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)  # SHA-256 hex
    is_used: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped["User"] = relationship("User", back_populates="totp_backup_codes")


class UserConsent(Base):
    __tablename__ = "user_consents"
    __table_args__ = (
        UniqueConstraint("user_id", "consent_type", "version", name="uq_consent_user_type_version"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    consent_type: Mapped[str] = mapped_column(String(20), nullable=False)
    agreed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    version: Mapped[str] = mapped_column(String(10), nullable=False)

    user: Mapped["User"] = relationship("User", back_populates="consents")

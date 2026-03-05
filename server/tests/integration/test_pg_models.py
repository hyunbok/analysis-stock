"""PostgreSQL 모델 통합 테스트.

실제 PG 연결 필요 (conftest.py의 pg_engine fixture 사용).
테스트마다 트랜잭션 롤백으로 격리.
"""

import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.models.coin import Coin, WatchlistCoin
from app.models.exchange import UserExchangeAccount
from app.models.trading import TradeOrder
from app.models.user import Client, User


# ── helpers ───────────────────────────────────────────────────────────────────

def make_user(**kwargs) -> User:
    defaults = dict(
        id=uuid.uuid4(),
        email=f"test_{uuid.uuid4().hex[:8]}@example.com",
        password_hash="hashed",
    )
    return User(**{**defaults, **kwargs})


def make_coin(exchange_type: str = "upbit", symbol: str = "BTC") -> Coin:
    return Coin(
        id=uuid.uuid4(),
        symbol=symbol,
        name_ko="비트코인",
        name_en="Bitcoin",
        exchange_type=exchange_type,
        market_code=f"KRW-{symbol}",
    )


def make_exchange_account(user_id: uuid.UUID, exchange_type: str = "upbit") -> UserExchangeAccount:
    return UserExchangeAccount(
        id=uuid.uuid4(),
        user_id=user_id,
        exchange_type=exchange_type,
        api_key_encrypted=b"encrypted_key",
        api_secret_encrypted=b"encrypted_secret",
    )


# ── tests ─────────────────────────────────────────────────────────────────────

async def test_create_user(db_session):
    """User 생성 후 조회."""
    user = make_user(nickname="testuser")
    db_session.add(user)
    await db_session.flush()

    result = await db_session.execute(select(User).where(User.id == user.id))
    fetched = result.scalar_one()

    assert fetched.email == user.email
    assert fetched.nickname == "testuser"
    assert fetched.language == "ko"


async def test_user_unique_email(db_session):
    """중복 email 삽입 시 IntegrityError."""
    email = f"unique_{uuid.uuid4().hex[:8]}@example.com"
    db_session.add(make_user(email=email))
    await db_session.flush()

    db_session.add(make_user(email=email))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_user_cascade_delete(db_session):
    """User 삭제 시 Client CASCADE 삭제 검증."""
    user = make_user()
    db_session.add(user)
    await db_session.flush()

    client = Client(
        id=uuid.uuid4(),
        user_id=user.id,
        device_type="android",
    )
    db_session.add(client)
    await db_session.flush()

    # 삭제 전 Client 존재 확인
    result = await db_session.execute(select(Client).where(Client.id == client.id))
    assert result.scalar_one_or_none() is not None

    await db_session.delete(user)
    await db_session.flush()

    # CASCADE: Client도 삭제되어야 함
    result = await db_session.execute(select(Client).where(Client.id == client.id))
    assert result.scalar_one_or_none() is None


async def test_create_coin(db_session):
    """Coin 생성 및 UNIQUE(exchange_type, market_code) 제약 검증."""
    coin = make_coin()
    db_session.add(coin)
    await db_session.flush()

    result = await db_session.execute(select(Coin).where(Coin.id == coin.id))
    fetched = result.scalar_one()
    assert fetched.symbol == "BTC"
    assert fetched.exchange_type == "upbit"

    # 동일 (exchange_type, market_code) 중복 삽입
    duplicate = make_coin(exchange_type="upbit", symbol="BTC")
    db_session.add(duplicate)
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_create_trade_order(db_session):
    """TradeOrder 생성 및 status CHECK 제약 검증."""
    user = make_user()
    coin = make_coin(symbol=f"T{uuid.uuid4().hex[:4].upper()}")
    exchange_account = make_exchange_account(user.id)
    db_session.add_all([user, coin, exchange_account])
    await db_session.flush()

    order = TradeOrder(
        id=uuid.uuid4(),
        user_id=user.id,
        exchange_account_id=exchange_account.id,
        coin_id=coin.id,
        order_type="buy",
        order_method="market",
        quantity=0.001,
        status="pending",
    )
    db_session.add(order)
    await db_session.flush()

    result = await db_session.execute(select(TradeOrder).where(TradeOrder.id == order.id))
    fetched = result.scalar_one()
    assert fetched.status == "pending"
    assert fetched.order_type == "buy"

    # CHECK 제약: 잘못된 status
    bad_order = TradeOrder(
        id=uuid.uuid4(),
        user_id=user.id,
        exchange_account_id=exchange_account.id,
        coin_id=coin.id,
        order_type="buy",
        order_method="market",
        quantity=0.001,
        status="invalid_status",
    )
    db_session.add(bad_order)
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_watchlist_coin_relations(db_session):
    """WatchlistCoin → User/Coin 관계 검증."""
    user = make_user()
    coin = make_coin(symbol=f"W{uuid.uuid4().hex[:4].upper()}")
    db_session.add_all([user, coin])
    await db_session.flush()

    wl = WatchlistCoin(
        id=uuid.uuid4(),
        user_id=user.id,
        coin_id=coin.id,
        sort_order=1,
    )
    db_session.add(wl)
    await db_session.flush()

    result = await db_session.execute(
        select(WatchlistCoin).where(WatchlistCoin.id == wl.id)
    )
    fetched = result.scalar_one()
    assert fetched.user_id == user.id
    assert fetched.coin_id == coin.id
    assert fetched.sort_order == 1

    # UNIQUE(user_id, coin_id, exchange_account_id) 중복 검증
    duplicate_wl = WatchlistCoin(
        id=uuid.uuid4(),
        user_id=user.id,
        coin_id=coin.id,
        sort_order=2,
    )
    db_session.add(duplicate_wl)
    with pytest.raises(IntegrityError):
        await db_session.flush()

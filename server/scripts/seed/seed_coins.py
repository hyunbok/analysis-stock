"""코인 초기 데이터 로드 스크립트.

Upbit / CoinOne 공개 API에서 코인 목록을 조회하여 DB에 upsert 한다.
API 호출 실패 시 정적 fallback(15개 주요 코인)으로 대체한다.

실행:
    cd server && python -m scripts.seed.seed_coins
    python -m scripts.seed.seed_coins --exchange upbit
    python -m scripts.seed.seed_coins --exchange coinone
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from dataclasses import dataclass
from typing import Any

import httpx
from sqlalchemy import func, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

# ─── 경로 설정: server/ 디렉토리에서 실행 ──────────────────────────────────────
sys.path.insert(0, ".")

from app.core.config import settings  # noqa: E402
from app.models.coin import Coin  # noqa: E402

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

# ─── 정적 Fallback ─────────────────────────────────────────────────────────────

FALLBACK_COINS: list[dict[str, str | None]] = [
    {"symbol": "BTC",  "name_ko": "비트코인",    "name_en": "Bitcoin",       "exchange_type": "upbit",   "market_code": "KRW-BTC"},
    {"symbol": "ETH",  "name_ko": "이더리움",    "name_en": "Ethereum",      "exchange_type": "upbit",   "market_code": "KRW-ETH"},
    {"symbol": "XRP",  "name_ko": "리플",        "name_en": "XRP",           "exchange_type": "upbit",   "market_code": "KRW-XRP"},
    {"symbol": "SOL",  "name_ko": "솔라나",      "name_en": "Solana",        "exchange_type": "upbit",   "market_code": "KRW-SOL"},
    {"symbol": "DOGE", "name_ko": "도지코인",    "name_en": "Dogecoin",      "exchange_type": "upbit",   "market_code": "KRW-DOGE"},
    {"symbol": "ADA",  "name_ko": "에이다",      "name_en": "Cardano",       "exchange_type": "upbit",   "market_code": "KRW-ADA"},
    {"symbol": "AVAX", "name_ko": "아발란체",    "name_en": "Avalanche",     "exchange_type": "upbit",   "market_code": "KRW-AVAX"},
    {"symbol": "DOT",  "name_ko": "폴카닷",      "name_en": "Polkadot",      "exchange_type": "upbit",   "market_code": "KRW-DOT"},
    {"symbol": "MATIC","name_ko": "폴리곤",      "name_en": "Polygon",       "exchange_type": "upbit",   "market_code": "KRW-MATIC"},
    {"symbol": "LINK", "name_ko": "체인링크",    "name_en": "Chainlink",     "exchange_type": "upbit",   "market_code": "KRW-LINK"},
    {"symbol": "ATOM", "name_ko": "코스모스",    "name_en": "Cosmos",        "exchange_type": "upbit",   "market_code": "KRW-ATOM"},
    {"symbol": "ETC",  "name_ko": "이더리움클래식", "name_en": "Ethereum Classic", "exchange_type": "upbit", "market_code": "KRW-ETC"},
    {"symbol": "BCH",  "name_ko": "비트코인캐시","name_en": "Bitcoin Cash",  "exchange_type": "upbit",   "market_code": "KRW-BCH"},
    {"symbol": "TRX",  "name_ko": "트론",        "name_en": "TRON",          "exchange_type": "upbit",   "market_code": "KRW-TRX"},
    {"symbol": "EOS",  "name_ko": "이오스",      "name_en": "EOS",           "exchange_type": "upbit",   "market_code": "KRW-EOS"},
]


# ─── API 파서 ─────────────────────────────────────────────────────────────────

@dataclass
class CoinRow:
    symbol: str
    name_ko: str | None
    name_en: str | None
    exchange_type: str
    market_code: str
    is_active: bool = True


async def fetch_upbit_coins(client: httpx.AsyncClient) -> list[CoinRow]:
    """Upbit 마켓 코드 목록 조회 — KRW 마켓만 필터링."""
    url = "https://api.upbit.com/v1/market/all?isDetails=true"
    try:
        resp = await client.get(url, timeout=10.0)
        resp.raise_for_status()
        data: list[dict[str, Any]] = resp.json()
    except Exception as exc:
        logger.warning("Upbit API 호출 실패: %s", exc)
        return []

    rows: list[CoinRow] = []
    for item in data:
        market: str = item.get("market", "")
        if not market.startswith("KRW-"):
            continue
        symbol = market.split("-")[1]
        rows.append(CoinRow(
            symbol=symbol,
            name_ko=item.get("korean_name"),
            name_en=item.get("english_name"),
            exchange_type="upbit",
            market_code=market,
        ))
    logger.info("Upbit: %d개 KRW 마켓 코인 조회", len(rows))
    return rows


async def fetch_coinone_coins(client: httpx.AsyncClient) -> list[CoinRow]:
    """CoinOne 마켓 목록 조회."""
    url = "https://api.coinone.co.kr/public/v2/markets/all"
    try:
        resp = await client.get(url, timeout=10.0)
        resp.raise_for_status()
        body: dict[str, Any] = resp.json()
    except Exception as exc:
        logger.warning("CoinOne API 호출 실패: %s", exc)
        return []

    markets: list[dict[str, Any]] = body.get("markets", [])
    rows: list[CoinRow] = []
    for item in markets:
        target: str = item.get("target_currency", "").upper()
        quote: str = item.get("quote_currency", "").upper()
        if quote != "KRW" or not target:
            continue
        market_code = f"{quote}-{target}"
        rows.append(CoinRow(
            symbol=target,
            name_ko=item.get("name"),
            name_en=item.get("name_eng") or item.get("name"),
            exchange_type="coinone",
            market_code=market_code,
        ))
    logger.info("CoinOne: %d개 KRW 마켓 코인 조회", len(rows))
    return rows


# ─── DB Upsert ────────────────────────────────────────────────────────────────

async def upsert_coins(session: AsyncSession, rows: list[CoinRow]) -> int:
    """ON CONFLICT DO UPDATE로 멱등성 upsert. 삽입/업데이트된 행 수 반환."""
    if not rows:
        return 0

    values = [
        {
            "symbol": r.symbol,
            "name_ko": r.name_ko,
            "name_en": r.name_en,
            "exchange_type": r.exchange_type,
            "market_code": r.market_code,
            "is_active": r.is_active,
        }
        for r in rows
    ]

    stmt = pg_insert(Coin).values(values)
    stmt = stmt.on_conflict_do_update(
        constraint="uq_coin_exchange_market",
        set_={
            "symbol": stmt.excluded.symbol,
            "name_ko": stmt.excluded.name_ko,
            "name_en": stmt.excluded.name_en,
            "is_active": stmt.excluded.is_active,
            "updated_at": func.now(),
        },
    )
    result = await session.execute(stmt)
    await session.commit()
    return result.rowcount


async def deactivate_missing_coins(
    session: AsyncSession,
    exchange_type: str,
    active_market_codes: set[str],
) -> int:
    """거래소에서 사라진 코인을 is_active=false 처리."""
    from sqlalchemy import update as sa_update

    stmt = (
        sa_update(Coin)
        .where(
            Coin.exchange_type == exchange_type,
            Coin.market_code.not_in(active_market_codes),
            Coin.is_active.is_(True),
        )
        .values(is_active=False, updated_at=func.now())
    )
    result = await session.execute(stmt)
    await session.commit()
    deactivated = result.rowcount
    if deactivated:
        logger.info("%s: %d개 코인 비활성 처리", exchange_type, deactivated)
    return deactivated


# ─── 메인 ────────────────────────────────────────────────────────────────────

async def seed(exchange: str | None = None) -> None:
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    async_session: sessionmaker[AsyncSession] = sessionmaker(  # type: ignore[type-arg]
        engine, class_=AsyncSession, expire_on_commit=False
    )

    async with httpx.AsyncClient() as client:
        upbit_rows: list[CoinRow] = []
        coinone_rows: list[CoinRow] = []
        upbit_is_fallback = False
        coinone_is_fallback = False

        run_upbit = exchange in (None, "upbit")
        run_coinone = exchange in (None, "coinone")

        if run_upbit:
            upbit_rows = await fetch_upbit_coins(client)
            if not upbit_rows:
                logger.warning("Upbit API 실패 → fallback 코인 15개 사용")
                upbit_rows = [
                    CoinRow(**{k: v for k, v in coin.items()})  # type: ignore[arg-type]
                    for coin in FALLBACK_COINS
                ]
                upbit_is_fallback = True

        if run_coinone:
            coinone_rows = await fetch_coinone_coins(client)
            # CoinOne fallback: Upbit fallback 코인에서 exchange_type만 변환
            if not coinone_rows:
                logger.warning("CoinOne API 실패 → fallback 코인 15개 사용")
                coinone_rows = [
                    CoinRow(
                        symbol=coin["symbol"],  # type: ignore[arg-type]
                        name_ko=coin["name_ko"],  # type: ignore[arg-type]
                        name_en=coin["name_en"],  # type: ignore[arg-type]
                        exchange_type="coinone",
                        market_code=coin["market_code"],  # type: ignore[arg-type]
                    )
                    for coin in FALLBACK_COINS
                ]
                coinone_is_fallback = True

    async with async_session() as session:
        if run_upbit and upbit_rows:
            count = await upsert_coins(session, upbit_rows)
            logger.info("Upbit: %d행 upsert 완료", count)
            if not upbit_is_fallback:
                await deactivate_missing_coins(
                    session, "upbit", {r.market_code for r in upbit_rows}
                )

        if run_coinone and coinone_rows:
            count = await upsert_coins(session, coinone_rows)
            logger.info("CoinOne: %d행 upsert 완료", count)
            if not coinone_is_fallback:
                await deactivate_missing_coins(
                    session, "coinone", {r.market_code for r in coinone_rows}
                )

    await engine.dispose()
    logger.info("seed_coins 완료")


def main() -> None:
    parser = argparse.ArgumentParser(description="코인 초기 데이터 로드")
    parser.add_argument(
        "--exchange",
        choices=["upbit", "coinone"],
        default=None,
        help="특정 거래소만 로드 (기본: 전체)",
    )
    args = parser.parse_args()
    asyncio.run(seed(exchange=args.exchange))


if __name__ == "__main__":
    main()

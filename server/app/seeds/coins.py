"""코인 마스터 시드 데이터.

사용법: python -m app.seeds.coins
"""

# Upbit KRW 마켓 주요 코인 (15개)
UPBIT_COINS = [
    {"symbol": "BTC", "name_ko": "비트코인", "name_en": "Bitcoin", "exchange_type": "upbit", "market_code": "KRW-BTC"},
    {"symbol": "ETH", "name_ko": "이더리움", "name_en": "Ethereum", "exchange_type": "upbit", "market_code": "KRW-ETH"},
    {"symbol": "XRP", "name_ko": "리플", "name_en": "Ripple", "exchange_type": "upbit", "market_code": "KRW-XRP"},
    {"symbol": "SOL", "name_ko": "솔라나", "name_en": "Solana", "exchange_type": "upbit", "market_code": "KRW-SOL"},
    {"symbol": "DOGE", "name_ko": "도지코인", "name_en": "Dogecoin", "exchange_type": "upbit", "market_code": "KRW-DOGE"},
    {"symbol": "ADA", "name_ko": "에이다", "name_en": "Cardano", "exchange_type": "upbit", "market_code": "KRW-ADA"},
    {"symbol": "AVAX", "name_ko": "아발란체", "name_en": "Avalanche", "exchange_type": "upbit", "market_code": "KRW-AVAX"},
    {"symbol": "DOT", "name_ko": "폴카닷", "name_en": "Polkadot", "exchange_type": "upbit", "market_code": "KRW-DOT"},
    {"symbol": "MATIC", "name_ko": "폴리곤", "name_en": "Polygon", "exchange_type": "upbit", "market_code": "KRW-MATIC"},
    {"symbol": "LINK", "name_ko": "체인링크", "name_en": "Chainlink", "exchange_type": "upbit", "market_code": "KRW-LINK"},
    {"symbol": "ATOM", "name_ko": "코스모스", "name_en": "Cosmos", "exchange_type": "upbit", "market_code": "KRW-ATOM"},
    {"symbol": "ETC", "name_ko": "이더리움클래식", "name_en": "Ethereum Classic", "exchange_type": "upbit", "market_code": "KRW-ETC"},
    {"symbol": "BCH", "name_ko": "비트코인캐시", "name_en": "Bitcoin Cash", "exchange_type": "upbit", "market_code": "KRW-BCH"},
    {"symbol": "NEAR", "name_ko": "니어프로토콜", "name_en": "NEAR Protocol", "exchange_type": "upbit", "market_code": "KRW-NEAR"},
    {"symbol": "SUI", "name_ko": "수이", "name_en": "Sui", "exchange_type": "upbit", "market_code": "KRW-SUI"},
]

# CoinOne KRW 마켓 주요 코인 (10개)
COINONE_COINS = [
    {"symbol": "BTC", "name_ko": "비트코인", "name_en": "Bitcoin", "exchange_type": "coinone", "market_code": "KRW-BTC"},
    {"symbol": "ETH", "name_ko": "이더리움", "name_en": "Ethereum", "exchange_type": "coinone", "market_code": "KRW-ETH"},
    {"symbol": "XRP", "name_ko": "리플", "name_en": "Ripple", "exchange_type": "coinone", "market_code": "KRW-XRP"},
    {"symbol": "SOL", "name_ko": "솔라나", "name_en": "Solana", "exchange_type": "coinone", "market_code": "KRW-SOL"},
    {"symbol": "DOGE", "name_ko": "도지코인", "name_en": "Dogecoin", "exchange_type": "coinone", "market_code": "KRW-DOGE"},
    {"symbol": "ADA", "name_ko": "에이다", "name_en": "Cardano", "exchange_type": "coinone", "market_code": "KRW-ADA"},
    {"symbol": "DOT", "name_ko": "폴카닷", "name_en": "Polkadot", "exchange_type": "coinone", "market_code": "KRW-DOT"},
    {"symbol": "LINK", "name_ko": "체인링크", "name_en": "Chainlink", "exchange_type": "coinone", "market_code": "KRW-LINK"},
    {"symbol": "ATOM", "name_ko": "코스모스", "name_en": "Cosmos", "exchange_type": "coinone", "market_code": "KRW-ATOM"},
    {"symbol": "ETC", "name_ko": "이더리움클래식", "name_en": "Ethereum Classic", "exchange_type": "coinone", "market_code": "KRW-ETC"},
]

INITIAL_COINS = UPBIT_COINS + COINONE_COINS


async def seed_coins() -> None:
    """멱등성 보장 시드 (ON CONFLICT DO NOTHING)."""
    from sqlalchemy import text

    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        for coin_data in INITIAL_COINS:
            await session.execute(
                text("""
                    INSERT INTO coins (id, symbol, name_ko, name_en, exchange_type, market_code)
                    VALUES (gen_random_uuid(), :symbol, :name_ko, :name_en, :exchange_type, :market_code)
                    ON CONFLICT (exchange_type, market_code) DO NOTHING
                """),
                coin_data,
            )
        await session.commit()


if __name__ == "__main__":
    import asyncio

    asyncio.run(seed_coins())

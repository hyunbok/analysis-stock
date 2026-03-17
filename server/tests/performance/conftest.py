"""벤치마크 공통 픽스처."""
from __future__ import annotations

import random
import time
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.trading.indicators.types import CandleInput


# ── 캔들 데이터 생성 헬퍼 ─────────────────────────────────────────────────────

def _make_candles(n: int) -> list[CandleInput]:
    """n개의 합성 OHLCV 캔들 생성."""
    candles: list[CandleInput] = []
    base_price = 50_000_000.0  # KRW 기준 BTC 가격
    ts = time.time() - n * 60
    for _ in range(n):
        open_ = base_price + random.uniform(-100_000, 100_000)
        high = open_ + random.uniform(0, 200_000)
        low = open_ - random.uniform(0, 200_000)
        close = random.uniform(low, high)
        volume = random.uniform(0.01, 10.0)
        candles.append(
            CandleInput(
                timestamp=ts,
                open=open_,
                high=high,
                low=low,
                close=close,
                volume=volume,
            )
        )
        ts += 60
        base_price = close
    return candles


@pytest.fixture
def candles_200() -> list[CandleInput]:
    """200개 캔들 픽스처 (EMA-200 기준)."""
    return _make_candles(200)


@pytest.fixture
def candles_576() -> list[CandleInput]:
    """576개 캔들 픽스처 (24h × 24개 = 일 데이터 기준)."""
    return _make_candles(576)


# ── 인증 사용자 mock ──────────────────────────────────────────────────────────

@pytest.fixture
def mock_user() -> MagicMock:
    user = MagicMock()
    user.id = uuid.uuid4()
    user.email = "bench@example.com"
    user.nickname = "bench_user"
    user.avatar_url = None
    user.language = "ko"
    user.theme = "system"
    user.price_color_style = "korean"
    user.ai_trading_enabled = False
    user.is_2fa_enabled = False
    user.email_verified_at = datetime.now(timezone.utc)
    user.soft_deleted_at = None
    user.created_at = datetime.now(timezone.utc)
    return user


# ── fakeredis 클라이언트 ──────────────────────────────────────────────────────

@pytest.fixture
async def fake_redis():
    """fakeredis async 클라이언트."""
    try:
        import fakeredis.aioredis as fakeredis_async
        client = fakeredis_async.FakeRedis()
        yield client
        await client.aclose()
    except ImportError:
        pytest.skip("fakeredis not installed")

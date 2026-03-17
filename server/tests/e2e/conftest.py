"""E2E 테스트 공용 픽스처.

설계서 ADR-025-2 기반:
- DB 초기화: Alembic upgrade(head) — 마이그레이션 누락 조기 감지
- 세션: 커밋 허용 + teardown cleanup (multi-request E2E 롤백 불가)
- fakeredis: FakeServer() 세션 공유 — pub/sub 채널 동작 지원 (WS E2E 필수)
- 글로벌 Redis 직접 교체 + ExchangeProviderFactory 싱글턴 초기화
"""
from __future__ import annotations

import os

import fakeredis.aioredis as fakeredis_aio
import pytest
import pytest_asyncio
from fakeredis import FakeServer
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# 모든 PG 모델 등록 (Alembic target_metadata 인식용)
import app.models  # noqa: F401


def _get_e2e_pg_url() -> str:
    """E2E 전용 TEST_DATABASE_URL 또는 _e2e suffix DB."""
    if url := os.getenv("TEST_DATABASE_URL"):
        return url
    from app.core.config import settings
    parts = settings.DATABASE_URL.rsplit("/", 1)
    return f"{parts[0]}/{parts[1]}_e2e"


def _run_alembic(sync_conn, target: str) -> None:
    """Alembic 마이그레이션 실행 — 동기 커넥션 바인딩."""
    from alembic import command
    from alembic.config import Config

    cfg = Config("alembic.ini")
    cfg.attributes["connection"] = sync_conn
    if target == "head":
        command.upgrade(cfg, target)
    else:
        command.downgrade(cfg, target)


# ── 세션 범위 (1회 초기화) ────────────────────────────────────────────────────


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def e2e_engine():
    """E2E용 PG 엔진 — Alembic 마이그레이션으로 DB 생성."""
    engine = create_async_engine(_get_e2e_pg_url(), echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: _run_alembic(c, "head"))
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: _run_alembic(c, "base"))
    await engine.dispose()


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def fake_redis_server():
    """fakeredis FakeServer — 세션 공유로 pub/sub 채널 동작 지원."""
    return FakeServer()


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def e2e_redis(fake_redis_server):
    """E2E용 Redis — FakeServer 공유 (pub/sub 지원), decode_responses=True."""
    client = fakeredis_aio.FakeRedis(server=fake_redis_server, decode_responses=True)
    yield client
    await client.aclose()


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def e2e_pubsub_redis(fake_redis_server):
    """Pub/Sub 전용 Redis — 동일 FakeServer 공유."""
    client = fakeredis_aio.FakeRedis(server=fake_redis_server, decode_responses=True)
    yield client
    await client.aclose()


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def mongo_client():
    """E2E용 MongoDB — mongomock-motor 세션 범위."""
    try:
        from mongomock_motor import AsyncMongoMockClient
    except ImportError:
        pytest.skip("mongomock-motor not installed; skipping E2E tests with MongoDB")

    from beanie import init_beanie

    from app.documents.audit_logs import AuditLog
    from app.documents.notifications import Notification
    from app.documents.trading_logs import AiDecision, DailyPnlReport, TradeLog
    from app.documents.news_data import NewsData

    client = AsyncMongoMockClient()
    await init_beanie(
        database=client.get_database("cointrader_e2e"),
        document_models=[TradeLog, AiDecision, DailyPnlReport, Notification, AuditLog, NewsData],
    )
    yield client


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def e2e_app(e2e_engine, e2e_redis, e2e_pubsub_redis, mongo_client):
    """실제 앱 + 글로벌 상태 교체 + DI override.

    주의:
    - get_redis()/get_pubsub_redis()는 글로벌 변수 패턴 → dependency_overrides 외에 모듈
      글로벌 직접 교체 필요.
    - ExchangeProviderFactory 싱글턴이므로 init() 호출.
    - lifespan은 실행하지 않으므로 WS 관련 state(ws_hub, ws_bridge 등)는 직접 설정.
    """
    from app.main import app
    import app.core.redis as redis_module
    from app.core.database import get_db
    from app.core.mongodb import get_mongodb
    from app.providers.factory import ExchangeProviderFactory
    from app.ws.hub import WSHub
    from app.ws.subscribers import PubSubSubscriber
    from app.core.pubsub import RedisPublisher
    from app.ws.bridge import ExchangeStreamBridge
    from app.ws.router import MessageRouter

    # 1. 글로벌 Redis 클라이언트 직접 교체
    redis_module._redis_client = e2e_redis
    redis_module._pubsub_client = e2e_pubsub_redis

    # 2. ExchangeProviderFactory 싱글턴 초기화 (기존 인스턴스 교체)
    ExchangeProviderFactory._instance = None
    factory = ExchangeProviderFactory.init(redis=e2e_redis)
    factory.register_defaults()

    # 3. DI override: DB 세션
    session_factory = async_sessionmaker(e2e_engine, class_=AsyncSession, expire_on_commit=False)

    async def _get_db():
        async with session_factory() as s:
            yield s

    app.dependency_overrides[get_db] = _get_db

    # 4. MongoDB DI override
    def _get_mongodb():
        return mongo_client.get_database("cointrader_e2e")

    app.dependency_overrides[get_mongodb] = _get_mongodb

    # 5. AsyncSessionLocal 교체 — authenticate_ws()가 직접 사용하므로 DI override 불충분
    import app.core.database as db_module

    original_session_local = db_module.AsyncSessionLocal
    db_module.AsyncSessionLocal = async_sessionmaker(
        e2e_engine, class_=AsyncSession, expire_on_commit=False
    )

    # 6. WebSocket 상태 설정 (lifespan 미실행 대체)
    ws_hub = WSHub()
    publisher = RedisPublisher(e2e_redis)
    bridge = ExchangeStreamBridge(factory, publisher, redis=e2e_redis)
    subscriber = PubSubSubscriber(e2e_pubsub_redis, ws_hub)
    ws_router = MessageRouter(ws_hub, subscriber, bridge)

    app.state.ws_hub = ws_hub
    app.state.ws_bridge = bridge
    app.state.ws_subscriber = subscriber
    app.state.ws_router = ws_router

    yield app

    # 정리
    app.dependency_overrides.clear()
    await factory.close_all()
    ExchangeProviderFactory._instance = None
    redis_module._redis_client = None
    redis_module._pubsub_client = None
    db_module.AsyncSessionLocal = original_session_local


# ── 함수 범위 (테스트별 독립) ─────────────────────────────────────────────────


@pytest_asyncio.fixture(loop_scope="session")
async def e2e_db_session(e2e_engine):
    """DB 직접 검증용 세션 — API 호출 결과를 DB에서 확인할 때만 사용.

    주의: API 호출은 e2e_client로, DB 검증만 이 세션으로.
    API 요청은 e2e_app의 DI override로 별도 세션이 생성됨.
    """
    session_factory = async_sessionmaker(e2e_engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session


@pytest_asyncio.fixture(loop_scope="session")
async def e2e_client(e2e_app):
    """httpx AsyncClient — E2E API 호출 전용."""
    async with AsyncClient(
        transport=ASGITransport(app=e2e_app),
        base_url="http://test",
    ) as client:
        yield client


@pytest_asyncio.fixture(loop_scope="session")
async def test_user(e2e_client, e2e_redis):
    """등록 + 인증된 사용자 픽스처 — access_token 포함.

    teardown: soft delete 대신 DB cleanup은 e2e_engine에서 Alembic base로 처리.
    """
    # 1. POST /api/v1/auth/register
    resp = await e2e_client.post(
        "/api/v1/auth/register",
        json={"email": "e2e@test.com", "password": "Test1234!", "nickname": "E2E테스터"},
    )
    assert resp.status_code == 201, f"register failed: {resp.text}"

    # 2. fakeredis에서 인증 코드 직접 조회 → POST /api/v1/auth/verify-email
    code = await e2e_redis.get("email_verify:e2e@test.com")
    assert code is not None, "인증 코드가 Redis에 없음"
    verify_resp = await e2e_client.post(
        "/api/v1/auth/verify-email",
        json={"email": "e2e@test.com", "code": code},
    )
    assert verify_resp.status_code == 200, f"verify-email failed: {verify_resp.text}"

    # 3. POST /api/v1/auth/login → token 반환
    login_resp = await e2e_client.post(
        "/api/v1/auth/login",
        json={"email": "e2e@test.com", "password": "Test1234!"},
    )
    assert login_resp.status_code == 200, f"login failed: {login_resp.text}"
    data = login_resp.json()["data"]

    yield {
        "user_id": data["user"]["id"],
        "access_token": data["tokens"]["access_token"],
        "refresh_token": data["tokens"]["refresh_token"],
        "email": "e2e@test.com",
    }
    # teardown: 세션 범위라 Alembic base 롤백 시 자동 cleanup


@pytest_asyncio.fixture(loop_scope="session")
async def test_exchange_account(e2e_client, test_user):
    """MockProvider 연결된 거래소 계정 픽스처."""
    headers = {"Authorization": f"Bearer {test_user['access_token']}"}
    resp = await e2e_client.post(
        "/api/v1/exchanges",
        json={
            "exchange_type": "upbit",
            "api_key": "mock-key",
            "api_secret": "mock-secret",
            "nickname": "E2E거래소",
        },
        headers=headers,
    )
    assert resp.status_code == 201, f"exchange register failed: {resp.text}"
    data = resp.json()["data"]

    yield {"account_id": data["id"], "exchange_type": "upbit"}

    # teardown
    await e2e_client.delete(f"/api/v1/exchanges/{data['id']}", headers=headers)

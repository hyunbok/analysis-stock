"""DB 쿼리 성능 벤치마크 — pytest-benchmark.

성능 기준 (설계서 ST6):
  - Redis 캐시 HIT: < 5ms
  - DB 쿼리 (단일 조회): < 10ms
  - DB 쿼리 (페이지네이션): < 50ms (1000건 기준)

구현 방식:
  - Redis: fakeredis (in-memory)
  - MongoDB: mongomock-motor + Beanie
  - 암호화: AES-256-GCM, bcrypt

Note: benchmark()는 내부적으로 함수를 여러 번 반복 호출.
      async 함수를 매번 새로 생성하는 lambda 패턴 사용.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

import pytest

pytestmark = pytest.mark.benchmark


def _assert_perf(benchmark, threshold_sec: float, label: str) -> None:
    """benchmark.stats가 있을 때만 성능 기준 검증."""
    if benchmark.stats:
        assert benchmark.stats["mean"] < threshold_sec, (
            f"{label}: {benchmark.stats['mean'] * 1000:.2f}ms > {threshold_sec * 1000:.0f}ms"
        )


# ── Redis 캐시 벤치마크 ───────────────────────────────────────────────────────

class TestRedisCacheBenchmark:
    """Redis 캐시 GET/SET 성능 — 기준: < 5ms."""

    def test_cache_set(self, benchmark, fake_redis):
        """Redis SET 연산 — 기준: mean < 5ms."""
        key = "bench:coin:price:BTC-KRW"
        value = "50000000"

        def _set():
            asyncio.run(fake_redis.set(key, value, ex=60))

        benchmark(_set)
        _assert_perf(benchmark, 0.005, "Redis SET")

    def test_cache_get_hit(self, benchmark, fake_redis):
        """Redis GET HIT 연산 — 기준: mean < 5ms."""
        key = "bench:coin:price:ETH-KRW"
        value = "3000000"

        asyncio.run(fake_redis.set(key, value, ex=60))

        def _get():
            result = asyncio.run(fake_redis.get(key))
            assert result is not None

        benchmark(_get)
        _assert_perf(benchmark, 0.005, "Redis GET HIT")

    def test_cache_get_miss(self, benchmark, fake_redis):
        """Redis GET MISS (키 없음) — 기준: mean < 5ms."""
        def _get():
            result = asyncio.run(fake_redis.get("bench:miss:fixed_key_no_exist"))
            assert result is None

        benchmark(_get)
        _assert_perf(benchmark, 0.005, "Redis GET MISS")

    def test_cache_hset_hget(self, benchmark, fake_redis):
        """Redis HSET/HGET (해시 필드) — 기준: mean < 5ms."""
        hash_key = "bench:market_cache:upbit"

        asyncio.run(fake_redis.hset(hash_key, "BTC-KRW", "50000000"))
        asyncio.run(fake_redis.hset(hash_key, "ETH-KRW", "3000000"))

        def _get():
            result = asyncio.run(fake_redis.hget(hash_key, "BTC-KRW"))
            assert result is not None

        benchmark(_get)
        _assert_perf(benchmark, 0.005, "Redis HGET")

    def test_cache_pipeline(self, benchmark, fake_redis):
        """Redis 파이프라인 일괄 처리 (5개 키) — 기준: mean < 5ms."""
        async def _pipeline_coro():
            pipe = fake_redis.pipeline()
            for i in range(5):
                pipe.set(f"bench:pipeline:{i}", str(i * 1000))
            await pipe.execute()

        def _pipeline():
            asyncio.run(_pipeline_coro())

        benchmark(_pipeline)
        _assert_perf(benchmark, 0.005, "Redis 파이프라인")


# ── 암호화 성능 벤치마크 ─────────────────────────────────────────────────────

class TestEncryptionBenchmark:
    """bcrypt/AES 암호화 연산 성능."""

    def test_bcrypt_verify(self, benchmark):
        """bcrypt 해시 검증 성능.

        CI용 cost=4로 측정 (기준: < 500ms).
        프로덕션 기본값은 cost=12이며 약 100-300ms 소요.
        CI에서는 테스트 속도를 위해 cost를 낮춰 실행.
        """
        import bcrypt
        password = b"TestPassword123!"
        hashed = bcrypt.hashpw(password, bcrypt.gensalt(rounds=4))

        def _verify():
            return bcrypt.checkpw(password, hashed)

        result = benchmark(_verify)
        assert result is True
        _assert_perf(benchmark, 0.500, "bcrypt 검증(cost=4)")

    def test_aes_encrypt_decrypt(self, benchmark):
        """AES-256-GCM 암호화/복호화 — 기준: < 5ms."""
        import os

        from app.core.encryption import decrypt_value, encrypt_value

        plaintext = "upbit_api_key_example_12345678901234"
        key = os.urandom(32)

        def _round_trip():
            encrypted = encrypt_value(plaintext, key)
            decrypted = decrypt_value(encrypted, key)
            assert decrypted == plaintext

        benchmark(_round_trip)
        _assert_perf(benchmark, 0.005, "AES-256-GCM 암호화/복호화")


# ── MongoDB 문서 벤치마크 ────────────────────────────────────────────────────

class TestMongoDBBenchmark:
    """MongoDB 문서 삽입/조회 성능 — mongomock-motor 사용.

    루트 conftest.py의 mongo_client 픽스처(session scope)를 활용.
    Beanie init_beanie()가 이미 완료된 상태에서 삽입/조회 성능만 측정.
    """

    def test_audit_log_insert(self, benchmark, mongo_client):
        """AuditLog 문서 단건 삽입 — 기준: < 10ms."""
        from app.documents.audit_logs import AuditLog

        async def _insert_coro():
            log = AuditLog(
                user_id=uuid.uuid4(),
                action="login_success",
                ip_address="127.0.0.1",
                user_agent="pytest-benchmark",
                details={"exchange": "upbit"},
                created_at=datetime.now(UTC),
            )
            await log.insert()

        def _insert():
            asyncio.run(_insert_coro())

        benchmark(_insert)
        _assert_perf(benchmark, 0.010, "AuditLog 삽입")

    def test_audit_log_query_limit(self, benchmark, mongo_client):
        """AuditLog 최근 10건 조회 — 기준: < 50ms.

        mongomock-motor는 asyncio.run() 오버헤드 + in-memory 처리로
        실제 MongoDB보다 느릴 수 있음. 실제 MongoDB 기준 < 10ms이나
        CI(mongomock) 환경에서는 < 50ms로 완화 적용.
        """
        from app.documents.audit_logs import AuditLog

        # 사전 데이터 적재
        async def _setup():
            for i in range(20):
                log = AuditLog(
                    user_id=uuid.uuid4(),
                    action="benchmark_query_test",
                    ip_address=f"127.0.0.{i}",
                    user_agent="pytest",
                    details={},
                    created_at=datetime.now(UTC),
                )
                await log.insert()

        asyncio.run(_setup())

        async def _query_coro():
            logs = await AuditLog.find_all().limit(10).to_list()
            assert len(logs) <= 10

        def _query():
            asyncio.run(_query_coro())

        benchmark(_query)
        _assert_perf(benchmark, 0.050, "AuditLog 조회(limit 10, mongomock)")

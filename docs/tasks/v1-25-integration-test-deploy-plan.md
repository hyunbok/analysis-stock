# v1-25: 통합 테스트 및 배포 파이프라인 구성 설계서

> **태스크**: v1:25
> **브랜치**: `feature/v1-25_integration-test-deploy`
> **작성**: project-architect + code-architect
> **최종 갱신**: 2026-03-17

---

## 1. 현재 상태 (프로젝트 컨텍스트)

### 기존 테스트 인프라

| 컴포넌트 | 위치 | 역할 | 상태 |
|----------|------|------|------|
| 루트 conftest | `tests/conftest.py` | PG engine/session, MongoDB mock(mongomock-motor), Beanie 초기화 | 재사용 |
| 통합 테스트 | `tests/integration/` (25개 파일) | API별 mock-service 주입 통합 테스트 | 재사용 |
| 단위 테스트 | `tests/unit/` (40+ 파일) | providers, services, trading 순수 로직 | 재사용 |
| trading 테스트 | `tests/trading/` | indicators 계산 테스트 | 재사용 |
| MockExchangeProvider | `providers/mock_provider.py` | 4가지 시나리오 (FILL/OPEN/PARTIAL/FAIL) | **확장** |
| pyproject.toml | `[tool.pytest.ini_options]` | asyncio_mode=auto, session scope | 재사용 |

### 기존 CI/CD

| 워크플로우 | 파일 | 역할 | 상태 |
|-----------|------|------|------|
| Server CI | `.github/workflows/ci.yml` | lint → type-check → test(cov 80%) | **확장** |
| Flutter CI | `.github/workflows/ci-flutter.yml` | analyze → test | **확장** |
| Docker Build | `.github/workflows/docker.yml` | Build & Push (ghcr.io) | **확장** |

### 기존 모니터링

| 컴포넌트 | 위치 | 역할 | 상태 |
|----------|------|------|------|
| Prometheus Instrumentator | `core/metrics.py` | HTTP 메트릭 자동 수집, /metrics 엔드포인트 | 재사용 |
| Sentry | `main.py:20-27` | 에러 트래킹 (조건부 초기화) | 재사용 |
| structlog | `main.py:30-44` | JSON 구조화 로깅 | 재사용 |
| Health Check | `api/v1/health.py` | PG + MongoDB + Redis 상태 확인 | 재사용 |
| CorrelationId | `middleware/correlation_id.py` | 요청별 추적 ID | 재사용 |

### 기존 통합 테스트 패턴

```python
# 현재 패턴: FastAPI 앱 생성 + dependency_overrides + httpx AsyncClient
@pytest.fixture
def test_app(mock_auth_service):
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(auth_router, prefix="/auth")
    app.dependency_overrides[get_auth_service] = lambda: mock_auth_service
    return app

# httpx로 API 호출
async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
    resp = await client.post("/auth/register", json={...})
```

**문제점**:
1. 서비스 레이어 mock → 실제 DB 연동 검증 불가
2. 개별 API 단위 테스트 → 크로스-API 흐름 검증 부재
3. WebSocket E2E 테스트 부재 (starlette TestClient만 사용)
4. 성능/부하 테스트 없음
5. CI에 E2E/성능 분리 실행 없음
6. 배포 파이프라인 스테이징/프로덕션 단계 없음

---

## 2. 설계 결정 (ADR)

### ADR-025-1: E2E 테스트 디렉토리 구조

**상태**: 승인됨
**맥락**: 기존 `tests/integration/`은 mock-service 기반 API 테스트. E2E는 실제 DB/Redis 연동 + 크로스-API 흐름 검증.
**선택지**:
1. `tests/integration/` 확장 — 기존 파일과 혼재
2. `tests/e2e/` 신규 — 독립 conftest, 실제 DB 연동
**결정**: `tests/e2e/` 신규. 이유: conftest 분리 필요 (Alembic DB 초기화 + 트랜잭션 롤백), 실행 시간 차이 (CI에서 별도 stage)
**영향**: pytest marker `@pytest.mark.e2e` + `@pytest.mark.benchmark` 추가, CI에서 `--ignore=tests/e2e` / `-m e2e` 분리

### ADR-025-2: E2E 픽스처 전략

**상태**: 승인됨 (code-architect 최종 합의)
**맥락**: E2E 테스트는 multi-request 시나리오(회원가입→로그인→주문) → 트랜잭션 롤백 불가, 실제 커밋 필요.
**결정**:
- **DB 초기화: Alembic 방식** (`create_all` 대신) — 마이그레이션 누락 조기 감지
- **세션: 커밋 허용 + teardown cleanup** — multi-request E2E는 롤백 불가, 테스트 후 생성 데이터 DELETE
- `tests/e2e/conftest.py`: Alembic upgrade(head) → 세션 팩토리 → 함수별 커밋+cleanup
- `e2e_client`: httpx AsyncClient(app=실제 app with DI override for DB/Redis)
- `test_user`: 가입 → fakeredis에서 인증코드 직접 조회 → 인증 → 로그인 → 토큰 반환 (teardown: soft delete)
- `test_exchange_account`: Mock Provider 기반 거래소 계정 생성 (teardown: DELETE)
- **fakeredis: `FakeServer()` 세션 공유** — pub/sub 채널 동작 지원 (WS E2E 필수)
- **단위/통합 테스트는 기존 `create_all` + 롤백 유지** (속도 우선)

### ADR-025-3: Mock Exchange Provider 전략

**상태**: 승인됨
**맥락**: E2E에서 주문 생성 → 체결 → 잔고 변경 시뮬레이션 필요.
**결정**: 기존 `MockExchangeProvider` 최소 확장 (E2E 전용 클래스 미생성). 이유:
- 이미 4가지 시나리오 (FILL/OPEN/PARTIAL/FAIL) 구현
- `_orders` dict로 상태 추적 가능
- `set_scenario()` per-test 설정
- 추가: `reset_orders()` 메서드 (테스트 간 주문 상태 초기화)
- **잔고 변경 검증은 Provider 잔고가 아닌 DB 주문 상태로 확인** (`set_balance()` 미채택)

### ADR-025-4: 성능 테스트 도구

**상태**: 승인됨
**맥락**: 단위 벤치마크 + HTTP 부하 테스트 둘 다 필요.
**결정**: 이중 도구 채택
- **pytest-benchmark**: indicators 계산, DB 쿼리, 캐시 HIT, 암호화 성능 → CI 주 1회 (`-m benchmark`)
- **locust**: HTTP API 부하, WS 동시접속 → 스테이징 배포 후 수동 or 주 1회 스케줄
**영향**: `tests/performance/` 디렉토리 신규, `locustfile.py` + `locust-plugins` (WebsocketUser)

**CI 실행 분리**:
```
PR 단위:         pytest tests/unit/ tests/integration/ -m "not benchmark"
develop merge:   pytest tests/e2e/ -m "not benchmark"
주 1회 스케줄:   pytest tests/performance/ -m benchmark
스테이징 후:     locust -f tests/performance/locustfile.py (수동)
```

### ADR-025-5: CI/CD 파이프라인 단계

**상태**: 승인됨
**맥락**: 현재 CI는 lint → type-check → test 단일 파이프라인. 배포 자동화 없음.
**결정**:
- **ci.yml 확장**: lint → type-check → unit-test → integration-test → e2e-test → coverage
- **cd.yml 신규**: staging 자동 배포 → 수동 승인 → production 배포
- **docker.yml 확장**: multi-stage + security scan (trivy)
- E2E는 별도 job (services: postgres, mongodb, redis)

### ADR-025-6: 모니터링 스택

**상태**: 승인됨
**맥락**: 기존 Prometheus instrumentator + Sentry. Grafana/Loki 미구성.
**결정**:
- `docker-compose.monitoring.yml` 별도 파일 (개발 환경 분리)
- Prometheus + Grafana (메트릭 대시보드)
- Loki + promtail (로그 수집 — structlog JSON)
- 커스텀 메트릭: 거래소 API 응답시간, Circuit Breaker 상태, AI 매매 실행 횟수, WS 연결 수
- AlertManager: Slack 웹훅 (에러율 급증, 거래소 장애)

### ADR-025-7: 배포 전략

**상태**: 승인됨
**맥락**: Docker Compose 기반 배포, 무중단 요구사항.
**결정**:
- `docker-compose.prod.yml`: production 환경 (replicas 불가 → Nginx reverse proxy + 2 server 컨테이너)
- Rolling Update: 새 컨테이너 Health Check 통과 후 구 컨테이너 종료
- Nginx: upstream health check, graceful reload
- 롤백: 이전 이미지 태그로 재배포 (1-click script)
- DB 마이그레이션: 배포 전 Alembic upgrade (CI/CD job)

---

## 3. 서브태스크별 상세 설계

### ST1: 인증 흐름 E2E 테스트 (e2e-test-expert)

#### 파일 목록

| 파일 | 역할 | 신규/수정 |
|------|------|-----------|
| `tests/e2e/__init__.py` | 패키지 초기화 | 신규 |
| `tests/e2e/conftest.py` | E2E 공통 픽스처 | 신규 |
| `tests/e2e/test_auth_flow.py` | 인증 흐름 E2E | 신규 |
| `tests/e2e/helpers.py` | 공통 헬퍼 (회원가입/로그인) | 신규 |

#### E2E conftest.py 픽스처 설계

```python
# tests/e2e/conftest.py
from alembic.config import Config
from alembic import command
from fakeredis import FakeServer
import fakeredis.aioredis as fakeredis_aio

def _run_alembic(sync_conn, target: str) -> None:
    """Alembic 마이그레이션 실행 — 동기 커넥션 바인딩."""
    cfg = Config("alembic.ini")
    cfg.attributes["connection"] = sync_conn
    if target == "head":
        command.upgrade(cfg, target)
    else:
        command.downgrade(cfg, target)

# ── 세션 범위 (1회 초기화) ──────────────────────────────────────────────────

@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def e2e_engine():
    """E2E용 PG 엔진 — Alembic 마이그레이션으로 DB 생성 (마이그레이션 누락 감지)."""
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
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
    """Pub/Sub 전용 Redis — 동일 FakeServer 공유 (socket_timeout=None 시뮬레이션)."""
    client = fakeredis_aio.FakeRedis(server=fake_redis_server, decode_responses=True)
    yield client
    await client.aclose()

@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def e2e_app(e2e_engine, e2e_redis, e2e_pubsub_redis, mongo_client):
    """실제 앱 + 글로벌 상태 교체 + DI override.

    주의: get_redis()/get_pubsub_redis()는 글로벌 변수 패턴이므로
    dependency_overrides 외에 모듈 글로벌 직접 교체 필요.
    ExchangeProviderFactory도 싱글턴이므로 _instance 직접 설정.
    """
    from app.main import app
    import app.core.redis as redis_module
    from app.core.database import get_db
    from app.providers.factory import ExchangeProviderFactory

    # 1. 글로벌 Redis 클라이언트 직접 교체 (get_redis(), get_pubsub_redis() 대응)
    redis_module._redis_client = e2e_redis
    redis_module._pubsub_client = e2e_pubsub_redis

    # 2. ExchangeProviderFactory 싱글턴 초기화 (fakeredis 기반)
    factory = ExchangeProviderFactory.init(redis=e2e_redis)
    factory.register_defaults()  # MockExchangeProvider 등록

    # 3. DI override: DB 세션만 (Redis는 글로벌 교체로 처리됨)
    session_factory = async_sessionmaker(e2e_engine, class_=AsyncSession, expire_on_commit=False)
    async def _get_db():
        async with session_factory() as s:
            yield s
    app.dependency_overrides[get_db] = _get_db

    yield app

    # 정리
    app.dependency_overrides.clear()
    await factory.close_all()
    ExchangeProviderFactory._instance = None
    redis_module._redis_client = None
    redis_module._pubsub_client = None

# ── 함수 범위 (테스트별 독립) ────────────────────────────────────────────────

@pytest_asyncio.fixture(loop_scope="session")
async def e2e_db_session(e2e_engine):
    """DB 직접 검증용 세션 — API 호출 결과를 DB에서 확인할 때 사용.

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
        base_url="http://test"
    ) as client:
        yield client

@pytest_asyncio.fixture(loop_scope="session")
async def test_user(e2e_client, e2e_redis):
    """등록+인증된 사용자 픽스처 — access_token 포함."""
    # 1. POST /api/v1/auth/register
    resp = await e2e_client.post("/api/v1/auth/register", json={
        "email": "e2e@test.com", "password": "Test1234!", "nickname": "E2E테스터"
    })
    # 2. fakeredis에서 인증 코드 직접 조회 → POST /api/v1/auth/verify-email
    code = await e2e_redis.get("email_verify:e2e@test.com")
    await e2e_client.post("/api/v1/auth/verify-email", json={
        "email": "e2e@test.com", "code": code
    })
    # 3. POST /api/v1/auth/login → token 반환
    resp = await e2e_client.post("/api/v1/auth/login", json={
        "email": "e2e@test.com", "password": "Test1234!"
    })
    data = resp.json()["data"]
    yield {
        "user_id": data["user"]["id"],
        "access_token": data["tokens"]["access_token"],
        "refresh_token": data["tokens"]["refresh_token"],
    }
    # teardown: soft delete (실제 API 호출로 cleanup)

@pytest_asyncio.fixture(loop_scope="session")
async def test_exchange_account(e2e_client, test_user):
    """MockProvider 연결된 거래소 계정 픽스처."""
    headers = {"Authorization": f"Bearer {test_user['access_token']}"}
    resp = await e2e_client.post("/api/v1/exchanges", json={
        "exchange_type": "upbit", "api_key": "mock-key", "secret_key": "mock-secret",
        "nickname": "E2E거래소"
    }, headers=headers)
    data = resp.json()["data"]
    yield {"account_id": data["id"], "exchange_type": "upbit"}
    # teardown: DELETE /api/v1/exchanges/{account_id}
    await e2e_client.delete(f"/api/v1/exchanges/{data['id']}", headers=headers)
```

> **설계 근거**:
> - **글로벌 상태 교체**: `get_redis()`/`get_pubsub_redis()`는 `_redis_client`/`_pubsub_client` 글로벌 반환 → `dependency_overrides`만으로는 불충분, 모듈 글로벌 직접 교체 필수
> - **ExchangeProviderFactory._instance 직접 설정**: 싱글턴 패턴이므로 `init()` 호출 후 `instance()` 정상 동작
> - **e2e_pubsub_redis 분리**: 실제 앱은 cache용/pub/sub용 Redis 클라이언트 분리 → E2E도 동일 구조 (동일 FakeServer 공유)
> - **e2e_db_session vs e2e_client 명확 분리**: API 호출은 `e2e_client`, DB 직접 검증만 `e2e_db_session`
> - **decode_responses=True**: 실제 Redis 설정과 일치 (`code.decode()` 불필요)
> - 단위/통합 테스트는 기존 `create_all` + 롤백 유지 (속도 우선)
> - E2E만 Alembic 방식 (마이그레이션 정합성 검증)

#### 테스트 시나리오

```
TC-AUTH-E2E-01: 회원가입 → 이메일 인증 → 로그인 → 토큰 갱신 → 로그아웃
TC-AUTH-E2E-02: 소셜 로그인 (Google Mock) → 토큰 발급 → /users/me 조회
TC-AUTH-E2E-03: 2FA 활성화 → 로그인 → TOTP 검증 → 접근
TC-AUTH-E2E-04: 비밀번호 변경 → 기존 세션 무효화 → 재로그인
TC-AUTH-E2E-05: 비활성 계정 로그인 시도 → 차단 확인
TC-AUTH-E2E-06: Rate Limit 초과 → 429 응답 → 윈도우 만료 후 복구
```

---

### ST2: 거래소 연동 E2E 테스트 (e2e-test-expert)

#### 파일 목록

| 파일 | 역할 | 신규/수정 |
|------|------|-----------|
| `tests/e2e/test_exchange_flow.py` | 거래소 연동 E2E | 신규 |
| `app/providers/mock_provider.py` | `set_balance()` 메서드 추가 | 수정 |

#### MockExchangeProvider 확장

```python
# mock_provider.py 변경 사항

# __init__에 _custom_balances 초기화 추가
def __init__(self, *args, **kwargs) -> None:
    super().__init__(*args, **kwargs)
    self._scenario: MockOrderScenario = MockOrderScenario.IMMEDIATE_FILL
    self._orders: dict[str, OrderResult] = {}
    self._custom_balances: list[Balance] | None = None  # 신규

# 신규 메서드
def set_balance(self, balances: list[Balance]) -> None:
    """E2E 테스트용 잔고 동적 설정."""
    self._custom_balances = balances

def reset_orders(self) -> None:
    """테스트 간 전체 상태 초기화."""
    self._orders.clear()
    self._scenario = MockOrderScenario.IMMEDIATE_FILL
    self._custom_balances = None

# get_balance() 수정
async def get_balance(self) -> list[Balance]:
    if self._custom_balances is not None:
        return self._custom_balances
    return [...]  # 기존 기본값
```

> 잔고 변경 검증은 가급적 **DB의 주문 상태/트레이드 로그**에서 직접 확인.
> `set_balance()`는 포트폴리오 E2E 시나리오 등 거래소 잔고 응답 조작이 필요한 경우에만 사용.

#### 테스트 시나리오

```
TC-EXCHANGE-E2E-01: API 키 등록 → 검증(verify_api_key) → 거래소 계정 활성화
TC-EXCHANGE-E2E-02: 시세 조회 → 호가 조회 → 캔들 조회 (전체 시장 데이터)
TC-EXCHANGE-E2E-03: 시장가 매수 → 체결 확인 → 잔고 변경 → 주문 내역 조회
TC-EXCHANGE-E2E-04: 지정가 매도 → OPEN 상태 → 취소 → 잔고 복구
TC-EXCHANGE-E2E-05: 잔고 부족 주문 → 실패 → 에러 응답 검증
TC-EXCHANGE-E2E-06: 일괄 취소 → 부분 성공 → BatchCancelResponse 검증
```

---

### ST3: AI 매매 흐름 E2E 테스트 (e2e-test-expert)

#### 파일 목록

| 파일 | 역할 | 신규/수정 |
|------|------|-----------|
| `tests/e2e/test_ai_trading_flow.py` | AI 매매 흐름 E2E | 신규 |
| `tests/e2e/fixtures/mock_openai.py` | OpenAI API Mock | 신규 |

#### 테스트 시나리오

```
TC-AI-E2E-01: 캔들 데이터 → indicators 계산 → Redis 캐시 → 지표 조회 API
TC-AI-E2E-02: indicators → regime 분석 → GPT 검증(Mock) → 장세 결정
TC-AI-E2E-03: regime → strategy 선택 → signal 생성 → 주문 실행
TC-AI-E2E-04: 리스크 관리: 최대 동시 포지션 초과 → 주문 거부
TC-AI-E2E-05: Drawdown 한도 도달 → 매매 중단 → 알림 발생
TC-AI-E2E-06: Celery task(ai_trading) → 전체 파이프라인 실행 → MongoDB 로그 검증
```

#### OpenAI Mock 패턴

```python
# tests/e2e/fixtures/mock_openai.py
class MockOpenAIClient:
    """GPT 응답 시뮬레이션 — regime validation 용."""
    async def chat_completions_create(self, **kwargs):
        return MockCompletion(
            content='{"regime": "trend", "confidence": 0.85, "reasoning": "test"}'
        )

@pytest.fixture
def mock_openai(monkeypatch):
    """openai.AsyncOpenAI를 MockOpenAIClient로 교체."""
    monkeypatch.setattr("openai.AsyncOpenAI", lambda **kw: MockOpenAIClient())
```

---

### ST4: 포트폴리오 및 손익 계산 E2E 테스트 (e2e-test-expert)

#### 파일 목록

| 파일 | 역할 | 신규/수정 |
|------|------|-----------|
| `tests/e2e/test_portfolio_flow.py` | 포트폴리오 E2E | 신규 |

#### 테스트 시나리오

```
TC-PORTFOLIO-E2E-01: 거래소 계정 연결 → 잔고 조회 → 포트폴리오 통합 응답
TC-PORTFOLIO-E2E-02: 복수 거래소 자산 → 총 자산 계산 → KRW 환산 정확성
TC-PORTFOLIO-E2E-03: 주문 체결 후 → 포트폴리오 갱신 → 수익률 계산
TC-PORTFOLIO-E2E-04: 일일 PnL 리포트 생성 → MongoDB 저장 → 조회 API
TC-PORTFOLIO-E2E-05: 캐시된 시세(Redis) 활용 → 캐시 미스 시 거래소 조회 폴백
```

---

### ST5: WebSocket 실시간 통신 E2E 테스트 (e2e-test-expert)

#### 파일 목록

| 파일 | 역할 | 신규/수정 |
|------|------|-----------|
| `tests/e2e/test_websocket_flow.py` | WebSocket E2E | 신규 |

#### 테스트 시나리오

```
TC-WS-E2E-01: JWT 인증 → WS 연결 → 시세 구독 → ticker 메시지 수신
TC-WS-E2E-02: 다중 심볼 구독 → 구독 해제 → 메시지 중단 확인
TC-WS-E2E-03: 호가 구독 → orderbook 업데이트 수신
TC-WS-E2E-04: 알림 채널 구독 → 주문 체결 알림 수신
TC-WS-E2E-05: 비인증 연결 시도 → 거부 (close code 4001: Unauthorized)
TC-WS-E2E-06: 삭제된 계정 연결 → 거부 (close code 4003: Forbidden)
TC-WS-E2E-07: Heartbeat 타임아웃 → 서버 측 연결 종료
TC-WS-E2E-08: 동시 연결 제한 (MAX_CONNECTIONS_PER_USER=5) → 초과 시 거부
```

#### WebSocket 테스트 패턴

기존 `test_websocket_hub.py`와 동일하게 Starlette TestClient(sync) 패턴 사용.
asyncio 기반 WS 테스트(websockets 라이브러리)는 복잡도 대비 이점 없으므로 미채택.

> **WS 프로토콜**: `?token={access_token}` 쿼리 파라미터 인증, 메시지 포맷은 `action` + `channel` + `exchange` + `market` (단수).

```python
# tests/e2e/test_ws_realtime.py — Starlette TestClient sync 패턴
def test_ws_ticker_subscribe(e2e_app, test_user):
    """ticker 구독 → 시세 수신 E2E 흐름."""
    token = test_user["access_token"]
    client = TestClient(e2e_app)
    with client.websocket_connect(f"/ws/v1?token={token}") as ws:
        connected = ws.receive_json()  # {"action": "connected", "conn_id": "..."}
        assert connected["action"] == "connected"

        ws.send_json({
            "action": "subscribe",
            "channel": "ticker",
            "exchange": "upbit",
            "market": "KRW-BTC",
        })
        msg = ws.receive_json()
        assert msg["action"] == "subscribed"
        assert msg["channel"] == "ticker"
        assert msg["exchange"] == "upbit"
        assert msg["market"] == "KRW-BTC"

def test_ws_unauthorized_rejected(e2e_app):
    """토큰 없이 WS 연결 → close code 4001 (Unauthorized)."""
    with pytest.raises(Exception):
        with TestClient(e2e_app).websocket_connect("/ws/v1?token=bad-token") as ws:
            ws.receive_json()  # 여기까지 도달하면 안 됨
```

---

### ST6: 성능 테스트 및 벤치마크 구성 (python-backend-expert)

#### 파일 목록

| 파일 | 역할 | 신규/수정 |
|------|------|-----------|
| `tests/performance/__init__.py` | 패키지 초기화 | 신규 |
| `tests/performance/conftest.py` | 벤치마크 픽스처 | 신규 |
| `tests/performance/test_api_benchmarks.py` | API 응답 시간 벤치마크 | 신규 |
| `tests/performance/test_indicator_benchmarks.py` | 지표 계산 벤치마크 | 신규 |
| `tests/performance/test_db_benchmarks.py` | DB 쿼리 벤치마크 | 신규 |
| `tests/performance/locustfile.py` | Locust 부하 테스트 시나리오 | 신규 |

#### pytest-benchmark 성능 기준

| 측정 대상 | 기준 | 비고 |
|-----------|------|------|
| indicators 200행 계산 | < 50ms | PRD §v1-15 |
| indicators 576행 계산 | < 100ms | PRD §v1-15 |
| Redis 캐시 HIT | < 5ms | |
| API 응답 (인증) | < 200ms (p95 < 500ms) | PRD §10.1 |
| API 응답 (주문) | < 300ms (p95 < 700ms) | 거래소 호출 포함 |
| DB 쿼리 (단일 조회) | < 10ms | 인덱스 활용 |
| DB 쿼리 (페이지네이션) | < 50ms | 1000건 기준 |

#### Locust 부하 시나리오

```python
# tests/performance/locustfile.py
class CoinTraderUser(HttpUser):
    wait_time = between(1, 3)

    @task(3)
    def get_coins(self):
        self.client.get("/api/v1/coins?page=1&size=20")

    @task(2)
    def get_portfolio(self):
        self.client.get("/api/v1/portfolio", headers=self.auth_headers)

    @task(1)
    def place_order(self):
        self.client.post("/api/v1/orders", json={...}, headers=self.auth_headers)

class WebSocketUser(User):
    """WS 동시접속 부하 테스트."""
    # websocket-client 기반
```

#### 부하 테스트 목표

| 메트릭 | 목표 | 비고 |
|--------|------|------|
| 동시 사용자 | 100명 | API + WS 혼합 |
| WS 동시 연결 | 1,000개 | PRD §10.1 |
| API RPS | 500 req/s | p95 < 500ms |
| 에러율 | < 1% | 5xx 기준 |

---

### ST7: CI/CD 파이프라인 완성 및 배포 자동화 (project-architect)

#### 파일 목록

| 파일 | 역할 | 신규/수정 |
|------|------|-----------|
| `.github/workflows/ci.yml` | Server CI 확장 | 수정 |
| `.github/workflows/ci-flutter.yml` | Flutter CI 확장 | 수정 |
| `.github/workflows/cd.yml` | CD 파이프라인 (staging → prod) | 신규 |
| `.github/workflows/docker.yml` | Docker Build 확장 (security scan) | 수정 |
| `.github/workflows/nightly.yml` | Nightly 성능 테스트 | 신규 |

#### ci.yml 확장 설계

```yaml
# .github/workflows/ci.yml
name: Server CI

on:
  push:
    branches: [main, develop]
    paths: ['server/**']
  pull_request:
    branches: [main, develop]
    paths: ['server/**']

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.12', cache: pip }
      - run: pip install ruff
      - run: ruff check server/app/ server/tests/

  type-check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.12', cache: pip }
      - run: pip install -r server/requirements.txt mypy pydantic
      - run: cd server && mypy app/

  unit-test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.12', cache: pip }
      - run: pip install -r server/requirements.txt && pip install pytest pytest-asyncio pytest-cov httpx mongomock-motor "fakeredis[aioredis]"
      - run: cd server && pytest tests/unit/ tests/trading/ -v --cov=app --cov-report=xml
      - uses: actions/upload-artifact@v4
        with: { name: unit-coverage, path: server/coverage.xml }

  integration-test:
    runs-on: ubuntu-latest
    needs: [lint, type-check]
    services:
      postgres:
        image: postgres:16-alpine
        env:
          POSTGRES_USER: cointrader
          POSTGRES_PASSWORD: testpassword
          POSTGRES_DB: cointrader_test
        ports: ['5432:5432']
        options: >-
          --health-cmd pg_isready --health-interval 10s --health-timeout 5s --health-retries 5
      redis:
        image: redis:7-alpine
        ports: ['6379:6379']
        options: >-
          --health-cmd "redis-cli ping" --health-interval 10s --health-timeout 5s --health-retries 5
    env:
      TEST_DATABASE_URL: postgresql+asyncpg://cointrader:testpassword@localhost:5432/cointrader_test
      REDIS_URL: redis://localhost:6379/0
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.12', cache: pip }
      - run: pip install -r server/requirements.txt && pip install pytest pytest-asyncio pytest-cov httpx mongomock-motor "fakeredis[aioredis]"
      - run: cd server && pytest tests/integration/ -v --cov=app --cov-report=xml --cov-append
      - uses: actions/upload-artifact@v4
        with: { name: integration-coverage, path: server/coverage.xml }

  e2e-test:
    runs-on: ubuntu-latest
    needs: [integration-test]
    services:
      postgres:
        image: postgres:16-alpine
        env:
          POSTGRES_USER: cointrader
          POSTGRES_PASSWORD: testpassword
          POSTGRES_DB: cointrader_test
        ports: ['5432:5432']
        options: >-
          --health-cmd pg_isready --health-interval 10s --health-timeout 5s --health-retries 5
      mongodb:
        image: mongo:7
        env:
          MONGO_INITDB_ROOT_USERNAME: cointrader
          MONGO_INITDB_ROOT_PASSWORD: testpassword
        ports: ['27017:27017']
      redis:
        image: redis:7-alpine
        ports: ['6379:6379']
        options: >-
          --health-cmd "redis-cli ping" --health-interval 10s --health-timeout 5s --health-retries 5
    env:
      TEST_DATABASE_URL: postgresql+asyncpg://cointrader:testpassword@localhost:5432/cointrader_test
      MONGODB_URL: mongodb://cointrader:testpassword@localhost:27017/cointrader_test?authSource=admin
      REDIS_URL: redis://localhost:6379/0
      JWT_SECRET_KEY: test-secret-key-for-ci
      TOTP_ENCRYPTION_KEY: "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
      EXCHANGE_API_KEY_SECRET: "fedcba9876543210fedcba9876543210fedcba9876543210fedcba9876543210"
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.12', cache: pip }
      - run: pip install -r server/requirements.txt && pip install pytest pytest-asyncio pytest-cov httpx mongomock-motor "fakeredis[aioredis]"
      - run: cd server && pytest tests/e2e/ -v --cov=app --cov-report=xml
      - uses: actions/upload-artifact@v4
        with: { name: e2e-coverage, path: server/coverage.xml }

  coverage:
    runs-on: ubuntu-latest
    needs: [unit-test, integration-test, e2e-test]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/download-artifact@v4
      - run: pip install coverage
      - run: coverage combine */coverage.xml && coverage report --fail-under=80
```

#### cd.yml 신규

```yaml
# .github/workflows/cd.yml
name: CD Pipeline

on:
  push:
    branches: [main]
  workflow_dispatch:
    inputs:
      environment:
        description: 'Deploy target'
        required: true
        type: choice
        options: [staging, production]

jobs:
  build:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write
    outputs:
      image_tag: ${{ steps.meta.outputs.tags }}
    steps:
      - uses: actions/checkout@v4
      - uses: docker/setup-buildx-action@v3
      - uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - id: meta
        uses: docker/metadata-action@v5
        with:
          images: ghcr.io/${{ github.repository }}/server
          tags: |
            type=sha,prefix=
            type=raw,value=latest,enable={{is_default_branch}}
      - uses: docker/build-push-action@v5
        with:
          context: ./server
          push: true
          tags: ${{ steps.meta.outputs.tags }}
          cache-from: type=gha
          cache-to: type=gha,mode=max

  security-scan:
    needs: build
    runs-on: ubuntu-latest
    steps:
      - uses: aquasecurity/trivy-action@master
        with:
          image-ref: ghcr.io/${{ github.repository }}/server:${{ github.sha }}
          format: table
          exit-code: 1
          severity: CRITICAL,HIGH

  migrate:
    needs: security-scan
    runs-on: ubuntu-latest
    environment: staging
    steps:
      - uses: actions/checkout@v4
      - run: |
          # Alembic upgrade (staging DB)
          pip install -r server/requirements.txt
          cd server && alembic upgrade head
        env:
          DATABASE_URL: ${{ secrets.STAGING_DATABASE_URL }}

  deploy-staging:
    needs: migrate
    runs-on: ubuntu-latest
    environment: staging
    steps:
      - uses: actions/checkout@v4
      - name: Deploy to staging
        run: |
          # SSH + docker compose pull & up (rolling)
          ssh ${{ secrets.STAGING_HOST }} << 'EOF'
            cd /opt/cointrader
            docker compose -f docker-compose.prod.yml pull server celery-worker
            docker compose -f docker-compose.prod.yml up -d --no-deps server
            docker compose -f docker-compose.prod.yml up -d --no-deps celery-worker celery-beat
          EOF

  smoke-test:
    needs: deploy-staging
    runs-on: ubuntu-latest
    steps:
      - run: |
          # Health check
          for i in $(seq 1 10); do
            if curl -sf "${{ secrets.STAGING_URL }}/api/v1/health"; then
              echo "Staging healthy"
              exit 0
            fi
            sleep 5
          done
          echo "Staging health check failed"
          exit 1

  deploy-production:
    needs: smoke-test
    runs-on: ubuntu-latest
    environment:
      name: production
      url: ${{ secrets.PRODUCTION_URL }}
    steps:
      - uses: actions/checkout@v4
      - name: Deploy to production
        run: |
          ssh ${{ secrets.PRODUCTION_HOST }} << 'EOF'
            cd /opt/cointrader
            docker compose -f docker-compose.prod.yml pull server celery-worker
            # Rolling: 하나씩 교체
            docker compose -f docker-compose.prod.yml up -d --no-deps --scale server=2 server
            sleep 10
            docker compose -f docker-compose.prod.yml up -d --no-deps server celery-worker celery-beat
          EOF
```

---

### ST8: 모니터링 대시보드 구성 (project-architect)

#### 파일 목록

| 파일 | 역할 | 신규/수정 |
|------|------|-----------|
| `docker-compose.monitoring.yml` | Prometheus + Grafana + Loki 스택 | 신규 |
| `monitoring/prometheus/prometheus.yml` | Prometheus 설정 | 신규 |
| `monitoring/prometheus/alert_rules.yml` | AlertManager 규칙 | 신규 |
| `monitoring/grafana/provisioning/datasources/datasources.yml` | Grafana 데이터소스 자동 설정 | 신규 |
| `monitoring/grafana/provisioning/dashboards/dashboards.yml` | 대시보드 프로비저닝 | 신규 |
| `monitoring/grafana/dashboards/api_overview.json` | API 개요 대시보드 | 신규 |
| `monitoring/grafana/dashboards/exchange_health.json` | 거래소 상태 대시보드 | 신규 |
| `monitoring/grafana/dashboards/ai_trading.json` | AI 매매 대시보드 | 신규 |
| `monitoring/loki/loki-config.yml` | Loki 설정 | 신규 |
| `monitoring/promtail/promtail-config.yml` | Promtail 로그 수집 설정 | 신규 |
| `server/app/core/metrics.py` | 커스텀 메트릭 추가 | 수정 |

#### 커스텀 Prometheus 메트릭

```python
# core/metrics.py 추가 — cointrader_ 접두사로 네임스페이스 충돌 방지
from prometheus_client import Counter, Histogram, Gauge

# 거래소 API
cointrader_exchange_request_duration = Histogram(
    "cointrader_exchange_request_duration_seconds",
    "Exchange API request duration",
    ["exchange", "method"],
    buckets=[0.01, 0.05, 0.1, 0.2, 0.5, 1.0, 2.0, 5.0],
)
cointrader_exchange_request_errors = Counter(
    "cointrader_exchange_request_errors_total",
    "Exchange API errors",
    ["exchange", "error_type"],
)
cointrader_circuit_breaker_state = Gauge(
    "cointrader_circuit_breaker_state",
    "Circuit breaker state (0=closed, 1=half-open, 2=open)",
    ["exchange"],
)

# 주문
cointrader_orders_placed = Counter(
    "cointrader_orders_placed_total",
    "Total orders placed",
    ["exchange", "side", "status"],
)

# AI 매매
cointrader_ai_trade_executions = Counter(
    "cointrader_ai_trade_executions_total",
    "AI trade execution count",
    ["action", "strategy", "result"],  # buy/sell, strategy name, success/fail
)
cointrader_ai_regime_analysis_duration = Histogram(
    "cointrader_ai_regime_analysis_duration_seconds",
    "AI regime analysis duration",
)

# API 응답 (엔드포인트별 상세)
cointrader_api_request_duration = Histogram(
    "cointrader_api_request_duration_seconds",
    "API request latency",
    ["method", "endpoint", "status_code"],
    buckets=[0.01, 0.05, 0.1, 0.2, 0.5, 1.0, 2.0, 5.0],
)

# WebSocket
cointrader_ws_active_connections = Gauge(
    "cointrader_ws_active_connections",
    "Active WebSocket connections",
)
cointrader_ws_subscriptions = Gauge(
    "cointrader_ws_subscriptions_total",
    "Total active WS subscriptions",
    ["channel"],
)
```

#### Grafana 대시보드 패널

**API Overview**:
- Request Rate (req/s by endpoint)
- Response Time (p50/p95/p99)
- Error Rate (4xx/5xx)
- Active Connections

**Exchange Health**:
- Request Duration by Exchange
- Error Rate by Exchange
- Circuit Breaker State (gauge)
- Rate Limiter Remaining Quota

**AI Trading**:
- Trade Execution Count (buy/sell by strategy)
- Regime Distribution (trend/range/transition)
- Win Rate (rolling 7d)
- Drawdown Level

#### 알림 규칙 (AlertManager)

```yaml
# monitoring/prometheus/alert_rules.yml
groups:
  - name: cointrader
    rules:
      - alert: HighErrorRate
        expr: rate(http_requests_total{status=~"5.."}[5m]) > 0.05
        for: 2m
        labels: { severity: critical }
        annotations:
          summary: "High 5xx error rate: {{ $value }}"

      - alert: ExchangeCircuitBreakerOpen
        expr: circuit_breaker_state > 1
        for: 1m
        labels: { severity: warning }
        annotations:
          summary: "Circuit breaker OPEN for {{ $labels.exchange }}"

      - alert: HighAPILatency
        expr: histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m])) > 0.5
        for: 5m
        labels: { severity: warning }
        annotations:
          summary: "API p95 latency > 500ms: {{ $value }}s"

      - alert: WSConnectionsHigh
        expr: ws_active_connections > 900
        for: 2m
        labels: { severity: warning }
        annotations:
          summary: "WS connections approaching limit: {{ $value }}/1000"
```

---

### ST9: 프로덕션 배포 및 무중단 배포 설정 (project-architect) — depends on ST7

#### 파일 목록

| 파일 | 역할 | 신규/수정 |
|------|------|-----------|
| `docker-compose.prod.yml` | 프로덕션 Compose 파일 | 신규 |
| `nginx/nginx.conf` | Reverse proxy + health check | 신규 |
| `nginx/conf.d/cointrader.conf` | 서버 upstream 설정 | 신규 |
| `scripts/deploy.sh` | 배포 스크립트 (rolling update) | 신규 |
| `scripts/rollback.sh` | 롤백 스크립트 | 신규 |
| `scripts/backup.sh` | DB 백업 스크립트 | 신규 |
| `server/.env.example` | 환경변수 템플릿 갱신 | 수정 |

#### docker-compose.prod.yml

```yaml
services:
  nginx:
    image: nginx:1.25-alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx/nginx.conf:/etc/nginx/nginx.conf:ro
      - ./nginx/conf.d:/etc/nginx/conf.d:ro
      - ./nginx/ssl:/etc/nginx/ssl:ro
    depends_on:
      server-1: { condition: service_healthy }
      server-2: { condition: service_healthy }
    restart: unless-stopped

  server-1:
    image: ghcr.io/${GITHUB_REPOSITORY}/server:${IMAGE_TAG:-latest}
    env_file: .env.prod
    healthcheck:
      test: ["CMD", "python", "-c", "import httpx; httpx.get('http://localhost:8000/api/v1/health').raise_for_status()"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 15s
    deploy:
      resources:
        limits: { cpus: '2', memory: 2G }
        reservations: { cpus: '1', memory: 1G }
    restart: unless-stopped

  server-2:
    extends:
      service: server-1

  celery-worker:
    image: ghcr.io/${GITHUB_REPOSITORY}/server:${IMAGE_TAG:-latest}
    command: >
      celery -A tasks.celery_app.celery_app worker -l info -c 4 -Q ai,scraper,default
    env_file: .env.prod
    deploy:
      resources:
        limits: { cpus: '2', memory: 2G }
    restart: unless-stopped

  celery-beat:
    image: ghcr.io/${GITHUB_REPOSITORY}/server:${IMAGE_TAG:-latest}
    command: >
      celery -A tasks.celery_app.celery_app beat -l info --scheduler celery.beat.PersistentScheduler
    env_file: .env.prod
    restart: unless-stopped

  postgres:
    image: postgres:16-alpine
    env_file: .env.prod
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./backups/postgres:/backups
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U cointrader"]
      interval: 10s
    deploy:
      resources:
        limits: { memory: 4G }
    restart: unless-stopped

  mongodb:
    image: mongo:7
    env_file: .env.prod
    volumes:
      - mongodb_data:/data/db
      - ./backups/mongodb:/backups
    healthcheck:
      test: ["CMD", "mongosh", "--eval", "db.adminCommand('ping')"]
      interval: 10s
    restart: unless-stopped

  redis:
    image: redis:7-alpine
    command: redis-server --appendonly yes --maxmemory 512mb --maxmemory-policy allkeys-lru
    volumes:
      - redis_data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
    restart: unless-stopped
```

#### Nginx 설정

```nginx
# nginx/conf.d/cointrader.conf
upstream cointrader_api {
    server server-1:8000;
    server server-2:8000;
}

server {
    listen 80;
    server_name api.cointrader.io;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name api.cointrader.io;

    ssl_certificate /etc/nginx/ssl/fullchain.pem;
    ssl_certificate_key /etc/nginx/ssl/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;

    # API
    location /api/ {
        proxy_pass http://cointrader_api;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # WebSocket
    location /ws/ {
        proxy_pass http://cointrader_api;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_read_timeout 300s;
    }

    # Metrics (내부 접근만)
    location /metrics {
        deny all;  # 외부 차단, Prometheus는 Docker 네트워크로 접근
    }
}
```

#### Rolling Update 스크립트

```bash
#!/bin/bash
# scripts/deploy.sh
set -euo pipefail

IMAGE_TAG=${1:-latest}
COMPOSE_FILE="docker-compose.prod.yml"

echo "=== Deploying image: ${IMAGE_TAG} ==="

# 1. Pull new image
IMAGE_TAG=$IMAGE_TAG docker compose -f $COMPOSE_FILE pull server-1 server-2 celery-worker

# 2. Rolling update: server-1 먼저
echo "--- Updating server-1 ---"
IMAGE_TAG=$IMAGE_TAG docker compose -f $COMPOSE_FILE up -d --no-deps server-1
sleep 10

# Health check server-1
for i in $(seq 1 12); do
    if docker compose -f $COMPOSE_FILE exec server-1 python -c "import httpx; httpx.get('http://localhost:8000/api/v1/health').raise_for_status()" 2>/dev/null; then
        echo "server-1 healthy"
        break
    fi
    [ $i -eq 12 ] && { echo "server-1 failed health check"; exit 1; }
    sleep 5
done

# 3. server-2 업데이트
echo "--- Updating server-2 ---"
IMAGE_TAG=$IMAGE_TAG docker compose -f $COMPOSE_FILE up -d --no-deps server-2
sleep 10

# 4. Celery worker/beat 업데이트
echo "--- Updating celery ---"
IMAGE_TAG=$IMAGE_TAG docker compose -f $COMPOSE_FILE up -d --no-deps celery-worker celery-beat

# 5. Nginx reload (upstream 갱신)
docker compose -f $COMPOSE_FILE exec nginx nginx -s reload

echo "=== Deploy complete: ${IMAGE_TAG} ==="
```

#### 롤백 스크립트

```bash
#!/bin/bash
# scripts/rollback.sh
set -euo pipefail

PREVIOUS_TAG=${1:?"Usage: rollback.sh <previous_image_tag>"}
echo "=== Rolling back to: ${PREVIOUS_TAG} ==="

IMAGE_TAG=$PREVIOUS_TAG bash scripts/deploy.sh $PREVIOUS_TAG
```

---

### ST10: 보안 강화 및 감사 로깅 구현 (code-review-expert) — depends on ST7

#### 파일 목록

| 파일 | 역할 | 신규/수정 |
|------|------|-----------|
| `server/app/middleware/security_headers.py` | 보안 헤더 미들웨어 | 신규 |
| `server/app/core/config.py` | 보안 관련 설정 추가 | 수정 |
| `.github/workflows/security.yml` | 보안 스캔 워크플로우 | 신규 |
| `server/app/api/v1/app_version.py` | 앱 버전 엔드포인트 | 신규 |

#### 보안 헤더 미들웨어

```python
# middleware/security_headers.py
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        return response
```

#### 보안 스캔 워크플로우

```yaml
# .github/workflows/security.yml
name: Security Scan

on:
  schedule:
    - cron: '0 6 * * 1'  # 매주 월요일 06:00 UTC
  push:
    branches: [main]
    paths: ['server/requirements.txt', 'server/pyproject.toml']

jobs:
  dependency-scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: pip install safety
      - run: safety check -r server/requirements.txt

  container-scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: docker/build-push-action@v5
        with: { context: ./server, push: false, tags: scan-target }
      - uses: aquasecurity/trivy-action@master
        with:
          image-ref: scan-target
          format: sarif
          output: trivy-results.sarif
          severity: CRITICAL,HIGH
      - uses: github/codeql-action/upload-sarif@v3
        with: { sarif_file: trivy-results.sarif }

  secret-scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with: { fetch-depth: 0 }
      - uses: trufflesecurity/trufflehog@main
        with: { extra_args: --only-verified }
```

#### 앱 버전 엔드포인트

```python
# api/v1/app_version.py
@router.get("/app-version")
async def get_app_version():
    return {
        "server_version": "0.1.0",
        "min_client_version": "1.0.0",
        "force_update": False,
        "update_message": None,
    }
```

#### 보안 체크리스트

- [x] JWT Secret 환경변수 (production에서 반드시 변경)
- [x] CORS 화이트리스트 (명시적 origins)
- [x] Rate Limiting (미들웨어)
- [x] SQL Injection 방지 (SQLAlchemy ORM)
- [x] AES-256-GCM 암호화 (거래소 API 키, TOTP 시크릿)
- [x] bcrypt 비밀번호 해싱
- [ ] 보안 헤더 미들웨어 추가 (ST10에서 구현)
- [ ] HTTPS/WSS 강제 (Nginx TLS, HSTS)
- [ ] 의존성 보안 스캔 (safety, trivy)
- [ ] 시크릿 스캔 (trufflehog)
- [ ] API 키 마스킹 로그 (structlog 필터)

---

## 4. 신규 의존성

### 서버 (pyproject.toml)

| 패키지 | 용도 | 그룹 |
|--------|------|------|
| `pytest-benchmark>=4.0` | 성능 벤치마크 | dev |
| `locust>=2.20` | HTTP 부하 테스트 | dev |
| `locust-plugins>=4.0` | WebsocketUser (WS 동시접속 테스트) | dev |

### pytest 설정 변경 (pyproject.toml)

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "session"
asyncio_default_test_loop_scope = "session"
testpaths = ["tests"]
markers = [
    "e2e: end-to-end tests requiring real DB/Redis (deselect with '-m not e2e')",
    "benchmark: performance benchmark tests (deselect with '-m not benchmark')",
]
```

### structlog 테스트 환경 설정

```python
# tests/conftest.py 상단에 추가 — 테스트 시 로그 노이즈 최소화
import structlog
structlog.configure(
    processors=[structlog.dev.ConsoleRenderer()],
    wrapper_class=structlog.make_filtering_bound_logger(logging.WARNING),
)
```

### 인프라

| 도구 | 버전 | 용도 |
|------|------|------|
| Prometheus | 2.x | 메트릭 수집 |
| Grafana | 10.x | 대시보드 시각화 |
| Loki | 2.x | 로그 수집 |
| Promtail | 2.x | 로그 전송 |
| AlertManager | 0.27 | 알림 라우팅 |
| Nginx | 1.25 | Reverse proxy |

---

## 5. 구현 순서

```
Phase 1: 기반 구조 (ST7 + ST8 병렬)
  ST7: CI/CD 파이프라인 확장 — ci.yml 분리, cd.yml 신규
  ST8: 모니터링 스택 — docker-compose.monitoring.yml, 커스텀 메트릭

Phase 2: E2E 테스트 (ST1~ST5 병렬)
  ST1: 인증 흐름 E2E — conftest.py 공통 픽스처 포함
  ST2: 거래소 연동 E2E — MockProvider 확장
  ST3: AI 매매 E2E — OpenAI Mock
  ST4: 포트폴리오 E2E
  ST5: WebSocket E2E

Phase 3: 성능 + 보안 (ST6, ST10 병렬)
  ST6: 성능 테스트 — pytest-benchmark + locust
  ST10: 보안 강화 — 보안 헤더, 스캔 워크플로우

Phase 4: 배포 (ST9 — ST7 완료 후)
  ST9: 프로덕션 배포 — docker-compose.prod.yml, nginx, 배포 스크립트
```

---

## 6. 예상 파일 수

| 카테고리 | 신규 | 수정 | 합계 |
|----------|------|------|------|
| E2E 테스트 (ST1~ST5) | 9 | 1 | 10 |
| 성능 테스트 (ST6) | 5 | 0 | 5 |
| CI/CD (ST7) | 2 | 3 | 5 |
| 모니터링 (ST8) | 10 | 1 | 11 |
| 배포 (ST9) | 6 | 1 | 7 |
| 보안 (ST10) | 3 | 1 | 4 |
| **합계** | **35** | **7** | **42** |

---

## 7. 테스트 전략 요약

| 구분 | 도구 | 실행 환경 | CI 포함 |
|------|------|-----------|---------|
| 단위 테스트 | pytest + mongomock + fakeredis | 로컬/CI | 항상 |
| 통합 테스트 | pytest + mock services + httpx | 로컬/CI | 항상 |
| E2E 테스트 | pytest + httpx + 실 DB/Redis | CI (services) | 항상 |
| 성능 벤치마크 | pytest-benchmark | CI | 항상 (regression) |
| 부하 테스트 | locust | CI (nightly) | nightly |
| 보안 스캔 | trivy + safety + trufflehog | CI | 주간/push |

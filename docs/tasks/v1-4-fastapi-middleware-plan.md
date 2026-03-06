# v1-4 FastAPI 기본 프로젝트 구조 및 미들웨어 구성 - 설계서

## 1. 개요

FastAPI 앱 초기화, 미들웨어 체인(CORS, Correlation ID, 요청 로깅, 에러 처리), 헬스체크 엔드포인트, 의존성 주입 설정, Prometheus 메트릭, Sentry 통합을 구성한다.

**의존성**: v1-1(프로젝트 인프라), v1-3(Redis 캐시/Pub/Sub) 완료.

**현재 상태**: 전체 구현 완료. Correlation ID 미들웨어(`correlation_id.py`), 글로벌 에러 핸들러(`error_handler.py`+`schemas/error.py`), main.py 미들웨어 체인 통합, 통합 테스트 34케이스(34/34 통과) 구현됨. 코드 리뷰 WARNING 2건(로그 인젝션 방어, 민감정보 마스킹) 수정 완료.

---

## 2. 구현 현황표

| ST# | 서브태스크 | 상태 | 담당 | 비고 |
|-----|-----------|------|------|------|
| 1 | FastAPI 앱 인스턴스 및 Lifespan | **완료** | project-architect | `main.py` lifespan, PG/MongoDB/Redis 초기화 |
| 2 | CORS 미들웨어 설정 | **수정** | code-architect | `expose_headers`에 `X-Correlation-ID` 추가 |
| 3 | 구조화된 로깅 (structlog + JSON) | **완료** | python-backend-expert | `main.py` configure_logging() |
| 4 | Correlation ID 미들웨어 | **신규** | python-backend-expert | `middleware/correlation_id.py` 생성 |
| 5 | 글로벌 에러 핸들러 | **신규** | python-backend-expert | `middleware/error_handler.py` 생성 |
| 6 | 헬스체크 엔드포인트 | **완료** | python-backend-expert | `api/v1/health.py` PG/MongoDB/Redis 병렬 체크 |
| 7 | 의존성 주입 설정 | **수정** | code-architect | `CurrentUser` placeholder 추가 |
| 8 | pydantic-settings + Sentry | **완료** | project-architect | `config.py` Settings + `main.py` sentry_sdk.init |
| 9 | Prometheus 메트릭 | **완료** | python-backend-expert | `metrics.py` instrumentator + `/metrics` |
| 10 | 통합 테스트 + 코드 리뷰 | **신규** | e2e-test-expert, code-review-expert | 전체 미들웨어 체인 검증 |

---

## 3. 시스템 아키텍처 - 요청 처리 파이프라인

```
Client Request
    │
    ▼
┌─────────────────────────────────────────────────┐
│  1. CORSMiddleware (가장 외부)                    │
│     - Preflight OPTIONS 처리                     │
│     - Access-Control-* 헤더 설정                  │
├─────────────────────────────────────────────────┤
│  2. CorrelationIdMiddleware                      │
│     - X-Correlation-ID 헤더 파싱 or UUID4 생성    │
│     - structlog contextvars에 바인딩             │
│     - 응답 헤더에 X-Correlation-ID 추가           │
├─────────────────────────────────────────────────┤
│  3. RateLimitMiddleware                          │
│     - IP 기반 Token Bucket 체크                   │
│     - 429 Too Many Requests 반환                 │
│     - X-RateLimit-Remaining 헤더                 │
├─────────────────────────────────────────────────┤
│  4. Prometheus Instrumentator                    │
│     - 요청/응답 메트릭 수집                       │
│     - /metrics, /health 제외                     │
├─────────────────────────────────────────────────┤
│  5. Global Error Handlers (exception_handler)    │
│     - RequestValidationError → 422               │
│     - HTTPException → 4xx/5xx                    │
│     - Exception → 500 (Sentry 전송)              │
│     - 통일 에러 응답 포맷                         │
├─────────────────────────────────────────────────┤
│  6. Router Handlers                              │
│     - Depends: DbSession, RedisClient, etc.      │
│     - Business Logic                             │
└─────────────────────────────────────────────────┘
    │
    ▼
Client Response (+ X-Correlation-ID, X-RateLimit-Remaining)
```

### 미들웨어 등록 순서 (main.py)

> FastAPI/Starlette에서 `add_middleware`는 **후입선출(LIFO)** — 마지막 등록이 가장 외부에서 실행.

```python
# main.py 등록 순서 (위에서 아래로)
# 1. Prometheus (가장 내부에서 실행)
instrumentator.instrument(app).expose(app, endpoint="/metrics")

# 2. RateLimitMiddleware
app.add_middleware(RateLimitMiddleware)

# 3. CorrelationIdMiddleware
app.add_middleware(CorrelationIdMiddleware)

# 4. CORSMiddleware (가장 외부에서 실행 — 마지막 등록)
app.add_middleware(CORSMiddleware, ...)
```

---

## 4. Correlation ID 미들웨어 설계 (ST4 - 신규)

### 4-1. 파일: `server/app/middleware/correlation_id.py`

```python
"""Correlation ID 미들웨어 — 요청 추적용 고유 ID 생성 및 전파.

흐름: 요청 헤더 → contextvars → structlog → 응답 헤더
"""
from __future__ import annotations

import uuid
from contextvars import ContextVar

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

CORRELATION_ID_HEADER = "X-Correlation-ID"

# contextvars — 비동기 안전
correlation_id_ctx: ContextVar[str] = ContextVar("correlation_id", default="")


def get_correlation_id() -> str:
    """현재 요청의 Correlation ID 반환 (미들웨어 외부에서 사용)."""
    return correlation_id_ctx.get()


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """요청마다 Correlation ID를 생성/전파하는 미들웨어.

    1. 요청 헤더 X-Correlation-ID가 있으면 사용, 없으면 UUID4 생성
    2. structlog contextvars에 바인딩 → 모든 로그에 자동 포함
    3. 응답 헤더 X-Correlation-ID에 포함
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        cid = request.headers.get(CORRELATION_ID_HEADER) or str(uuid.uuid4())

        # contextvars에 저장
        token = correlation_id_ctx.set(cid)

        # structlog contextvars에 바인딩
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            correlation_id=cid,
            method=request.method,
            path=request.url.path,
        )

        try:
            response = await call_next(request)
            response.headers[CORRELATION_ID_HEADER] = cid
            return response
        finally:
            correlation_id_ctx.reset(token)
            structlog.contextvars.clear_contextvars()
```

### 4-2. Correlation ID 전파 구조

```
Client → [X-Correlation-ID: abc-123] → Request Header
    │
    ▼
CorrelationIdMiddleware
    ├─ contextvars.correlation_id = "abc-123"
    ├─ structlog.bind_contextvars(correlation_id="abc-123")
    │
    ▼
모든 structlog 로그 자동 포함:
    {"correlation_id": "abc-123", "event": "...", ...}
    │
    ▼
에러 핸들러:
    {"error": {"correlation_id": "abc-123", ...}}
    │
    ▼
Response Header: X-Correlation-ID: abc-123
```

---

## 5. 글로벌 에러 핸들러 설계 (ST5 - 신규)

### 5-1. 통일 에러 응답 스키마

```python
# server/app/schemas/error.py

class ErrorDetail(BaseModel):
    """개별 검증 에러 상세."""
    field: str
    message: str
    type: str  # e.g., "value_error", "missing"

class ErrorResponse(BaseModel):
    """통일 에러 응답 포맷."""
    error: ErrorBody

class ErrorBody(BaseModel):
    code: str           # e.g., "VALIDATION_ERROR", "NOT_FOUND", "INTERNAL_ERROR"
    message: str        # 사람이 읽을 수 있는 메시지
    details: list[ErrorDetail] | None = None  # 검증 에러 시 상세 목록
    correlation_id: str | None = None         # 요청 추적 ID
```

### 5-2. 에러 코드 매핑

| HTTP Status | 에러 코드 | 발생 원인 |
|-------------|----------|----------|
| 400 | `BAD_REQUEST` | 잘못된 요청 파라미터 |
| 401 | `UNAUTHORIZED` | 인증 실패, 토큰 만료 |
| 403 | `FORBIDDEN` | 권한 부족 |
| 404 | `NOT_FOUND` | 리소스 없음 |
| 409 | `CONFLICT` | 중복 리소스 |
| 422 | `VALIDATION_ERROR` | Pydantic 검증 실패 |
| 429 | `RATE_LIMIT_EXCEEDED` | Rate Limit 초과 |
| 500 | `INTERNAL_ERROR` | 서버 내부 에러 |

### 5-3. 파일: `server/app/middleware/error_handler.py`

```python
"""글로벌 에러 핸들러 — 모든 예외를 통일 에러 응답으로 변환.

FastAPI의 exception_handler 데코레이터를 사용하여 등록.
미들웨어가 아닌 exception_handler로 구현하여 Starlette 미들웨어 체인과 분리.
"""
from __future__ import annotations

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse

from app.middleware.correlation_id import get_correlation_id
from app.schemas.error import ErrorBody, ErrorDetail

logger = structlog.get_logger(__name__)


def register_error_handlers(app: FastAPI) -> None:
    """앱에 글로벌 에러 핸들러 등록."""

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        details = [
            ErrorDetail(
                field=".".join(str(loc) for loc in err["loc"]),
                message=err["msg"],
                type=err["type"],
            )
            for err in exc.errors()
        ]
        body = ErrorBody(
            code="VALIDATION_ERROR",
            message="Request validation failed",
            details=details,
            correlation_id=get_correlation_id(),
        )
        logger.warning("validation_error", errors=exc.errors())
        return JSONResponse(
            status_code=422,
            content={"error": body.model_dump(exclude_none=True)},
        )

    @app.exception_handler(HTTPException)
    async def http_error_handler(
        request: Request, exc: HTTPException
    ) -> JSONResponse:
        code_map = {
            400: "BAD_REQUEST",
            401: "UNAUTHORIZED",
            403: "FORBIDDEN",
            404: "NOT_FOUND",
            409: "CONFLICT",
            429: "RATE_LIMIT_EXCEEDED",
        }
        body = ErrorBody(
            code=code_map.get(exc.status_code, f"HTTP_{exc.status_code}"),
            message=str(exc.detail),
            correlation_id=get_correlation_id(),
        )
        if exc.status_code >= 500:
            logger.error("http_error", status=exc.status_code, detail=exc.detail)
        else:
            logger.warning("http_error", status=exc.status_code, detail=exc.detail)
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": body.model_dump(exclude_none=True)},
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        logger.exception("unhandled_error", error=str(exc))
        # Sentry가 활성화되어 있으면 자동 캡처됨
        body = ErrorBody(
            code="INTERNAL_ERROR",
            message="An unexpected error occurred",
            correlation_id=get_correlation_id(),
        )
        return JSONResponse(
            status_code=500,
            content={"error": body.model_dump(exclude_none=True)},
        )
```

---

## 6. CORS 미들웨어 수정 (ST2 - 수정)

### 현재 구현 (`main.py`)
```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

### 수정 사항

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Correlation-ID", "X-RateLimit-Remaining", "X-RateLimit-Retry-After-Ms"],
)
```

**변경 이유**: 클라이언트(Flutter Web)에서 커스텀 응답 헤더를 읽으려면 `expose_headers`에 명시 필요.

### CORS 설정 결정사항 (code-architect)

| 항목 | 현재 | 결정 | 근거 |
|------|------|------|------|
| `allow_methods` | `["*"]` | **유지** | REST API는 모든 메서드 사용, 제한 실익 없음 |
| `allow_headers` | `["*"]` | **유지** | Swagger UI 등 개발 도구 호환 필요 |
| `expose_headers` | 미설정 | **추가** | 클라이언트(Flutter Web)가 커스텀 헤더 읽기 위해 필수 |
| `allow_origins` | env 기반 | **유지** | `settings.cors_origins_list` 콤마 파싱 이미 구현됨 |

> **프로덕션 보안 강화 고려**: `allow_headers`를 `["Authorization", "Content-Type", "X-Correlation-ID"]`로 제한 가능하나, Swagger UI 지원을 위해 현 단계에서는 `["*"]` 유지. 향후 prod 환경 분기 시 검토.

---

## 7. 의존성 주입 수정 (ST7 - 수정)

### 현재 구현 (`deps.py`)
```python
# 이미 구현됨
DbSession = Annotated[AsyncSession, Depends(get_db)]
RedisClient = Annotated[Redis, Depends(get_redis)]
PubSubRedisClient = Annotated[Redis, Depends(get_pubsub_redis)]
ApiRateLimiter = Annotated[APIRateLimiter, Depends(get_api_rate_limiter)]
ExchangeLimiter = Annotated[ExchangeRateLimiter, Depends(get_exchange_rate_limiter)]
```

### 추가 사항 (code-architect)

#### 1. MongoDB 의존성 추가

Beanie는 전역 초기화 방식이지만, 서비스 레이어 DI 일관성 유지를 위해 motor `AsyncIOMotorDatabase` getter 추가.

```python
# server/app/core/mongodb.py — init_mongodb() 내부에 _mongodb 할당 후 getter 추가

from motor.motor_asyncio import AsyncIOMotorDatabase

_mongodb: AsyncIOMotorDatabase | None = None  # init_mongodb()에서 할당


def get_mongodb() -> AsyncIOMotorDatabase:
    """MongoDB 데이터베이스 인스턴스 반환."""
    if _mongodb is None:
        raise RuntimeError("MongoDB not initialized. Call init_mongodb first.")
    return _mongodb
```

```python
# server/app/core/deps.py — MongoDb 타입 별칭 추가

from motor.motor_asyncio import AsyncIOMotorDatabase
from app.core.mongodb import get_mongodb

MongoDb = Annotated[AsyncIOMotorDatabase, Depends(get_mongodb)]
```

#### 2. Settings 의존성 추가

라우터 핸들러에서 settings를 테스트 가능한 방식으로 주입하기 위한 의존성.

```python
# server/app/core/deps.py — AppSettings 타입 별칭 추가

from app.core.config import Settings, settings as _settings

def get_settings() -> Settings:
    return _settings

AppSettings = Annotated[Settings, Depends(get_settings)]
```

#### 3. Auth 의존성 (v1-5 예약)

```python
# server/app/core/deps.py -- 주석 상태 유지, v1-5에서 활성화
# CurrentUser = Annotated[User, Depends(get_current_user)]
# CurrentUserOptional = Annotated[User | None, Depends(get_current_user_optional)]
```

**결정**: Auth 의존성은 v1-5 auth 모듈에서 구현 예정이므로 현 단계에서는 주석 유지. `deps.py`의 기존 주석이 이미 올바른 형태.

#### 4. deps.py 공개 API (__all__)

```python
# server/app/core/deps.py

__all__ = [
    "DbSession",        # PostgreSQL AsyncSession
    "MongoDb",          # MongoDB AsyncIOMotorDatabase (신규)
    "RedisClient",      # Redis 일반 클라이언트
    "PubSubRedisClient", # Redis Pub/Sub 전용
    "ApiRateLimiter",   # API Rate Limiter
    "ExchangeLimiter",  # Exchange Rate Limiter
    "AppSettings",      # pydantic Settings (신규)
    # v1-5 auth 구현 시 활성화:
    # "CurrentUser",
    # "CurrentUserOptional",
]
```

### 의존성 주입 전체 맵

```
                    ┌─────────────────────────────────────────┐
                    │              Router Handler              │
                    └──────┬──────┬──────┬──────┬──────┬──────┘
                           │      │      │      │      │
              ┌────────────▼──┐ ┌─▼────┐ │  ┌───▼───┐  │
              │   DbSession   │ │Redis │ │  │ApiRate│  │
              │ (AsyncSession) │ │Client│ │  │Limiter│  │
              └───────┬───────┘ └──┬───┘ │  └───┬───┘  │
                      │            │     │      │      │
              ┌───────▼───────┐    │     │      │  ┌───▼────────┐
              │   get_db()    │    │     │      │  │ExchangeRate│
              │ (yield session)│    │     │      │  │  Limiter   │
              └───────────────┘    │     │      │  └────────────┘
                                   │     │      │
                         ┌─────────▼──┐  │  ┌───▼──────────┐
                         │ get_redis()│  │  │get_api_rate  │
                         │(singleton) │  │  │  _limiter()  │
                         └────────────┘  │  └──────────────┘
                                         │
                               ┌─────────▼──────────┐
                               │  get_pubsub_redis() │
                               │    (singleton)      │
                               └─────────────────────┘

  [v1-5 추가 예정]
  CurrentUser = Annotated[User, Depends(get_current_user)]
  CurrentUserOptional = Annotated[User | None, Depends(get_current_user_optional)]
```

---

## 8. main.py 수정 사항 (ST1 - 수정)

### 현재 main.py 구조
```python
# Sentry 초기화
# configure_logging()
# lifespan: init_db, init_mongodb, init_redis
# FastAPI 인스턴스
# CORS 미들웨어
# v1 라우터
# Prometheus instrumentator
```

### 수정 후 main.py 구조
```python
# Sentry 초기화 (기존 유지)
# configure_logging() (기존 유지)
# lifespan (기존 유지)

# FastAPI 인스턴스 (기존 유지)

# 글로벌 에러 핸들러 등록 (신규)
register_error_handlers(app)

# 미들웨어 등록 (순서 중요 — LIFO)
# 1. Prometheus instrumentator (기존 유지, 가장 내부)
instrumentator.instrument(app).expose(app, endpoint="/metrics")

# 2. RateLimitMiddleware (기존 유지)
app.add_middleware(RateLimitMiddleware)

# 3. CorrelationIdMiddleware (신규)
app.add_middleware(CorrelationIdMiddleware)

# 4. CORSMiddleware (기존 수정 — expose_headers 추가)
app.add_middleware(CORSMiddleware, ...)

# v1 라우터 (기존 유지)
app.include_router(v1_router, prefix="/api/v1")
```

---

## 9. 구현 파일 목록 (서브태스크별)

| ST# | 상태 | 파일 | 작업 |
|-----|------|------|------|
| 1 | 완료 | `server/app/main.py` | 변경 불필요 (lifespan) |
| 2 | 수정 | `server/app/main.py` | CORS `expose_headers` 추가 |
| 3 | 완료 | `server/app/main.py` | 변경 불필요 (configure_logging) |
| 4 | **신규** | `server/app/middleware/correlation_id.py` | CorrelationIdMiddleware 생성 |
| 4 | 수정 | `server/app/main.py` | CorrelationIdMiddleware 등록 |
| 5 | **신규** | `server/app/schemas/error.py` | ErrorResponse, ErrorBody, ErrorDetail 스키마 |
| 5 | **신규** | `server/app/middleware/error_handler.py` | register_error_handlers() 함수 |
| 5 | 수정 | `server/app/main.py` | register_error_handlers(app) 호출 |
| 6 | 완료 | `server/app/api/v1/health.py` | 변경 불필요 |
| 7 | **수정** | `server/app/core/deps.py` | MongoDb, AppSettings 타입 별칭 추가, CurrentUser 주석 유지 |
| 7 | **수정** | `server/app/core/mongodb.py` | get_mongodb() getter 추가 |
| 8 | 완료 | `server/app/core/config.py` | 변경 불필요 |
| 9 | 완료 | `server/app/core/metrics.py` | 변경 불필요 |
| 10 | **신규** | `server/tests/test_middleware_chain.py` | 미들웨어 통합 테스트 |
| 10 | **신규** | `server/tests/test_error_handler.py` | 에러 핸들러 테스트 |
| 10 | **신규** | `server/tests/test_correlation_id.py` | Correlation ID 테스트 |

---

## 10. 모듈 의존 관계

```
app/middleware/correlation_id.py  ← structlog (외부), contextvars (stdlib)
app/schemas/error.py              ← pydantic (외부)
app/middleware/error_handler.py   ← app/middleware/correlation_id.py (get_correlation_id)
                                  ← app/schemas/error.py (ErrorBody, ErrorDetail)
app/middleware/rate_limit.py      ← app/core/rate_limiter.py + redis.py (기존)
app/core/deps.py                  ← app/core/database.py + redis.py + rate_limiter.py (기존)
app/core/config.py                ← pydantic-settings (기존)
app/core/metrics.py               ← prometheus-fastapi-instrumentator (기존)
app/api/v1/health.py              ← app/core/database.py + mongodb.py + redis.py (기존)

app/main.py
  ├─ app/core/config.py
  ├─ app/core/database.py (init_db)
  ├─ app/core/mongodb.py (init_mongodb, close_mongodb)
  ├─ app/core/redis.py (init_redis, close_redis)
  ├─ app/core/metrics.py (instrumentator)
  ├─ app/middleware/correlation_id.py (CorrelationIdMiddleware) ← 신규
  ├─ app/middleware/error_handler.py (register_error_handlers) ← 신규
  ├─ app/middleware/rate_limit.py (RateLimitMiddleware) ← 기존 (등록 위치 조정)
  └─ app/api/v1/ (v1_router)
```

---

## 11. 주요 결정사항

| 결정 | 선택 | 근거 |
|------|------|------|
| Correlation ID 구현 방식 | `BaseHTTPMiddleware` + `contextvars` | structlog.contextvars와 자연스럽게 통합, 비동기 안전 |
| 에러 핸들러 구현 방식 | `exception_handler` (미들웨어 X) | FastAPI 공식 패턴, 미들웨어 체인과 분리되어 단순 |
| 에러 응답 포맷 | `{"error": {"code", "message", "details", "correlation_id"}}` | RFC 7807 간소화, Rate Limiter 기존 포맷과 일관성 |
| Auth 의존성 시점 | v1-5에서 구현 | auth 모듈 없이 placeholder만 유지하면 import 에러 발생 |
| 미들웨어 순서 | CORS → CorrelationId → RateLimit → Prometheus | CORS preflight 우선, ID 생성 후 Rate Limit에서도 사용 가능 |
| Correlation ID 헤더 | `X-Correlation-ID` | 업계 표준, Sentry/Datadog 등 도구 호환 |
| Correlation ID 외부 수용 | 허용 (클라이언트 전달 시 재사용) | 분산 추적 시 유용, 마이크로서비스 전환 대비 |

---

## 12. 빌드 시퀀스

```
Phase A (이미 완료 — 변경 불필요):
  ├─ ST1: FastAPI 앱 인스턴스 + Lifespan ✅
  ├─ ST3: structlog 구조화 로깅 ✅
  ├─ ST6: 헬스체크 엔드포인트 ✅
  ├─ ST8: pydantic-settings + Sentry ✅
  └─ ST9: Prometheus 메트릭 ✅

Phase B (병렬 — 신규 구현):
  ┌─ ST4: Correlation ID 미들웨어 (correlation_id.py)
  └─ ST5-스키마: 에러 응답 스키마 (schemas/error.py)

Phase C (ST4 + ST5-스키마 완료 후):
  └─ ST5-핸들러: 글로벌 에러 핸들러 (error_handler.py)

Phase D (ST4 + ST5 완료 후 — main.py 수정):
  ├─ ST2: CORS expose_headers 수정
  └─ ST1-수정: main.py에 미들웨어/에러핸들러 등록

Phase E (전체 완료 후):
  └─ ST10: 통합 테스트 + 코드 리뷰
```

**크리티컬 패스**: ST4 → ST5 → main.py 수정 → ST10
**최대 병렬도**: Phase B에서 ST4 + ST5-스키마 동시 진행

---

## 13. 통합 테스트 범위 (ST10)

### 13-1. test_correlation_id.py

| 테스트 케이스 | 검증 내용 |
|-------------|----------|
| 요청 시 X-Correlation-ID 자동 생성 | 응답 헤더에 UUID 포맷 포함 |
| 클라이언트 제공 ID 전파 | 요청 헤더 값이 응답에 그대로 반환 |
| 에러 응답에 correlation_id 포함 | 422/500 에러 바디에 ID 포함 |
| 로그에 correlation_id 포함 | structlog 출력에 ID 필드 존재 |

### 13-2. test_error_handler.py

| 테스트 케이스 | 검증 내용 |
|-------------|----------|
| 422 Validation Error | 통일 포맷, details 배열 포함 |
| 404 Not Found | `{"error": {"code": "NOT_FOUND", ...}}` |
| 500 Internal Error | 스택트레이스 미노출, 일반 메시지 |
| HTTPException 전파 | status_code 매핑 정확성 |

### 13-3. test_middleware_chain.py

| 테스트 케이스 | 검증 내용 |
|-------------|----------|
| CORS Preflight | OPTIONS 응답에 Access-Control-* 헤더 |
| 미들웨어 순서 검증 | Correlation ID가 에러 응답에 포함 (에러 핸들러보다 먼저 실행) |
| Rate Limit 응답 포맷 | 429 응답이 통일 에러 포맷 준수 |
| 헬스체크 정상 응답 | GET /api/v1/health → 200 |
| Prometheus /metrics | GET /metrics → 200 |

---

## 14. 환경별 설정 차이

| 설정 | dev | staging | prod |
|------|-----|---------|------|
| `DEBUG` | `true` | `false` | `false` |
| `LOG_LEVEL` | `DEBUG` | `INFO` | `INFO` |
| structlog 렌더러 | ConsoleRenderer | JSONRenderer | JSONRenderer |
| `/docs`, `/redoc` | 활성화 | 비활성화 | 비활성화 |
| SENTRY_DSN | 빈 문자열 | 설정 | 설정 |
| CORS_ORIGINS | `http://localhost:3000` | 스테이징 도메인 | 프로덕션 도메인 |
| `traces_sample_rate` | 0.1 | 0.1 | 0.1 |

---

## ADR-004: Correlation ID 미들웨어 구현 방식

### 상태: 승인됨
### 맥락
분산 요청 추적을 위해 모든 요청에 고유 ID를 부여하고 로그/응답에 포함해야 한다.
### 선택지
1. Starlette `BaseHTTPMiddleware` + `contextvars`
2. Pure ASGI 미들웨어 (더 성능적이나 복잡)
3. `asgi-correlation-id` 외부 패키지
### 결정
옵션 1 선택. `structlog.contextvars`와 자연스럽게 통합되고, 프로젝트 규모에 적합한 단순성. Pure ASGI는 성능 차이가 미미하고 코드 복잡도가 높음.
### 영향
`middleware/correlation_id.py` 신규 파일, `main.py`에 미들웨어 등록 추가.

## ADR-005: 글로벌 에러 핸들러 구현 방식

### 상태: 승인됨
### 맥락
모든 API 에러 응답을 통일 포맷으로 변환하여 클라이언트 에러 처리를 단순화해야 한다.
### 선택지
1. `exception_handler` 데코레이터 (FastAPI 공식 방식)
2. `BaseHTTPMiddleware`로 try/except 래핑
3. 커스텀 Router 클래스 오버라이드
### 결정
옵션 1 선택. FastAPI 공식 패턴, 미들웨어 체인과 독립적, 예외 타입별 세분화 가능. Rate Limiter 미들웨어의 기존 429 응답 포맷은 유지 (미들웨어에서 직접 반환하므로 exception_handler 경유하지 않음).
### 영향
`middleware/error_handler.py`, `schemas/error.py` 신규 파일. Rate Limiter 429 응답은 기존 포맷 유지 (이미 통일 포맷과 호환).

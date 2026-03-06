# v1-1 프로젝트 인프라 및 개발 환경 설정 - 설계서

## 1. 개요

모노레포 구조 정립, Docker Compose 환경(PostgreSQL 16, MongoDB 7, Redis 7), FastAPI/Flutter 기본 골격, GitHub Actions CI/CD, 모니터링 초기 설정.

**의존성**: 없음 (최초 태스크)
**관련 에이전트**: project-architect, db-architect, python-backend-expert, flutter-frontend-expert

## 2. 디렉토리 구조

```
/
├── server/
│   ├── app/
│   │   ├── main.py              # FastAPI 앱 인스턴스, lifespan
│   │   ├── core/
│   │   │   ├── config.py        # Pydantic BaseSettings
│   │   │   ├── database.py      # SQLAlchemy async engine/session
│   │   │   ├── mongodb.py       # Beanie/Motor init
│   │   │   ├── redis.py         # Redis 클라이언트
│   │   │   ├── deps.py          # FastAPI Depends
│   │   │   └── metrics.py       # Prometheus instrumentator
│   │   ├── api/v1/
│   │   │   ├── __init__.py      # v1 라우터 집합
│   │   │   └── health.py        # GET /health 엔드포인트
│   │   ├── models/              # SQLAlchemy 모델 (빈 __init__.py)
│   │   ├── documents/           # Beanie Document (빈 __init__.py)
│   │   ├── schemas/             # Pydantic v2 스키마
│   │   ├── repositories/        # 레포지토리 계층
│   │   ├── services/            # 비즈니스 로직
│   │   ├── providers/           # 거래소 어댑터
│   │   ├── trading/             # AI 매매 엔진
│   │   └── ws/                  # WebSocket 허브
│   ├── tasks/                   # Celery 태스크
│   ├── alembic/                 # 마이그레이션
│   ├── tests/                   # 테스트
│   ├── Dockerfile               # 멀티스테이지 빌드
│   ├── pyproject.toml           # Python 의존성/린트 설정
│   └── requirements.txt         # Docker 빌드용
├── client/                      # Flutter 프로젝트 (flutter create)
│   ├── lib/
│   │   ├── main.dart
│   │   ├── app/ (router.dart, theme.dart)
│   │   ├── features/ (auth, home, trading)
│   │   ├── core/ (api, websocket, utils)
│   │   ├── shared/ (widgets, models)
│   │   └── l10n/ (ARB 다국어)
│   └── pubspec.yaml
├── shared/
│   ├── api-spec/openapi.yaml    # OpenAPI 스펙
│   └── ws-spec/events.yaml      # WebSocket 이벤트 스펙
├── docker-compose.yml           # postgres, mongodb, redis, server
├── .github/workflows/
│   ├── ci.yml                   # 서버 CI (ruff, mypy, pytest)
│   ├── ci-flutter.yml           # 클라이언트 CI
│   └── docker.yml               # Docker 이미지 빌드/푸시
├── .gitignore                   # Python/Flutter/Docker/IDE 패턴
├── .editorconfig                # 코드 스타일 통일
└── README.md
```

## 3. Docker Compose 서비스

| 서비스 | 이미지 | 포트 | 헬스체크 |
|--------|--------|------|----------|
| postgres | postgres:16-alpine | 5432 | `pg_isready -U $POSTGRES_USER` |
| mongodb | mongo:7 | 27017 | `mongosh --eval "db.adminCommand('ping')"` |
| redis | redis:7-alpine | 6379 | `redis-cli ping` |
| server | build: ./server | 8000 | `curl -f http://localhost:8000/health` |

- 네트워크: `cointrader-network` (bridge)
- 볼륨: `postgres_data`, `mongodb_data`, `redis_data` (named volumes)

## 4. 구현 파일 목록 (서브태스크별)

| ST# | 에이전트 | 생성/수정 파일 |
|-----|----------|---------------|
| 1 | project-architect | `.gitignore`, `.editorconfig`, `README.md`, 전체 디렉토리 `__init__.py` |
| 2 | db-architect | `docker-compose.yml`, `server/.env.example` |
| 3 | python-backend-expert | `server/app/**/__init__.py`, `app/main.py`, `app/core/config.py`, `app/core/database.py`, `app/core/mongodb.py`, `app/core/deps.py` |
| 4 | python-backend-expert | `server/pyproject.toml`, `server/requirements.txt` |
| 5 | python-backend-expert | `server/app/api/v1/health.py`, `app/main.py` 수정 (라우터 등록, CORS, structlog) |
| 6 | flutter-frontend-expert | `client/` 전체 (flutter create), `pubspec.yaml` 수정, `lib/` 디렉토리 구조 |
| 7 | project-architect | `server/.env.example`, `.env.dev`, `.env.staging`, `.env.prod`, `app/core/config.py` 수정 |
| 8 | project-architect | `.github/workflows/ci.yml`, `.github/workflows/ci-flutter.yml` |
| 9 | project-architect | `server/Dockerfile`, `.github/workflows/docker.yml`, `docker-compose.yml` 수정 |
| 10 | project-architect | `app/core/metrics.py`, `app/main.py` 수정 (Sentry, Prometheus) |

## 5. 모듈 의존 관계

```
app/main.py → app/core/config.py (Settings)
app/main.py → app/core/database.py (async engine)
app/main.py → app/core/mongodb.py (init_beanie)
app/main.py → app/core/metrics.py (Prometheus)
app/main.py → app/api/v1/ (라우터)
app/api/v1/health.py → app/core/deps.py (DB 세션)
app/core/database.py → app/core/config.py (DATABASE_URL)
app/core/mongodb.py → app/core/config.py (MONGODB_URL)
```

## 6. 주요 결정사항

| 결정 | 선택 | 근거 |
|------|------|------|
| Python 패키지 관리 | pyproject.toml + requirements.txt | PEP 621 준수, Docker는 requirements.txt |
| FastAPI lifespan | contextmanager 패턴 | on_event deprecated, 공식 권장 |
| 환경변수 로딩 | pydantic-settings | 타입 안전, 검증 자동화 |
| Docker 빌드 | 멀티스테이지 | 이미지 크기 최소화 |
| Flutter 상태관리 | Riverpod | PRD 명세, 코드 생성 지원 |

## 7. 빌드 시퀀스

```
Phase 1: ST1 (디렉토리 구조) ─── 의존성 없음
Phase 2: ST2 (Docker Compose) ─┐
         ST3 (FastAPI 구조)   ─┤── ST1 완료 후 병렬
         ST6 (Flutter 구조)   ─┘
Phase 3: ST4 (Python 의존성) ─── ST3 완료 후
Phase 4: ST5 (헬스체크)      ─┐
         ST7 (환경 설정)      ─┤── ST4+ST2 완료 후 병렬
         ST8 (CI 워크플로우)   ─┘── ST4+ST6 완료 후
Phase 5: ST9 (Docker 이미지) ─── ST8 완료 후
         ST10 (모니터링)     ─── ST5 완료 후
```

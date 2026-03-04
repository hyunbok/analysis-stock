# 확정된 디렉토리 구조 (PRD 분석 후 개선안)

## 서버 구조

```
server/
├── app/
│   ├── main.py
│   ├── core/
│   │   ├── config.py            # Pydantic BaseSettings
│   │   ├── database.py          # AsyncSession 팩토리 (PostgreSQL)
│   │   ├── mongodb.py           # Beanie init_beanie(), Motor 클라이언트 (MongoDB)
│   │   ├── security.py          # JWT, AES-256-GCM
│   │   └── deps.py              # FastAPI Depends
│   ├── api/
│   │   └── v1/
│   │       ├── __init__.py
│   │       ├── auth.py
│   │       ├── users.py
│   │       ├── clients.py
│   │       ├── exchanges.py
│   │       ├── coins.py
│   │       ├── watchlist.py
│   │       ├── orders.py
│   │       └── ai_trading.py
│   ├── ws/
│   │   ├── hub.py               # 연결 풀, 채널 구독 관리
│   │   ├── router.py            # /ws/v1 엔드포인트
│   │   └── handlers/
│   │       ├── ticker.py
│   │       ├── orderbook.py
│   │       └── my_orders.py
│   ├── models/                  # SQLAlchemy 2.0 async (PostgreSQL 테이블만)
│   │   ├── user.py
│   │   ├── client.py
│   │   ├── exchange_account.py
│   │   ├── coin.py
│   │   ├── watchlist.py
│   │   ├── ai_trading_config.py
│   │   └── order.py
│   ├── documents/               # Beanie Document (MongoDB 컬렉션만)
│   │   ├── trade_log.py         # AI 매매 로그
│   │   ├── daily_pnl_report.py  # 일별 손익 리포트
│   │   ├── candle_data.py       # 캔들/시세 히스토리 (Time Series)
│   │   ├── news_data.py         # 뉴스 스크랩
│   │   └── ai_decision.py       # AI 판단 이력
│   ├── schemas/                 # Pydantic v2
│   │   ├── base.py              # ApiResponse[T], ApiError, Meta
│   │   ├── auth.py
│   │   ├── order.py
│   │   └── ...
│   ├── repositories/            # DB 접근 계층 (PG + Mongo 베이스 분리)
│   │   ├── base_pg.py           # AsyncSession 기반 PG 레포지토리 베이스
│   │   ├── base_mongo.py        # Beanie Document 기반 Mongo 레포지토리 베이스
│   │   ├── user_repository.py         # base_pg 상속
│   │   ├── order_repository.py        # base_pg 상속
│   │   ├── trade_log_repository.py    # base_mongo 상속
│   │   ├── candle_repository.py       # base_mongo 상속
│   │   └── ai_decision_repository.py  # base_mongo 상속
│   ├── services/
│   │   ├── auth_service.py
│   │   ├── order_service.py
│   │   ├── exchange_service.py
│   │   └── ai_trading_service.py
│   └── providers/
│       ├── base.py              # ExchangeRestProvider, ExchangeStreamProvider ABC
│       ├── factory.py           # ExchangeProviderFactory
│       ├── upbit.py
│       ├── coinone.py
│       ├── coinbase.py
│       └── binance.py
├── trading/                     # AI 트레이딩 독립 패키지
│   ├── __init__.py
│   ├── regime/
│   │   └── detector.py
│   ├── strategy/
│   │   └── selector.py
│   ├── execution/
│   │   └── engine.py
│   └── indicators/
│       └── calculator.py
├── tasks/                       # Celery 태스크
│   ├── celery_app.py
│   ├── ai_trading.py            # 5분봉 주기 태스크
│   └── news_scraper.py
├── alembic/
├── tests/
│   ├── unit/
│   ├── integration/
│   └── conftest.py
├── pyproject.toml               # ruff + mypy 설정
└── Dockerfile
```

## 클라이언트 구조

```
client/
├── lib/
│   ├── main.dart
│   ├── app/
│   │   ├── router.dart
│   │   └── theme.dart
│   ├── core/
│   │   ├── api/                 # Dio + JWT 자동 갱신 인터셉터
│   │   ├── websocket/           # 단일 WS 연결 관리
│   │   └── utils/
│   ├── shared/
│   │   ├── models/              # 여러 feature 공유 데이터 모델
│   │   └── widgets/             # 공용 위젯
│   ├── features/
│   │   ├── auth/
│   │   │   ├── models/
│   │   │   ├── providers/       # Riverpod
│   │   │   ├── views/
│   │   │   └── widgets/
│   │   ├── home/
│   │   ├── trading/
│   │   ├── exchange/
│   │   ├── ai_trading/
│   │   ├── history/
│   │   └── settings/
│   └── l10n/
├── test/
└── pubspec.yaml
```

## 공유 스펙

```
shared/
├── api-spec/
│   └── openapi.yaml             # OpenAPI 3.1
└── ws-spec/
    └── events.yaml              # WebSocket 이벤트 스펙
```

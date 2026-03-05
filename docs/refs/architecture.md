# CoinTrader - 시스템 아키텍처 & 프로젝트 구조

> 원본: docs/prd.md §3, §11 기준. 최종 갱신: 2026-03-05

---

## 3. 시스템 아키텍처

```
┌──────────────────────────────────────────────────────────┐
│                    Flutter Client                          │
│   (iOS / Android / Windows / macOS / Web)                  │
└────────────┬────────────────────────┬─────────────────────┘
             │ REST API (HTTPS)       │ WebSocket (WSS)
┌────────────▼────────────────────────▼─────────────────────┐
│                    FastAPI Server                           │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌───────────┐ │
│  │  Auth    │  │ Trading  │  │ AI Engine│  │ WS Hub    │ │
│  │ Service  │  │ Service  │  │ Service  │  │(Pub/Sub)  │ │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └─────┬─────┘ │
│       │              │              │               │       │
│  ┌────▼──────────────▼──────────────▼───────────────┤       │
│  │         Exchange Abstraction Layer               │       │
│  │  ┌────────┐ ┌────────┐ ┌──────────┐ ┌────────┐  │       │
│  │  │ Upbit  │ │CoinOne │ │Coinbase  │ │Binance │  │       │
│  │  └────────┘ └────────┘ └──────────┘ └────────┘  │       │
│  └──────────────────────────────────────────────────┘       │
└──────┬──────────────┬──────────────┬───────────────────────┘
       │              │              │
  ┌────▼────┐  ┌────▼────┐  ┌────▼────┐  ┌──────────┐  ┌──────────┐
  │PostgreSQL│  │ MongoDB │  │  Redis  │  │ OpenAI   │  │  Celery  │
  │(트랜잭션)│  │(AI/시세) │  │Cache/Sub│  │  API     │  │  Worker  │
  └─────────┘  └─────────┘  └─────────┘  └──────────┘  └──────────┘

  ┌──────────┐  ┌──────────┐  ┌──────────┐
  │  FCM/    │  │  File    │  │  OAuth   │
  │  APNs    │  │ Storage  │  │ Provider │
  │(푸시알림) │  │(S3/아바타)│  │(Google/  │
  └──────────┘  └──────────┘  │ Apple)   │
                              └──────────┘
```

### 3.1 핵심 설계 원칙

- **Exchange Abstraction Layer**: 모든 거래소를 공통 인터페이스(ABC)로 추상화, Provider Factory로 런타임 선택
- **비동기 우선**: FastAPI async/await, I/O 바운드 최적화
- **이벤트 기반 실시간**: Redis Pub/Sub → WS Hub → 클라이언트 브로드캐스트
- **관심사 분리**: API → Service → Repository 3계층 패턴
- **Celery Worker 분리**: AI 매매, 뉴스 스크랩 등 무거운 작업은 별도 워커에서 실행

### 3.2 핵심 데이터 흐름

```
실시간 시세:  Exchange WS → Provider → Redis Pub/Sub → WS Hub → Client
AI 자동매매: Celery Beat(5분) → 장세분석 → 전략선택 → 매매실행 → Exchange API → PostgreSQL(주문) + MongoDB(로그)
인증 흐름:   Login → JWT(access+refresh) → Redis refresh 저장 → WS 연결 시 토큰 검증
```

---

## 11. 프로젝트 구조

### 11.1 서버

```
server/
├── app/
│   ├── main.py
│   ├── core/                      # 설정, DB, 의존성
│   │   ├── config.py
│   │   ├── database.py            # PostgreSQL (SQLAlchemy async)
│   │   ├── mongodb.py             # MongoDB (Beanie async)
│   │   ├── deps.py
│   │   └── security.py
│   ├── api/v1/                    # API 라우터
│   │   ├── auth.py                # 이메일 인증 (register, login, me, avatar)
│   │   ├── social_auth.py         # 소셜 인증 (Google, Apple OAuth)
│   │   ├── clients.py
│   │   ├── exchanges.py
│   │   ├── coins.py
│   │   ├── watchlist.py
│   │   ├── orders.py
│   │   ├── portfolio.py            # 자산/포트폴리오
│   │   ├── ai_trading.py
│   │   ├── price_alerts.py         # 가격 알림 (M9)
│   │   └── notifications.py       # 알림 (M9)
│   ├── ws/                        # WebSocket 허브
│   │   ├── hub.py
│   │   └── handlers.py
│   ├── models/                    # SQLAlchemy 모델 (PostgreSQL)
│   ├── documents/                 # Beanie 도큐먼트 (MongoDB)
│   ├── schemas/                   # Pydantic 스키마
│   │   ├── ai_trading.py
│   │   ├── backtest.py            # (M9)
│   │   └── common.py              # MetaSchema, PaginationMeta
│   ├── repositories/              # DB 접근 계층
│   │   ├── base_pg.py             # PostgreSQL 베이스 (AsyncSession)
│   │   └── base_mongo.py          # MongoDB 베이스 (Beanie Document)
│   ├── services/                  # 비즈니스 로직
│   │   ├── ai_trading_service.py  # trading/ 패키지 연결 유일 인터페이스
│   │   └── backtest_service.py    # (M9)
│   ├── providers/                 # 거래소 프로바이더
│   │   ├── base.py
│   │   ├── factory.py
│   │   ├── upbit.py
│   │   ├── coinone.py
│   │   ├── coinbase.py
│   │   └── binance.py
│   ├── trading/                   # AI 매매 엔진 (독립 패키지, FastAPI/DB import 금지)
│   │   ├── __init__.py            # public API: RegimeDetector, StrategySelector, ExecutionEngine
│   │   ├── types.py               # 공유 타입
│   │   ├── exceptions.py
│   │   ├── indicators/            # 기술적 지표 계산 (순수 함수)
│   │   ├── regime/                # 장세 분류
│   │   ├── strategy/              # 매매 전략
│   │   ├── execution/             # 매매 실행
│   │   └── gpt/                   # GPT 연동 분리
│   └── utils/
├── tasks/                         # Celery 태스크
│   ├── celery_app.py              # Celery 앱 설정 + Beat 스케줄 + 큐 라우팅
│   ├── ai_trading.py              # AI 매매 태스크
│   ├── news_scraper.py
│   ├── reports.py                 # 일별 PnL 리포트
│   └── cleanup.py                 # 만료 토큰 정리
├── alembic/
├── tests/
├── requirements.txt
├── Dockerfile
└── docker-compose.yml
```

### 11.2 클라이언트

```
client/
├── lib/
│   ├── main.dart
│   ├── app/
│   │   ├── router.dart
│   │   └── theme.dart
│   ├── features/                  # Feature-first 구조
│   │   ├── auth/
│   │   ├── home/
│   │   ├── trading/
│   │   ├── exchange/
│   │   ├── ai_trading/
│   │   ├── portfolio/
│   │   ├── history/
│   │   ├── notifications/         # (M9)
│   │   └── settings/
│   ├── core/
│   │   ├── api/                   # Dio 클라이언트
│   │   ├── websocket/             # WS 클라이언트
│   │   └── utils/
│   └── l10n/                      # 다국어 ARB 파일
├── assets/
├── test/
└── pubspec.yaml
```

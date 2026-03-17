# Project Architect Memory

## 프로젝트 구조
- 설계서 위치: `docs/tasks/v1-{N}-{name}-plan.md`
- 참조 문서: `docs/refs/project-prd.md`, `docs/refs/architecture.md`, `docs/refs/security.md`
- 서버 코드: `server/app/` (FastAPI, 3계층: api → services → repositories)
- 테스트: `server/tests/` (unit/, integration/)

## 아키텍처 패턴
- 모듈러 모놀리스, 3계층 패턴 (API → Service → Repository)
- DI: FastAPI Depends 체인, `deps.py`에 팩토리 함수 + Annotated 타입 별칭
- 에러 처리: AppError 도메인 예외 → error_handler.py 글로벌 핸들러 → ErrorResponse 통일 포맷
- 미들웨어 체인 (LIFO): CORS → CorrelationId → RateLimit → Prometheus → ErrorHandler

## 기존 인프라
- DB: PostgreSQL (SQLAlchemy async), MongoDB (Beanie), Redis (redis.asyncio)
- 설정: `core/config.py` (pydantic-settings), `core/redis_keys.py` (키 패턴/TTL)
- 인증 캐시: `services/auth_cache_service.py` (refresh token, email verify, password reset)

## 설계서 작성 컨벤션
- code-architect와 분업: 나는 파일 구조/DI 흐름/시퀀스 다이어그램, 상대는 API 규격/스키마/컨벤션
- 기존 코드와의 정합성 반드시 확인 후 작성
- 시퀀스 다이어그램은 ASCII art 형식 사용

## v1-5 결정 사항
- soft delete: `soft_deleted_at: datetime | None` (bool 아닌 timestamp)
- JWT: python-jose, bcrypt: passlib, email: aiosmtplib
- Refresh token rotation + SHA-256 해시 Redis 저장

## v1-6 결정 사항 (소셜 로그인)
- 단일 OAuthVerificationService (Google/Apple 통합, _PROVIDER_CONFIG dict + _verify_token() 공통)
- JWKS URL 하드코딩 (SSRF 방지, 환경변수 노출 금지)
- JWKS Redis 캐시 (JwksCacheService, 멀티워커 안전)
- SRP 분리: schemas/social_auth.py, api/v1/social_auth.py (기존 auth.py에 추가 안 함)
- AuthErrors에 통합 (별도 SocialAuthErrors 클래스 금지)
- 의존 라이브러리: python-jose[cryptography] (RSA), httpx (JWKS fetch)

## v1-7 결정 사항 (2FA + 세션 관리)
- 2FA: TOTP (pyotp), AES-256-GCM 암호화 (cryptography), QR (qrcode[pil])
- 백업 코드: 10개 × 10자리, 별도 `user_totp_backup_codes` 테이블 (LargeBinary 기각)
- 백업 코드 반환 시점: setup이 아닌 **verify 성공 시** 반환
- 로그인 2FA: temp_token(5분 TTL) → POST /2fa/login-verify, LoginResponse nullable 통합
- Device 정보: Header 방식 (X-Device-Name, X-Device-Fingerprint), Body 아님
- Client 모델: device_name(200), user_agent, ip_address, device_fingerprint, is_active 추가
- 에러 통합: INVALID_BACKUP_CODE → invalid_totp_code(), TOTP_SETUP_EXPIRED → totp_setup_required()
- TOTP 브루트포스: 2fa:fail_count:{user_id} Redis 키 (5회/15분)
- AuditService: mongodb DI 주입, fire-and-forget (실패해도 주요 로직 차단 안 함)
- 서비스 오케스트레이션: AuthService에 TwoFactorService 주입 안 함 → API 레이어에서 조율 (순환 의존 방지)
- Setup TTL: 10분, Temp token TTL: 5분
- URL: POST /2fa/disable (DELETE 아님, body 필요), POST /2fa/login-verify

## v1-8 결정 사항 (거래소 추상화 계층)
- ABC 3단계: ExchangeRestProvider → ExchangeStreamProvider → ExchangeProvider (통합)
- BaseExchangeProvider: `_execute_rest()` 래퍼로 Rate Limiter → Circuit Breaker 자동 적용
- Factory 싱글턴: `ExchangeProviderFactory.init(redis)` → `.instance()` 패턴
- Registry 데코레이터: `@ExchangeProviderRegistry.register(ExchangeType.UPBIT)` 방식
- Circuit Breaker: 인메모리, 거래소별 독립, 슬라이딩 윈도우 + 연속 실패 하이브리드
- Circuit Breaker 제외 예외: Auth, Permission, InvalidSymbol, InsufficientBalance (사용자 오류)
- 기존 ExchangeRateLimiter 100% 재사용 (providers/rate_limiter.py 별도 생성 안 함)
- 예외 이중 계층: providers/exceptions.py (내부) → core/exceptions.py ExchangeErrors (HTTP 응답)
- v1-8 범위: 추상화 + Mock Provider만. 실제 거래소는 M3(Upbit), M5(CoinOne) 등에서 구현
- 의존 라이브러리: websockets 신규 추가, httpx 기존 의존
- SymbolMapper: 정규화 심볼 "BTC/KRW" ↔ 거래소 마켓 코드 양방향 변환

## v1-9 결정 사항 (Upbit 거래소 프로바이더)
- 디렉토리: `providers/upbit/` (provider.py, auth.py, stream.py, mappers.py, constants.py)
- JWT 알고리즘: **HS512** (Upbit 공식 문서 기준, HS256 아님)
- JWT payload: access_key, nonce(UUID4), query_hash(SHA-512, 조건부), query_hash_alg
- POST body query_hash: body를 "key=value&key=value"로 변환 후 SHA-512
- WS 파일명: `stream.py` (websockets 라이브러리명 충돌 방지, ExchangeStreamProvider 일관성)
- WS 클래스: `_UpbitWebSocketClient` (언더스코어 prefix로 internal 표시)
- SymbolMapper 동적 등록: initialize() 시 GET /v1/market/all → register_batch()
- 정적 fallback: UPBIT_STATIC_MARKETS 15개 (동적 로드 실패 시 유지)
- 에러 매핑: UPBIT_ERROR_MAP(error.name 기반) + HTTP_STATUS_ERROR_MAP(폴백)
- HTTP 418 처리: Upbit 고유 IP 차단 → ExchangeRateLimitError
- 시장가 매수 특이사항: ord_type="price", volume 대신 price(총 KRW)로 입력
- 재시도: Provider는 단발 호출, 서비스 레이어에서 Exponential Backoff (최대 3회)
- 의존 라이브러리: PyJWT>=2.8, websockets>=12.0
- 테스트: 42건 (단위 38 + 통합 4)

## v1-10 결정 사항 (CoinOne 거래소 프로바이더)
- 디렉토리: `providers/coinone/` (provider.py, auth.py, stream.py, mappers.py, constants.py)
- 인증: HMAC-SHA512 (표준 라이브러리만 사용, PyJWT 불필요)
  - Body → JSON → Base64 → X-COINONE-PAYLOAD 헤더
  - HMAC-SHA512(payload, secret_key) → X-COINONE-SIGNATURE 헤더
  - access_token을 body에 포함, nonce는 UUID v4
- REST 헬퍼 분리: `_public_request(GET)` / `_private_request(POST+HMAC)` (Upbit의 단일 `_request` 대신)
- 마켓 코드: target_currency 소문자 ("BTC/KRW" → "btc"), quote_currency 항상 "KRW" 고정
- 에러 처리: 숫자 error_code 기반 COINONE_ERROR_MAP (error_code "4" = rate limit 초과)
- WS URL: wss://stream.coinone.co.kr, 개별 SUBSCRIBE 메시지 방식 (Upbit 배열 방식과 다름)
- WS 타임아웃: 30분 (Upbit 120초 대비 여유), PING 간격 5분(300초)
- WS 연결: IP당 20개 (Upbit 5개 대비 여유)
- Rate Limit: Public 1200/분(IP), Private Order 40/초, Other 80/초 (포트폴리오 기준)
- 수수료: API 사용자 Maker/Taker 0.02%
- 추가 의존성: 없음 (websockets는 v1-9에서 이미 추가)
- 테스트: 42건 예상 (단위 38 + 통합 4)
- ST7/ST8 (Rate Limit/Circuit Breaker): 기존 인프라 100% 재사용, 별도 구현 없음

## v1-13 결정 사항 (코인 마스터 및 관심 코인 관리 API)
- 단일 CoinService (coin 검색 + watchlist CRUD 통합), Repository만 분리 (coin_repository + watchlist_repository)
- Flat ticker 필드 (Decimal) — CoinResponse에 직접 포함 (nested TickerSummary 기각)
- ON CONFLICT DO NOTHING — 관심 코인 중복 방지 (race condition 안전, IntegrityError catch 기각)
- CurrentUserOptional — 코인 검색은 공개 데이터 (미인증 허용)
- Redis 직접 주입 — pipeline 일괄 조회용 (MarketCacheService 래퍼 미사용)
- CoinErrors 팩토리: not_found, watchlist_not_found, watchlist_duplicate, watchlist_access_denied, watchlist_reorder_invalid, exchange_account_mismatch
- DI: ExchangeAccountRepository 주입 (exchange_account 소유권 검증)
- 라우터 등록 순서: PUT /watchlist/reorder를 DELETE /watchlist/{id}보다 먼저 (path 캡처 방지)
- bridge.py SETEX 추가: WS ticker → Redis 스냅샷 저장 → REST API에서 읽기
- 인덱스 4개 추가: name_ko/name_en GIN trgm, exchange_active partial, watchlist_user_account_sort 복합
- CASE WHEN 배치 UPDATE (SQLAlchemy case() + update(), bulk_update_mappings 기각)
- Seed 스크립트: scripts/seed/seed_coins.py (Alembic 분리), pg_insert ON CONFLICT DO UPDATE, --exchange 옵션
- ReorderWatchlistRequest: sort_order 유니크 validator (model_validator)
- 오프셋 기반 페이지네이션 (page + size), PaginatedCoins 스키마

## v1-14 결정 사항 (주문 실행 및 거래 API)
- 단일 OrderService (생성/조회/취소 통합), OrderRepository 분리
- OrderStateMachine: order_service.py 내 모듈 레벨 클래스 (별도 trading/ 패키지 미생성)
- 주문 상태 6개: pending, open, filled, partial, cancelled, failed (CHECK 제약 변경)
- 시장가 매수: `amount` 필드 신규 (KRW 총액), `quantity` nullable 변경, `price` 재활용 대신 명시적 분리
- Provider.place_order() 호출 전 PENDING INSERT → 성공 시 상태 전이 → 실패 시 FAILED
- 주문 생성 재시도 금지 (시장가/지정가 모두, 이중 주문 위험), 취소만 3회 지수 백오프 (멱등)
- 에러 매핑: OrderService._map_exchange_error() 정적 메서드, match/case 패턴
- batch-cancel: asyncio.gather 병렬 + BatchCancelResponse (부분 성공 허용)
- DB 컬럼 추가: amount, executed_price, fee_rate(감사/이상탐지용), fee_currency
- trading_fees 테이블 신규: 거래소별 tier별 maker/taker rate + Redis 캐시(1h TTL)
- trade_order_events 테이블 신규: 상태 변경 이력 (전자금융거래법 5년 보존)
- 인덱스 3개 추가 + 기존 pending partial 인덱스 → active로 확장 (pending, open, partial)
- exchange_order_id UNIQUE PARTIAL 인덱스 (exchange_account_id 포함, NULL 허용)
- OrderErrors 팩토리: not_found, invalid_status_transition, cannot_cancel, insufficient_balance, exchange_order_failed, exchange_unavailable
- DI: OrderRepository + ExchangeAccountRepository + ExchangeProviderFactory + Settings
- AuditService: 주문 생성/취소/일괄 취소 시 기록 (거래소 응답 성공 후만)
- v1-14 범위: 요청 시점 동기화(Passive Sync)만, WS 능동 동기화는 v2

## v1-15 결정 사항 (기술적 지표 계산 엔진)
- 순수 함수 패키지: `trading/indicators/` (FastAPI/DB import 금지, pandas/numpy만 허용)
- 파일 구조: types.py, trend.py, oscillator.py, volatility.py (OBV 포함), calculator.py
- 타입: TypedDict (Pydantic 아닌 stdlib), CandleInput(float), IndicatorResult
- EMA: 20/50/200 (PRD §7.3.1 준수, 9/21 제외)
- VWAP: VWAPResult(vwap + upper_band + lower_band), k=1.5, KST 00:00 리셋
- Bollinger: percent_b 포함 (전략 D "%B < 0.05" 필수)
- 과매수/과매도 플래그: indicators/ 미포함, regime/strategy 레이어에서 판별
- 데이터 부족: None 반환 (ValueError는 빈 리스트만), NaN 자연 전파
- 캐싱: MarketCacheService 기존 set/get_indicators 재사용 (신규 캐시 서비스 불필요)
- IndicatorService: services/indicator_service.py 신규, MarketCacheService + Motor DI
- IndicatorErrors: core/exceptions.py (insufficient_candles, calculation_failed)
- 성능 기준: 200행 <50ms, 576행 <100ms, 캐시 HIT <5ms

## v1-16 결정 사항 (AI 장세 분석 엔진)
- 패키지: `trading/regime/` (types.py, rules.py, classifier.py, detector.py, gpt_validator.py)
- 순수 함수 패턴 (indicators/와 동일) + MarketRegimeDetector 클래스 래퍼 (태스크 스펙)
- 규칙 5개: check_adx_strength, check_ema_alignment, check_macd_momentum, check_rsi_regime, check_bollinger_regime
- 가중치: ADX 30%, EMA 20%, RSI 20%, MACD 15%, BB 15% → softmax 정규화
- None 규칙 가중치 재정규화, 활성 규칙 < 2 시 confidence 0.3 강제
- GPT 검증: confidence < 0.7 OR transition 시 호출, openai SDK AsyncOpenAI
- GPT api_key/model 파라미터 주입 (Config import 금지), 실패 시 non-blocking
- gpt_validator.py는 trading/regime/ 내 유지 (openai는 인프라 결합 없는 허용 예외)
- RegimeService: MarketCacheService + AICacheService + MongoDB + Settings DI
- AiDecision 도큐먼트 재사용 (신규 컬렉션 생성 안 함)
- AiDecision 6개 필드 Optional화: selected_strategy, action, action_confidence, gpt_model, gpt_prompt_tokens, gpt_completion_tokens
- 기존 RedisKey.regime() / RedisTTL.REGIME=300 재사용 (변경 없음)
- 기존 OPENAI_API_KEY, OPENAI_MODEL 재사용 + OPENAI_TIMEOUT 신규 추가 제안
- RegimeErrors 팩토리: insufficient_indicators, gpt_validation_failed, analysis_failed
- RegimeType 소문자 통일: "trend" | "range" | "transition"
- 신규 라이브러리: openai>=1.0
- 테스트: ~44건 (규칙 20, 분류기 10, GPT mock 6, 서비스 8)

## v1-17 결정 사항 (AI 매매 전략 선택 및 신호 생성 엔진)
- 순수 계산 패키지: `trading/strategy/` (FastAPI/DB/Redis import 금지)
- 파일 구조: types.py, base.py, candle_patterns.py, 5개 전략, selector.py, signal_generator.py
- 타입: StrategyName Literal (str 아님), ConditionResult(name+passed+detail), StrategySignal, TradingSignal
- SignalStrength: "strong" | "moderate" | "weak" (medium 아닌 moderate)
- ABC: TradingStrategy(name, compatible_regimes, stop_loss/take_profit_atr_mult, risk_reward_ratio, evaluate)
- evaluate() 시그니처: (candles, indicators) → StrategySignal | None (regime 파라미터 없음, SRP)
- candle_patterns.py: strategy/ 내 배치 (indicators/ 아님), 5패턴 순수 함수
- StrategySelector: REGIME_STRATEGY_MAP 상수, select()가 evaluate()까지 호출 (우선순위 기반)
- REGIME_STRATEGY_MAP: trend→[trend_ma, vwap_bounce], range→[rsi_bb_reversal, vwap_band_reversal], transition→[rsi_divergence]
- SignalGenerator: 5분봉 기준 전략 평가 + 1h/4h MTF 방향 검증 (EMA20 vs EMA50 + RSI 50)
- MTF 차단: 매수 시 bearish 타임프레임 존재 → 차단, weight: 1.0/0.75/0.5
- ExitParams: 전략별 ATR 배수 내장 (A/B: SL 1.5 TP 3.0 RR 1:2, C/D: SL 1.0 TP 1.5 RR 1:1.5, E: SL 1.5 TP 3.75 RR 1:2.5)
- OBV 추세: 최근 5봉 close 방향 간이 판별 (OBV 시계열 범위 밖)
- RSI 다이버전스: rsi_divergence.py 내부 _calculate_rsi_series() 헬퍼 (50봉 탐색)
- 청산 조건 평가: v1-17 범위 밖, 진입 시점 ExitParams만 포함
- 신규 라이브러리: 없음
- 테스트: ~70건 (단위 65 + 통합 5)

## v1-18 결정 사항 (주문 실행 및 리스크 관리 엔진)
- 패키지: `trading/execution/` (순수 계산이 아닌 통합 패키지 — Redis, MongoDB, Provider 의존)
- 파일 구조: types.py, constants.py, exceptions.py, risk_manager.py, position_sizing.py, sl_tp.py, drawdown_manager.py, order_tracker.py, trade_logger.py, engine.py
- 순수/비순수 분리: risk_manager.py, position_sizing.py, sl_tp.py (순수) | drawdown_manager.py (Redis), order_tracker.py (OrderRepository+Provider), trade_logger.py (Beanie), engine.py (오케스트레이터)
- **의존 방향**: OrderService import 금지 → OrderRepository 직접 주입 (trading/ → repositories/ 허용)
- **OrderRepository.create(is_ai_order=True)** 직접 호출 — update_ai_flag() 불필요
- **count_active_ai_orders()**: OrderRepository 신규 메서드 (AI 미체결 주문 수 조회)
- **RiskManager 순수화**: Redis 의존 없음, DrawdownState + RiskParams 입력만
- **PositionSizer ABC 미사용**: FixedFractionalSizer + HalfKellySizer 독립 클래스 (@staticmethod)
- engine.py에서 둘 다 실행 후 min(보수적) 선택
- **TradeLogger**: AsyncIOMotorDatabase 주입 없음, Beanie Document 직접 (생성자 없음)
- Redis Hash: 단일 `trading:drawdown:{user_id}:{ea_id}` (TTL=48h), positions Set (TTL=24h)
- 내부 예외: trading/execution/exceptions.py (TradeExecutionError → RiskLimitExceeded, PositionSizingError, OrderExecutionError)
- **DI**: Celery task에서 직접 인스턴스화 (FastAPI deps.py 변경 없음)
- RiskParams: win_rate_estimate(0.5), avg_rr_ratio(1.5) 포함
- Trailing Stop: polling 방식 (v1-18), WS 기반은 v2
- 부분 체결: 60초 대기(10초 폴링) → 잔량 취소
- 재시도: 네트워크/가용성만 30초 간격 2회, 사용자 오류 즉시 실패
- 신규 라이브러리: 없음
- 테스트: ~50건 (단위 45 + 통합 5)

## v1-19 결정 사항 (Celery 비동기 작업 및 스케줄)
- 디렉토리: `server/tasks/` (app 밖 독립 패키지, PRD 구조 준수)
- 파일: celery_app.py, context.py, ai_trading.py, news_scraper.py, reports.py, cleanup.py
- async 패턴: `asyncio.run()` per-task + TaskContext 프로세스 싱글턴 (prefork pool 고수)
- TaskContext: lazy 초기화, Redis+AsyncEngine+MotorDB 보유, create_session() 메서드
- Redis DB 분리: DB0=앱 캐시/PubSub, DB1=Celery Broker, DB2=Celery Result
- 큐 3개: ai, scraper, default (kombu Queue)
- Beat: AI매매 300초, 뉴스 3600초, PnL crontab(0:05UTC), cleanup crontab(3:00UTC)
- 2단계 Redis Lock: cycle 280초 + config별 270초 (SET NX + TTL)
- run_single_config: max_retries=3 지수 백오프 (거래소 네트워크 오류만)
- run_backtest: (config_id, start_date, end_date) M9 스텁
- DLQ 대신 Sentry CeleryIntegration + task_acks_late
- 3계층 마스터 스위치: settings.AI_TRADING_ENABLED + Redis kill switch + user.ai_trading_enabled
- Settings 추가: CELERY_BROKER_URL, CELERY_RESULT_BACKEND, CELERY_WORKER_CONCURRENCY, AI_TRADING_ENABLED, NEWS_SCRAPER_ENABLED
- celery_broker_url/celery_result_backend: @property (REDIS_URL 기반 DB번호 자동 계산)
- 뉴스 스크랩: v1-19는 스캐폴딩만, 실제 크롤러 v2
- BaseAsyncTask 추상 베이스 클래스
- 테스트: ~38건 (단위 30 + 통합 8)

## v1-20 결정 사항 (포트폴리오/자산 조회 API)
- 단일 PortfolioService + PortfolioRepository(ReadOnly, SELECT 집계 전용)
- 평균 매입가: 가중 평균(VWAP) — Σ(qty×price)/Σ(qty), filled buy만, 매도 무관 (국내 거래소 표준)
- 데이터 소스: 거래소 API 실시간 호출 + Redis 캐시 (DB 동기화 아님)
- 원화 환산: KRW 기축 직접 계산, 환율 모듈 불필요 (해외 거래소는 v2)
- Redis 키: portfolio:summary:{user_id}(5분), portfolio:exchange:{user_id}:{ea_id}(1분), portfolio:avg_price:{user_id}:{ea_id}(10분)
- Redis 키에 user_id 포함 (keyspace 격리, 보안 스캔 용이 — code-architect 제안 채택)
- PortfolioErrors 4개: exchange_account_not_owned(403), no_exchange_accounts(404), balance_fetch_failed(503), exchange_unavailable(503)
- 에러 코드 네임스페이스: PORTFOLIO_ 접두사
- DI: PortfolioRepository + ExchangeAccountRepository + ExchangeProviderFactory + MarketCacheService + Redis + Settings
- 부분 실패 허용: asyncio.gather(return_exceptions=True), 실패 거래소 제외, 나머지 반환
- 도넛 차트: portfolio_weight 필드 (0.0~100.0 Decimal), KRW 포함, remainder adjustment
- 캐시 무효화: 주문 체결(→filled) 시 3개 키 DEL (v1은 OrderService 직접, v2는 Pub/Sub)
- top_coins: value_krw 내림차순 상위 5개
- 테스트: 단위 ~25건 + 통합 ~9건

## v1-21 결정 사항 (가격 알림 시스템)
- PriceAlertMonitor: Redis Pub/Sub ticker 구독, ws/price_alert_monitor.py, lifespan 연동
- 트리거 중복 방지: DB UPDATE WHERE is_triggered=false (1차) + Redis SETNX 30초 (2차)
- FCMService 스텁: Settings.FCM_SERVER_KEY, Client.fcm_token 복수 기기 지원
- NotificationService + NotificationRepository (MongoDB), 커서 기반 페이지네이션

## v1-22 결정 사항 (FCM 푸시 알림 시스템)
- Firebase Admin SDK (firebase-admin>=6.0) — Legacy Server Key 폐기
- 인증: FIREBASE_CREDENTIALS_PATH (서비스 계정 JSON 파일 경로), 빈 문자열=비활성
- FCMService 리팩토링: Settings만 → ClientRepository + Redis + Settings 3개 의존
- 초기화: lifespan에서 firebase_admin.initialize_app() 1회 → 싱글턴 아님, DI 매 요청 생성
- 범용 send_to_user(user_id, title, body, data, silent) — 내부에서 토큰 조회 + send_each() 멀티캐스트
- 알림 유형 헬퍼: send_order_execution(), send_ai_signal(), send_price_alert(), send_system_alert()
- 기존 Client 모델 fcm_token 재활용 (별도 fcm_tokens 테이블 미생성)
- 토큰 관리: PUT /api/v1/clients/me/fcm-token (JWT client_id 기반)
- Rate Limiting: fcm:rate:{user_id} INCR+EXPIRE(60), 분당 10건
- Dedup: fcm:dedup:{user_id}:{type}:{hash} SETNX(60초), SHA-256(title+body)[:16]
- 실패 토큰 정리: NotRegistered/UNREGISTERED → ClientRepo.clear_fcm_token()
- Silent push: data-only 메시지 (notification 필드 제외), content_available=True (iOS)
- 호출자 패턴: 각 서비스가 NotificationService.create() + FCMService.send_xxx() 독립 호출
- PriceAlertService 변경: client_repo DI 제거 (FCMService가 내부 보유)
- FCMErrors: not_configured(503), token_invalid(400), send_failed(502)
- 의존 라이브러리: firebase-admin>=6.0
- 테스트: ~42건 (단위 28 + 통합 14)

## v1-23 결정 사항 (Flutter 프로젝트 기본 구조)
- GoRouter: StatefulShellRoute.indexedStack 5탭 (홈/트레이딩/AI매매/자산/더보기)
- 인증 가드: GoRouter.redirect (splash에서 토큰 확인 → 자동 리다이렉트)
- Theme: TradingColors ThemeExtension (한국식 red=buy/blue=sell, 글로벌 green=buy/red=sell)
- i18n: flutter_localizations + intl ARB, 5언어 (en/ko/ja/zh/es), ~30개 기본 키
- Riverpod: @Riverpod(keepAlive: true) for core infra, @riverpod (autoDispose) for features
- Dio: interceptors/ 하위 3개 파일 분리 (auth, refresh, error)
- RefreshInterceptor: Completer lock + 별도 Dio (순환 방지), refresh token rotation 대응
- ApiException: Freezed 4 variant (server, network, timeout, unauthorized)
- WS: web_socket_channel, 서버 v1-12 프로토콜 완전 매칭
- WS 재연결: 지수 백오프 (1s→30s max), 기존 구독 자동 복원
- WS Heartbeat: 30초 ping, 10초 pong 타임아웃
- Storage: SecureStorage (JWT), AppPreferences (설정), Hive (캐시, v1-23은 초기화만)
- Feature 패턴: models/repositories/providers/screens/widgets 5-folder
- 환경 설정: --dart-define=API_BASE_URL 빌드 타임 오버라이드
- code-architect 분업: Riverpod/Dio/WS/Storage/Features 설계 담당

## 협업 패턴
- code-architect와 이견 시 먼저 합의 후 설계서 반영 (동시 편집 충돌 주의)
- 설계서 초안을 먼저 작성하고 상대에게 수정/보강 요청하는 방식이 효율적
- db-architect와 3자 합의 패턴 확립: 초안 → 병렬 리뷰 요청 → 피드백 반영 → 최종 확정

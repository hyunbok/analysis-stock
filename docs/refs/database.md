# CoinTrader - 데이터베이스 설계

> 원본: docs/prd.md §4 기준. 최종 갱신: 2026-03-05

---

## 4.1 하이브리드 DB 전략

트랜잭션 정합성이 필요한 핵심 거래 데이터는 **PostgreSQL**, 비정형/대량 시계열 데이터는 **MongoDB**로 분리한다.

## 4.2 PostgreSQL (트랜잭션 데이터)

```
users ──< clients (디바이스)
  │
  ├──< user_social_accounts (소셜 로그인)
  │
  ├──< user_exchange_accounts ──< watchlist_coins
  │                                     │
  │                                     ▼
  │                            ai_trading_configs
  │
  └──< trade_orders
```

| 테이블 | 설명 | 주요 컬럼 |
|--------|------|-----------|
| users | 회원 | email, password_hash(NULL 허용—소셜 전용 계정), nickname, avatar_url, language, theme, price_color_style(korean/global), ai_trading_enabled, totp_secret(nullable), is_2fa_enabled, email_verified_at |
| user_social_accounts | 소셜 로그인 연동 | user_id(FK), provider(google/apple), provider_id, provider_email |
| clients | 클라이언트/디바이스 | user_id, device_type, fcm_token |
| user_exchange_accounts | 거래소 계정 | user_id, exchange_type, api_key_encrypted, api_secret_encrypted |
| coins | 코인 마스터 | symbol, name_ko, name_en, exchange_type, market_code |
| watchlist_coins | 관심 코인 | user_id, coin_id, exchange_account_id, sort_order |
| ai_trading_configs | AI 매매 설정 | watchlist_coin_id, is_enabled, max_investment_ratio(NUMERIC, 기본 0.10), stop_loss_ratio(NUMERIC, 기본 0.02), take_profit_ratio(NUMERIC, 기본 0.03), daily_max_loss_ratio(NUMERIC, 기본 0.05), primary_timeframe(VARCHAR, 기본 '5m'), confirmation_timeframes(VARCHAR[], 기본 '{\"15m\",\"1h\"}'), strategy_params(JSONB), enabled_at, disabled_at, disable_reason |
| ai_trading_config_history | AI 설정 변경 이력 | config_id(FK), action(enabled/disabled/params_updated), changed_by(user/system), change_detail(JSONB) |
| trade_orders | 매매 주문 | order_type(buy/sell), order_method(market/limit), price, quantity, fee, status(pending/filled/cancelled/partial), is_ai_order |
| backtest_runs (M9) | 백테스팅 실행 이력 | user_id, coin_symbol, exchange_type, timeframe, start_date, end_date, initial_capital, strategy_config(JSONB), status(pending/running/completed/failed), celery_task_id |
| price_alerts | 가격 알림 조건 | user_id, coin_id, exchange_account_id, condition(above/below), target_price, is_triggered, is_active |
| user_consents | 개인정보 동의 이력 | user_id, consent_type(terms/privacy/marketing), agreed_at, version |

## 4.3 MongoDB (비정형/시계열 데이터)

| 컬렉션 | 설명 | 주요 필드 |
|--------|------|-----------|
| trade_logs | AI 매매 로그 | user_id, trade_order_id(PG 참조), coin_symbol, market_code, exchange_type, order_type/method, price/quantity/fee(비정규화 스냅샷), is_ai_order, market_regime, strategy_name, ai_decision_id, reasoning_summary, strategy_params_snapshot(JSONB), entry_price, pnl_amount/pnl_ratio/holding_minutes(청산 시), status |
| ai_decisions | AI 판단 이력 | user_id, coin_symbol, market_regime, regime_confidence(dict), selected_strategy, action(buy/sell/hold), action_confidence, indicators_snapshot(IndicatorsSnapshot 내장 도큐먼트 — MA/EMA/VWAP/RSI/MACD/BB/ADX 등 14종), gpt_model/gpt_prompt_tokens/gpt_completion_tokens/gpt_raw_response/gpt_parsed_result, news_context_summary, trade_log_id, execution_skipped_reason, analysis_duration_ms, celery_task_id. TTL 6개월 |
| daily_pnl_reports | 일별 손익 리포트 | user_id, report_date, total_pnl/trade_count/win_rate, ai_pnl/ai_trade_count/ai_win_count, manual_pnl/manual_trade_count, regime_stats(dict), strategy_stats(dict), cumulative_pnl. upsert 멱등성 보장 |
| candle_data_{tf} | 캔들/시세 히스토리 | 타임프레임별 별도 컬렉션 (`candle_data_1m`~`candle_data_1d`). Time Series 컬렉션(timeField=timestamp, metaField=exchange_type+market_code). TTL 차등: 1m=7일, 5m=90일, 15m=180일, 1h=1년, 4h=2년, 1d=5년 |
| backtest_results (M9) | 백테스팅 결과 | backtest_run_id(PG 참조), summary(총수익률/승률/샤프비율/MDD), trades(개별 거래 임베딩), daily_performance, regime_performance |
| news_data | 뉴스 스크랩 | 비정형 텍스트, 임베딩 벡터 |
| notifications (M9) | 알림 이력 | user_id, type(price_alert/ai_trading/order_execution), title, body, data(가변), is_read, TTL 90일 |
| audit_logs | 감사 로그 | user_id, action(login/logout/api_key_change/password_change/2fa_toggle), ip_address, user_agent, details(가변), created_at |

## 4.4 크로스DB 설계 주의사항

- **trade_logs(Mongo) → trade_orders(PG) 참조**: DB 레벨 조인 불가. trade_logs에 order 스냅샷(price, quantity, order_type) 비정규화 저장
- **daily_pnl_reports 집계**: PG(trade_orders) + Mongo(trade_logs) 동시 조회 필요. `report_date + user_id` 기준 upsert로 멱등성 보장
- **Beanie Document → API 응답**: `_id`, `revision_id` 등 내부 필드 노출 방지. `ResponseSchema.model_validate(document)` 변환 패턴 사용

> 상세 스키마(컬럼 타입, 인덱스, 제약조건, 도큐먼트 구조)는 DB 설계 태스크에서 정의한다.

## 4.5 Redis 활용

| 용도 | 키 패턴 |
|------|---------|
| Refresh Token | `auth:refresh:{user_id}:{client_id}` |
| Rate Limiting | `rate:{ip}`, `rate:{user_id}` |
| 실시간 시세 Pub/Sub | `ticker:{exchange}:{market}` |
| 알림 미읽 수 캐시 | `notifications:unread_count:{user_id}` |
| 기술적 지표 스냅샷 | `indicators:{exchange}:{market}:{timeframe}` (TTL 60~600s) |
| 장세 분석 결과 | `regime:{exchange}:{market}` (TTL 300s) |
| AI 최신 결정 | `ai_decision:{user_id}:{market}:latest` (TTL 300s) |
| 캔들 캐시 | `candles:{exchange}:{market}:{timeframe}:{count}` (TTL 30s, Cache-Aside) |
| GPT 뉴스 감성 캐시 | `ai:news_sentiment:{coin}` (TTL 30분) |
| 마지막 분석 시간 | `ai:last_run:{user_id}:{coin}` (TTL 10분) |
| AI 실시간 신호 Pub/Sub | `ai:signal:{user_id}` |
| Celery 브로커/결과 | Celery 기본 설정 |

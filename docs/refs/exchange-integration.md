# CoinTrader - 거래소 연동

> 원본: docs/prd.md §6 기준. 최종 갱신: 2026-03-05

---

## 6.1 지원 거래소

| 거래소 | 구분 | 기축 통화 | Phase |
|--------|------|-----------|-------|
| Upbit | 국내 | KRW | Phase 1 |
| CoinOne | 국내 | KRW | Phase 1 |
| Coinbase | 해외 | USD | Phase 2 |
| Binance | 해외 | USDT | Phase 2 |

## 6.2 Exchange Abstraction Layer

```python
# REST 조회/주문
class ExchangeRestProvider(ABC):
    async def get_ticker(market) -> Ticker
    async def get_orderbook(market) -> OrderBook
    async def get_candles(market, interval, count) -> list[Candle]
    async def place_order(order) -> OrderResult       # order_method: market/limit
    async def cancel_order(order_id) -> bool
    async def get_balance() -> list[Balance]
    async def get_trading_fee(market) -> TradingFee   # maker/taker 수수료율
    async def verify_api_key() -> ApiKeyInfo           # 권한 범위 확인

# 실시간 스트리밍
class ExchangeStreamProvider(ABC):
    async def subscribe_ticker(markets, callback) -> None
    async def subscribe_orderbook(markets, callback) -> None

# 통합 프로바이더
class ExchangeProvider(ExchangeRestProvider, ExchangeStreamProvider):
    pass

# 팩토리
class ExchangeProviderFactory:
    def create(exchange_type, credentials) -> ExchangeProvider
```

## 6.3 거래소 API 키 권한 검증

API 키 등록(`POST /api/v1/exchanges`) 시 `verify_api_key()`로 권한 범위를 확인한다.
- **출금 권한 감지 시**: 경고 표시, 출금 권한 없는 키 사용 권장
- **조회 전용 키**: 정상 등록, 주문 기능 비활성화 안내
- **거래 권한 키**: 정상 등록 (권장)
- **출금 포함 키**: 경고 후 사용자 확인 시 등록 허용

## 6.4 Circuit Breaker (거래소 장애 대응)

- **Closed (정상)**: 요청 통과, 실패율 모니터링
- **Open (차단)**: 연속 5회 실패 또는 30초 내 실패율 50% 초과 → 즉시 실패 반환, "거래소 연결 불안정" 알림
- **Half-Open (복구 시도)**: 30초 후 1건 테스트 → 성공 시 Closed, 실패 시 Open 유지
- 거래소별 독립 Circuit Breaker 운영

## 6.5 거래소별 Rate Limiting

| 거래소 | REST API 한도 | WebSocket 한도 |
|--------|-------------|---------------|
| Upbit | 초당 10회 (주문), 분당 600회 (조회) | 연결당 15개 마켓 구독 |
| CoinOne | 초당 10회 | 연결당 구독 제한 없음 |
| Coinbase | 분당 10,000회 | - |
| Binance | 분당 1,200회 (Weight 기반) | 연결당 200개 스트림 |

서버 측에서 거래소별 Rate Limiter를 운영하여 한도 초과 방지. Token Bucket 알고리즘 사용.

## 6.6 거래소 인증

| 거래소 | 인증 방식 |
|--------|-----------|
| Upbit | JWT (access key + secret key 서명) |
| CoinOne | HMAC-SHA512 |
| Coinbase | API Key + HMAC-SHA256 |
| Binance | API Key + HMAC-SHA256 query string |

## 6.7 개발자 문서

- Upbit: https://docs.upbit.com/kr/reference/api-overview
- CoinOne: https://docs.coinone.co.kr/reference/range-unit
- Coinbase: https://docs.cdp.coinbase.com/api-reference/v2/introduction
- Binance: https://www.binance.com/en/binance-api

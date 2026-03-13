---
name: v1-9 Upbit Provider 구현 완료
description: Upbit REST API JWT 인증, 시세/호가/캔들, WebSocket 스트리밍 구현 완료 현황
type: project
---

v1-9 exchange-api-expert 담당 서브태스크 모두 완료 (2026-03-13).

**Why:** python-backend-expert와 협업하여 스캐폴딩(ST1)을 바탕으로 JWT/mappers/WS 구현

**How to apply:** 후속 거래소(CoinOne, Coinbase, Binance) 구현 시 동일한 패턴 사용

## 구현된 파일
- `server/app/providers/upbit/auth.py` — UpbitJwtAuth (HS512 JWT, SHA-512 query_hash)
- `server/app/providers/upbit/constants.py` — URL, TIMEFRAME_TO_CANDLE_PATH, 에러 매핑
- `server/app/providers/upbit/mappers.py` — 순수함수 변환 (ticker/orderbook/candle/order/balance)
- `server/app/providers/__init__.py` — UpbitProvider import 추가

## 테스트 결과 (24/24 통과)
- test_auth.py: 7건
- test_mappers.py: 10건
- test_websocket.py: 7건

## 핵심 패턴
- `_market_to_symbol("KRW-BTC") → "BTC/KRW"` (linter가 헬퍼 함수로 리팩토링)
- provider.py의 `_request()` path: `/v1/ticker` (UPBIT_REST_BASE_URL + "/v1/ticker")
- float 절대 금지: `Decimal(str(raw_value))` 패턴 사용
- JWT: `jwt.encode(payload, secret, algorithm="HS512")` — secret은 Base64 인코딩 없이 그대로

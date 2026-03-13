---
name: v1-9 및 v1-10 Exchange Provider 구현 완료 현황
description: Upbit(v1-9)과 CoinOne(v1-10) Provider 구현 완료 상태 및 패턴 기록
type: project
---

## v1-9 Upbit Provider — 완료 (2026-03-13)

**Why:** python-backend-expert와 협업하여 스캐폴딩(ST1)을 바탕으로 JWT/mappers/WS 구현

구현 파일: `server/app/providers/upbit/` (auth.py, constants.py, mappers.py, provider.py, stream.py)

### 핵심 패턴
- `_market_to_symbol("KRW-BTC") → "BTC/KRW"` 변환
- JWT: `jwt.encode(payload, secret, algorithm="HS512")` — secret은 그대로 사용
- float 절대 금지: `Decimal(str(raw_value))` 패턴 사용
- 테스트: 24건 all passed

---

## v1-10 CoinOne Provider — 완료 (2026-03-13)

Branch: `feature/v1-10_coinone-exchange-provider`

구현 파일: `server/app/providers/coinone/` (auth.py, constants.py, mappers.py, provider.py, stream.py)

**Why:** 설계서 `docs/tasks/v1-10-coinone-exchange-provider-plan.md` 기반

### CoinOne 고유 특성 (Upbit과의 차이)
- **인증**: HMAC-SHA512 (JWT 아님) — `base64(json(body))` → `hmac(payload, secret)` → X-COINONE-PAYLOAD/SIGNATURE
- **Private API**: 전부 POST (GET/DELETE 없음)
- **에러 응답**: HTTP 200 + `result="error"` 패턴 — 반드시 처리 필수
- **SymbolMapper 마켓 코드**: 대문자 "BTC" (URL path에서만 `.lower()` 변환)
- **WS PING**: `{"request_type": "PING"}` 5분(300초) 간격
- **WS 구독**: 마켓별 개별 SUBSCRIBE 메시지 (Upbit 배열 방식과 다름)

### 수정된 공통 파일
- `server/app/providers/__init__.py` — CoinOneProvider import 추가
- `server/app/providers/types.py` — SymbolMapper COINONE 15개 마켓 (uppercase)
- `server/tests/unit/test_exchange_types.py` — coinone 마켓 코드 "BTC" 대문자로 수정

### 테스트: 40건 all passed
- test_auth.py (7건), test_mappers.py (10건), test_provider.py (15건), test_websocket.py (8건)

**How to apply:** 다음 거래소(Coinbase, Binance) 구현 시 동일 패턴(auth/constants/mappers/provider/stream) 적용.

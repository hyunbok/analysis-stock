# CoinTrader - API 설계

> 원본: docs/prd.md §5 기준. 최종 갱신: 2026-03-05

---

## 5.1 REST API

| 그룹 | 주요 엔드포인트 |
|------|----------------|
| 인증 | `POST /api/v1/auth/register, login, refresh, logout` / `POST /api/v1/auth/forgot-password, reset-password` / `GET,PUT /api/v1/auth/me` / `POST,DELETE /api/v1/auth/me/avatar` / `DELETE /api/v1/auth/me` (계정 삭제) |
| 소셜 인증 | `POST /api/v1/auth/social/google` / `POST /api/v1/auth/social/apple` |
| 클라이언트 | `POST,GET /api/v1/clients` / `DELETE /api/v1/clients/{id}` |
| 거래소 계정 | `POST,GET /api/v1/exchanges` / `PUT,DELETE /api/v1/exchanges/{id}` / `POST .../verify` |
| 코인 | `GET /api/v1/coins?q={keyword}` / `GET /api/v1/coins/{id}` |
| 관심 코인 | `GET,POST /api/v1/watchlist` / `DELETE /api/v1/watchlist/{id}` / `PUT .../reorder` |
| 주문 | `POST,GET /api/v1/orders` / `GET,DELETE /api/v1/orders/{id}` / `GET /api/v1/orders?status=open` / `POST /api/v1/orders/batch-cancel` |
| 자산 | `GET /api/v1/portfolio` (전체 요약) / `GET /api/v1/portfolio/{exchange_id}` (거래소별 상세) |
| AI 매매 | `POST,GET /api/v1/ai-trading/configs` / `PUT .../configs/{id}` / `PATCH .../configs/{id}/activation` / `PATCH /api/v1/ai-trading/master-switch` |
| AI 통계 | `GET /api/v1/ai-trading/logs` / `GET .../stats/daily` / `GET .../stats/total` |
| AI 백테스팅 (M9) | `POST /api/v1/ai-trading/backtest` (비동기 실행, 202 + task_id) / `GET .../backtest/{task_id}` (결과 폴링) |
| 가격 알림 | `POST,GET /api/v1/price-alerts` / `DELETE /api/v1/price-alerts/{id}` |
| 알림 (M9) | `GET /api/v1/notifications` / `PATCH .../notifications/{id}/read` / `POST .../mark-all-read` / `GET .../unread-count` / `DELETE .../notifications/{id}` / `PUT .../settings` |
| 2FA | `POST /api/v1/auth/2fa/setup` (TOTP QR) / `POST .../2fa/verify` / `POST .../2fa/disable` |
| 세션 관리 | `GET /api/v1/auth/sessions` / `DELETE .../sessions/{client_id}` / `POST /api/v1/auth/logout-all` |
| 앱 버전 | `GET /api/v1/app-version` |
| 헬스체크 | `GET /health` |

## 5.2 WebSocket

단일 연결 + 구독 메시지 방식으로 설계한다.

```
연결: ws://.../ws/v1?token={access_token}

구독 요청: { "action": "subscribe", "channel": "ticker", "exchange": "upbit", "market": "KRW-BTC" }
구독 해제: { "action": "unsubscribe", "channel": "ticker", "exchange": "upbit", "market": "KRW-BTC" }

채널 종류: ticker(시세), orderbook(호가), trades(체결), my-orders(내 주문)

연결 상태 UI: 연결됨(녹색), 연결 중(황색+스피너), 연결 끊김(적색+"재연결 중" 배너)
```

> 상세 요청/응답 스키마는 구현 태스크에서 정의한다.

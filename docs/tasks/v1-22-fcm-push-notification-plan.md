# v1-22: FCM 푸시 알림 시스템 구현 설계서

> **태스크**: v1:22 (M9)
> **브랜치**: `feature/v1-22_fcm-push-notification`
> **작성**: project-architect + code-architect
> **최종 갱신**: 2026-03-17

---

## 1. 현재 상태 (프로젝트 컨텍스트)

### v1-21에서 구현된 인프라

| 컴포넌트 | 위치 | 역할 | 상태 |
|----------|------|------|------|
| FCMService (스텁) | `services/fcm_service.py` | send_price_alert() 로깅만 수행 | **교체 대상** |
| NotificationService | `services/notification_service.py` | 알림 생성/조회/읽음/미읽 카운트 | 재사용 |
| NotificationRepository | `repositories/notification_repository.py` | MongoDB CRUD | 재사용 |
| Notification Document | `documents/notifications.py` | MongoDB TTL 90일 | 재사용 |
| Client 모델 | `models/user.py:107-142` | fcm_token(500), device_type(20) | 재사용 |
| ClientRepository | `repositories/client_repository.py` | Client CRUD (세션 관리) | **확장** |
| notifications.py API | `api/v1/notifications.py` | 알림 조회/읽음 | 재사용 |
| PriceAlertMonitor | `ws/price_alert_monitor.py` | 실시간 시세 → 가격 알림 트리거 | **수정** |
| RedisPublisher | `core/pubsub.py` | Pub/Sub 발행 | 재사용 |
| PubSubChannel.notification() | `core/redis_keys.py:251-253` | `ch:notification:{user_id}` | 재사용 |

### 기존 FCMService 스텁 분석

```python
# services/fcm_service.py — 현재 코드
class FCMService:
    def __init__(self, settings: Settings) -> None:
        self._enabled = bool(settings.FCM_SERVER_KEY)

    async def send_price_alert(
        self, fcm_token: str, coin_symbol: str,
        condition: str, target_price: Decimal, current_price: Decimal,
    ) -> bool:
        # TODO: FCM v1 API 또는 Firebase Admin SDK 구현
        return False
```

**문제점**:
1. 단일 토큰 대상 발송 — 멀티캐스트(복수 기기) 미지원
2. 가격 알림만 지원 — 주문 체결/AI 신호/시스템 알림 미지원
3. FCM_SERVER_KEY (레거시) — Firebase Admin SDK로 교체 필요
4. Rate Limiting / Dedup 없음

### 기존 DI 패턴 (deps.py)

```python
# 현재 FCMService DI
def get_fcm_service(settings: Settings = Depends(get_settings)) -> "FCMService":
    return FCMService(settings)

FCMServiceDep = Annotated["FCMService", Depends(get_fcm_service)]
```

---

## 2. 아키텍처 결정 사항

### ADR-022-1: Firebase Admin SDK 사용

**상태**: 승인됨
**맥락**: FCM 스텁을 실제 구현으로 교체 시 SDK 선택
**선택지**:
1. Firebase Admin SDK (firebase-admin) — 서비스 계정 기반, Python 공식 SDK
2. FCM HTTP v1 API 직접 호출 (httpx) — OAuth2 토큰 관리 필요
3. Legacy FCM Server Key — 2024년 6월 폐기 예정

**결정**: **Firebase Admin SDK (firebase-admin)**
**근거**:
- 공식 SDK가 OAuth2 토큰 갱신/캐싱 자동 처리
- `send_each()` 메서드로 멀티캐스트 + 개별 결과 확인 가능
- 실패 토큰 자동 식별 (InvalidRegistration, NotRegistered → 토큰 정리)
- Legacy Server Key는 Google이 2024년 6월 이후 신규 프로젝트에서 폐기

**영향**: `firebase-admin>=6.0` 의존성 추가, Settings 변경

### ADR-022-2: 인증 정보 — JSON 문자열 환경변수

**상태**: 승인됨 (code-architect 합의)
**맥락**: Firebase 서비스 계정 인증 방식
**선택지**:
1. Settings에 JSON 문자열 저장 (`FIREBASE_CREDENTIALS_JSON`)
2. 파일 경로 환경변수 (`GOOGLE_APPLICATION_CREDENTIALS` — Firebase 표준)
3. 파일 경로를 Settings에 저장 (`FIREBASE_CREDENTIALS_PATH`)

**결정**: **`FIREBASE_CREDENTIALS_JSON` (JSON 문자열, base64 인코딩 권장)**
**근거**:
- Docker/CI 환경에서 파일 마운트 없이 환경변수만으로 설정 가능
- base64 인코딩으로 JSON 이스케이프 문제 회피
- 빈 문자열이면 FCM 비활성화 (기존 스텁 동작 유지)
- 기존 `FCM_SERVER_KEY`는 하위 호환을 위해 유지 (deprecated)

### ADR-022-3: Firebase 초기화 — FCMService.__init__() 내부

**상태**: 승인됨 (code-architect 합의)
**맥락**: firebase_admin.initialize_app() 호출 시점
**선택지**:
1. lifespan에서 1회 초기화 → classmethod
2. FCMService.__init__()에서 처리 (중복 방지 포함)

**결정**: **FCMService.__init__()에서 처리**
**근거**:
- DI 팩토리가 매 요청 생성하지만, `firebase_admin._apps` 체크로 중복 초기화 방지
- lifespan에서 별도 초기화 불필요 → 코드 간결
- FCMService는 Settings만 의존 (저수준) — 기존 DI 패턴 유지

### ADR-022-4: 토큰 관리 — 기존 Client 모델 활용

**상태**: 승인됨
**맥락**: FCM 토큰 저장 위치 및 관리 방식
**선택지**:
1. 별도 `fcm_tokens` 테이블 생성
2. 기존 `clients` 테이블 fcm_token 컬럼 활용

**결정**: **기존 Client 모델 활용**
**근거**:
- Client 모델에 이미 `fcm_token: String(500)` 컬럼 존재
- Client = 기기 세션, FCM 토큰은 기기별 1개 → 자연스러운 1:1 매핑
- 별도 테이블 생성 불필요 — KISS 원칙

**토큰 등록/갱신 전략**:
- `POST /api/v1/clients` upsert: fingerprint로 기존 Client 조회 → 있으면 갱신, 없으면 생성
- FCM 발송 실패 (NotRegistered/UNREGISTERED) → 해당 Client의 fcm_token NULL로 클리어

### ADR-022-5: 서비스 2계층 분리 — FCMService + PushService

**상태**: 승인됨 (code-architect 제안)
**맥락**: FCM 발송과 알림 오케스트레이션의 책임 분리
**선택지**:
1. FCMService에 Rate Limit + Dedup + 알림 헬퍼 통합
2. FCMService(저수준 전송) + PushService(오케스트레이션) 분리

**결정**: **FCMService + PushService 2계층 분리**
**근거**:
- FCMService: 순수 Firebase 전송 책임 (send_notification, send_silent, send_multicast, unregister_token)
- PushService: Rate Limit + Dedup + NotificationService.create() + FCMService 호출 오케스트레이션
- 알림 유형별 헬퍼 (send_order_execution 등)는 PushService에 배치
- SRP 준수: FCMService는 Firebase API만, PushService는 비즈니스 오케스트레이션

**DI 의존 구조**:
```
PushService
  ├── FCMService (Settings)
  ├── NotificationService (NotificationRepository, Redis, RedisPublisher)
  ├── ClientRepository (AsyncSession)
  └── Redis
```

### ADR-022-6: Rate Limiting — Redis 고정 윈도우

**상태**: 승인됨
**결정**: PushService 내부에서 `fcm:rate:{user_id}` Redis 키로 분당 10건 제한
- INCR + EXPIRE(60, NX) 패턴
- 초과 시 FCM 발송 스킵 (에러 아닌 로깅 + 드롭, fire-and-forget)

### ADR-022-7: Dedup — dedup_key 기반 (TTL 1시간)

**상태**: 승인됨 (code-architect 합의: TTL 60초 → 3600초)
**결정**: `fcm:dedup:{user_id}:{hash}` Redis 키 (TTL 3600초 = 1시간)
- dedup_key = 호출자가 제공 (예: `"price_alert:{alert_id}"`, `"order:{order_id}"`)
- dedup_key == None이면 dedup 스킵
- hash = SHA-256(dedup_key)[:16]
- SETNX: 성공 시 발송, 실패 시 스킵

### ADR-022-8: Silent Push

**상태**: 승인됨
**결정**: FCM `data`-only 메시지 (notification 필드 제외)
- iOS: `apns-push-type: background`, `apns-priority: 5`
- Android: `priority: normal`
- 사용처: 백그라운드 데이터 동기화, 배지 카운트 업데이트

---

## 3. 시스템 아키텍처

### 3.1 전체 흐름도

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          Flutter Client                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────────────┐  │
│  │ FCM Token    │  │ 알림 설정 UI │  │ FCM 수신 (foreground/bg)    │  │
│  │ 등록/갱신    │  │              │  │ → local notification        │  │
│  └──────┬───────┘  └──────────────┘  └──────────────────────────────┘  │
└─────────┼──────────────────────────────────────────────────────────────┘
          │ POST /api/v1/clients (upsert)
┌─────────▼──────────────────────────────────────────────────────────────┐
│                          FastAPI Server                                  │
│                                                                          │
│  ┌────────────────────────────────────────────────────────┐             │
│  │                 PushService (오케스트레이터)             │             │
│  │  Rate Limit 체크 → Dedup 체크                           │             │
│  │  → NotificationService.create_notification()            │             │
│  │  → ClientRepository.get_by_user() → FCM 토큰 수집       │             │
│  │  → FCMService.send_multicast()                          │             │
│  │                                                          │             │
│  │  send_order_execution()                                  │             │
│  │  send_ai_trading_signal()                                │             │
│  │  send_price_alert_notification()                         │             │
│  │  send_system_alert()                                     │             │
│  └─────────────────┬────────────────────────────────────────┘             │
│                     │                                                     │
│  ┌─────────────────▼──────────────────────┐                              │
│  │          FCMService (저수준 전송)       │                              │
│  │  firebase_admin.initialize_app()       │                              │
│  │  send_notification() — 단건            │                              │
│  │  send_multicast() — 멀티캐스트         │                              │
│  │  send_silent() — data-only             │                              │
│  │  unregister_token() — 토큰 무효화      │                              │
│  └─────────────────┬──────────────────────┘                              │
│                     │                                                     │
│  호출처:            │                                                     │
│  ┌───────────────┐  │  ┌───────────────┐  ┌───────────────┐             │
│  │PriceAlert     │──┘  │OrderService   │  │Celery AI Task │             │
│  │Service        │     │(주문 체결)    │  │(AI 신호)      │             │
│  └───────────────┘     └───────┬───────┘  └───────┬───────┘             │
│                                │                   │                     │
│                      push_service.send_xxx()  push_service.send_xxx()   │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘
          │                    │                 │
  ┌───────▼──────┐    ┌───────▼──────┐   ┌──────▼──────┐
  │ Firebase     │    │ Redis        │   │ PostgreSQL  │
  │ Cloud Msg    │    │ rate/dedup   │   │ clients     │
  └──────────────┘    └──────────────┘   └─────────────┘
```

### 3.2 데이터 흐름

```
FCM 토큰 등록:  Flutter → POST /clients → fingerprint upsert → Client.fcm_token 저장
FCM 토큰 갱신:  Flutter 앱 시작 → onTokenRefresh → POST /clients (기존 Client 갱신)

주문 체결 알림: OrderService → push_service.send_order_execution()
                → Rate Limit → Dedup → NotificationService.create()
                → ClientRepo.get_by_user() → FCMService.send_multicast()
AI 매매 신호:   Celery task → push_service.send_ai_trading_signal()
가격 알림:      PriceAlertService._trigger_alert() → push_service.send_price_alert_notification()
시스템 알림:    Circuit Breaker/Health → push_service.send_system_alert()
```

### 3.3 시퀀스 다이어그램 — 주문 체결 알림 발송

```
OrderService              PushService           NotificationService    FCMService         Firebase
    │                         │                       │                    │                  │
    │  주문 체결 감지          │                       │                    │                  │
    ├──send_order_execution()▶│                       │                    │                  │
    │                         │──rate_limit_check()   │                    │                  │
    │                         │  Redis INCR           │                    │                  │
    │                         │──dedup_check()        │                    │                  │
    │                         │  Redis SETNX          │                    │                  │
    │                         │                       │                    │                  │
    │                         ├──create_notification()▶│                    │                  │
    │                         │                       │──MongoDB INSERT──▶ │                  │
    │                         │                       │──Redis INCR────▶   │                  │
    │                         │                       │──Pub/Sub publish──▶│                  │
    │                         │                       │                    │                  │
    │                         │──get_by_user()───────▶│                    │                  │
    │                         │◀─ tokens ────────────│                    │                  │
    │                         │                       │                    │                  │
    │                         ├──send_multicast()────────────────────────▶│                  │
    │                         │                       │                    │──send_each()───▶│
    │                         │                       │                    │◀─ responses ───│
    │                         │                       │                    │                  │
    │                         │                       │                    │──cleanup tokens  │
    │◀────── bool ────────────│                       │                    │                  │
```

### 3.4 시퀀스 다이어그램 — FCM 토큰 등록 (POST /clients upsert)

```
Flutter App                FastAPI                  ClientRepository      PostgreSQL
    │                         │                           │                   │
    │  앱 시작/토큰 갱신       │                           │                   │
    │  FirebaseMessaging      │                           │                   │
    │  .getToken()            │                           │                   │
    │                         │                           │                   │
    ├──POST /clients─────────▶│                           │                   │
    │  X-Device-Fingerprint   │                           │                   │
    │  {device_type, fcm_token│                           │                   │
    │   device_name?}         │                           │                   │
    │                         │──get_by_user_and_────────▶│                   │
    │                         │  fingerprint()            │──SELECT─────────▶│
    │                         │                           │◀─ Client/None ──│
    │                         │                           │                   │
    │                         │ [기존 Client 존재]         │                   │
    │                         │──update_fcm_token()──────▶│──UPDATE─────────▶│
    │                         │                           │                   │
    │                         │ [없으면 신규 생성]         │                   │
    │                         │──create()────────────────▶│──INSERT─────────▶│
    │                         │                           │                   │
    │◀── 200/201 ─────────────│                           │                   │
```

---

## 4. Settings 변경

```python
# core/config.py — 변경 사항

class Settings(BaseSettings):
    # FCM Push Notifications
    FCM_SERVER_KEY: str | None = None          # deprecated (v1-21 하위 호환)
    FIREBASE_CREDENTIALS_JSON: str = ""        # 서비스 계정 JSON 문자열 (빈 문자열=비활성)

    # FCM Rate Limiting
    FCM_RATE_LIMIT_PER_MINUTE: int = 10        # 사용자별 분당 최대 발송 건수
```

---

## 5. 서비스 계층 설계

### 5.1 FCMService — 저수준 Firebase 전송

```python
# services/fcm_service.py — 전체 교체

class FCMService:
    """Firebase Cloud Messaging 저수준 전송 서비스.

    Settings만 의존. firebase_admin 초기화 + 개별/멀티캐스트/silent 전송.
    """

    def __init__(self, settings: Settings) -> None:
        self._enabled = False
        if settings.FIREBASE_CREDENTIALS_JSON:
            import json
            import firebase_admin
            from firebase_admin import credentials
            cred_dict = json.loads(settings.FIREBASE_CREDENTIALS_JSON)
            cred = credentials.Certificate(cred_dict)
            if not firebase_admin._apps:
                firebase_admin.initialize_app(cred)
            self._enabled = True

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    async def send_notification(
        self,
        fcm_token: str,
        title: str,
        body: str,
        data: dict[str, str] | None = None,
        *,
        collapse_key: str | None = None,
    ) -> bool:
        """알림 + 데이터 푸시. 실패 시 False (fire-and-forget)."""
        if not self._enabled:
            logger.debug("FCM disabled, skipping notification push")
            return False
        from firebase_admin import messaging

        msg = messaging.Message(
            notification=messaging.Notification(title=title, body=body),
            data=data or {},
            token=fcm_token,
            android=messaging.AndroidConfig(
                priority="high",
                collapse_key=collapse_key,
            ),
            apns=messaging.APNSConfig(
                payload=messaging.APNSPayload(
                    aps=messaging.Aps(sound="default")
                )
            ),
        )
        try:
            await asyncio.to_thread(messaging.send, msg)
            return True
        except Exception:
            logger.exception("FCM send_notification failed: token=%s", fcm_token[:8])
            return False

    async def send_silent(
        self,
        fcm_token: str,
        data: dict[str, str],
    ) -> bool:
        """data-only silent push. 실패 시 False."""
        if not self._enabled:
            return False
        from firebase_admin import messaging

        msg = messaging.Message(
            data=data,
            token=fcm_token,
            android=messaging.AndroidConfig(priority="normal"),
            apns=messaging.APNSConfig(
                headers={"apns-push-type": "background", "apns-priority": "5"}
            ),
        )
        try:
            await asyncio.to_thread(messaging.send, msg)
            return True
        except Exception:
            logger.exception("FCM send_silent failed: token=%s", fcm_token[:8])
            return False

    async def send_multicast(
        self,
        fcm_tokens: list[str],
        title: str,
        body: str,
        data: dict[str, str] | None = None,
    ) -> int:
        """멀티캐스트 발송. 성공 건수 반환. 실패 토큰 목록도 반환."""
        if not self._enabled or not fcm_tokens:
            return 0
        from firebase_admin import messaging

        messages = []
        for token in fcm_tokens:
            msg = messaging.Message(
                notification=messaging.Notification(title=title, body=body),
                data=data or {},
                token=token,
                android=messaging.AndroidConfig(priority="high"),
                apns=messaging.APNSConfig(
                    payload=messaging.APNSPayload(
                        aps=messaging.Aps(sound="default")
                    )
                ),
            )
            messages.append(msg)

        try:
            response = await asyncio.to_thread(messaging.send_each, messages)
        except Exception:
            logger.exception("FCM send_multicast failed for %d tokens", len(fcm_tokens))
            return 0

        # 실패 토큰 로깅
        success_count = response.success_count
        for i, send_response in enumerate(response.responses):
            if not send_response.success:
                error = send_response.exception
                error_code = getattr(error, "code", "unknown") if error else "unknown"
                logger.warning(
                    "FCM multicast failed: token=%s error=%s",
                    fcm_tokens[i][:8], error_code,
                )
        return success_count

    async def unregister_token(self, fcm_token: str) -> None:
        """토큰 무효화 (fire-and-forget)."""
        # Firebase Admin SDK는 토큰 무효화 API를 직접 제공하지 않음
        # 서버에서는 DB에서 토큰을 제거하는 것으로 충분
        pass

    # ── 하위 호환 메서드 (v1-21) ─────────────────────────────────────────

    async def send_price_alert(
        self,
        fcm_token: str,
        coin_symbol: str,
        condition: str,
        target_price,
        current_price,
    ) -> bool:
        """v1-21 하위 호환. send_notification()으로 위임."""
        condition_kr = "이상" if condition == "above" else "이하"
        title = f"{coin_symbol} 목표가 도달"
        body = f"{target_price}원 {condition_kr} | 현재: {current_price}원"
        data = {
            "type": "price_alert",
            "coin_symbol": coin_symbol,
            "condition": condition,
            "target_price": str(target_price),
            "current_price": str(current_price),
        }
        return await self.send_notification(fcm_token, title, body, data)
```

### 5.2 PushService — 오케스트레이션 계층

```python
# services/push_service.py — 신규

class PushService:
    """FCM 푸시 알림 오케스트레이터.

    Rate Limiting + Dedup + NotificationService 저장 + FCMService 멀티캐스트.
    모든 알림 유형의 진입점.
    """

    def __init__(
        self,
        fcm_service: FCMService,
        notification_service: NotificationService,
        client_repo: ClientRepository,
        redis: Redis,
        settings: Settings,
    ) -> None:
        self._fcm = fcm_service
        self._notification = notification_service
        self._client_repo = client_repo
        self._redis = redis
        self._rate_limit = settings.FCM_RATE_LIMIT_PER_MINUTE

    async def send_to_user(
        self,
        user_id: uuid.UUID,
        notification_type: str,
        title: str,
        body: str,
        data: dict | None = None,
        *,
        dedup_key: str | None = None,
        silent: bool = False,
    ) -> bool:
        """사용자에게 알림 발송 (핵심 메서드).

        1. Rate Limit 체크 (분당 10건)
        2. Dedup 체크 (1시간 내 동일 dedup_key → skip)
        3. NotificationService.create_notification() — MongoDB 저장 + Redis INCR + Pub/Sub
        4. ClientRepository.get_by_user() → 활성 FCM 토큰 수집
        5. FCMService.send_multicast() — 복수 기기 발송
        """
        # 1. Rate Limit
        if not await self._check_rate_limit(user_id):
            logger.info("FCM rate limited: user=%s", user_id)
            return False

        # 2. Dedup
        if dedup_key and not await self._check_dedup(user_id, dedup_key):
            logger.debug("FCM dedup hit: user=%s key=%s", user_id, dedup_key)
            return False

        # 3. MongoDB 알림 저장 + Redis + Pub/Sub
        if not silent:
            str_data = {k: str(v) for k, v in data.items()} if data else None
            await self._notification.create_notification(
                user_id=user_id,
                type=notification_type,
                title=title,
                body=body,
                data=str_data,
            )

        # 4. FCM 토큰 수집
        clients = await self._client_repo.get_by_user(user_id)
        fcm_tokens = [c.fcm_token for c in clients if c.fcm_token]
        if not fcm_tokens:
            return True  # 알림 저장은 성공, FCM 기기 없음

        # 5. FCM 발송
        str_data = {k: str(v) for k, v in data.items()} if data else None
        if silent:
            for token in fcm_tokens:
                await self._fcm.send_silent(token, str_data or {})
        else:
            await self._fcm.send_multicast(fcm_tokens, title, body, str_data)

        return True

    # ── 알림 유형별 헬퍼 ─────────────────────────────────────────────────

    async def send_order_execution(
        self,
        user_id: uuid.UUID,
        order_id: str,
        coin_symbol: str,
        side: str,
        filled_qty: Decimal,
        price: Decimal,
    ) -> bool:
        """주문 체결 알림."""
        side_kr = "매수" if side == "buy" else "매도"
        title = f"{coin_symbol} {side_kr} 체결 완료"
        body = f"{filled_qty} {coin_symbol.split('/')[0]} @ {price:,}원"
        data = {
            "type": "order_execution",
            "order_id": order_id,
            "coin_symbol": coin_symbol,
            "side": side,
            "filled_qty": str(filled_qty),
            "price": str(price),
        }
        return await self.send_to_user(
            user_id, "order_execution", title, body, data,
            dedup_key=f"order:{order_id}",
        )

    async def send_ai_trading_signal(
        self,
        user_id: uuid.UUID,
        signal_type: str,
        coin_symbol: str,
        reason: str,
    ) -> bool:
        """AI 매매 신호 알림."""
        type_kr = {"BUY": "매수", "SELL": "매도", "HOLD": "관망"}.get(signal_type, signal_type)
        title = f"AI {type_kr} 신호 | {coin_symbol}"
        body = reason
        data = {
            "type": "ai_trading_signal",
            "signal_type": signal_type,
            "coin_symbol": coin_symbol,
        }
        return await self.send_to_user(
            user_id, "ai_trading_signal", title, body, data,
            dedup_key=f"ai_signal:{coin_symbol}:{signal_type}",
        )

    async def send_price_alert_notification(
        self,
        user_id: uuid.UUID,
        alert_id: str,
        coin_symbol: str,
        condition: str,
        target_price: Decimal,
        current_price: Decimal,
    ) -> bool:
        """가격 알림."""
        condition_kr = "이상" if condition == "above" else "이하"
        title = f"{coin_symbol} 목표가 도달"
        body = f"{target_price:,}원 {condition_kr} | 현재: {current_price:,}원"
        data = {
            "type": "price_alert",
            "alert_id": alert_id,
            "coin_symbol": coin_symbol,
            "condition": condition,
            "target_price": str(target_price),
            "current_price": str(current_price),
        }
        return await self.send_to_user(
            user_id, "price_alert", title, body, data,
            dedup_key=f"price_alert:{alert_id}",
        )

    async def send_system_alert(
        self,
        user_id: uuid.UUID,
        message: str,
        *,
        severity: str = "info",
    ) -> bool:
        """시스템 알림."""
        title_map = {
            "info": "시스템 안내",
            "warning": "시스템 경고",
            "critical": "긴급 알림",
        }
        title = title_map.get(severity, "시스템 알림")
        data = {
            "type": "system_alert",
            "severity": severity,
        }
        return await self.send_to_user(
            user_id, "system_alert", title, message, data,
            dedup_key=f"system:{severity}:{hashlib.sha256(message.encode()).hexdigest()[:8]}",
        )

    # ── 내부 메서드 ──────────────────────────────────────────────────────

    async def _check_rate_limit(self, user_id: uuid.UUID) -> bool:
        """분당 N건 제한. True=허용, False=초과."""
        key = RedisKey.fcm_rate(str(user_id))
        count = await self._redis.incr(key)
        await self._redis.expire(key, RedisTTL.FCM_RATE_WINDOW, nx=True)
        return count <= self._rate_limit

    async def _check_dedup(self, user_id: uuid.UUID, dedup_key: str) -> bool:
        """1시간 내 동일 dedup_key 중복 방지. True=발송 가능, False=중복."""
        dedup_hash = hashlib.sha256(dedup_key.encode()).hexdigest()[:16]
        key = RedisKey.fcm_dedup(str(user_id), dedup_hash)
        acquired = await self._redis.set(key, "1", nx=True, ex=RedisTTL.FCM_DEDUP)
        return bool(acquired)
```

---

## 6. API 엔드포인트 상세 규격

### 6.1 Client 관리 API — `api/v1/clients.py`

라우터 등록:
```python
# api/v1/__init__.py
router.include_router(clients_router, prefix="/clients", tags=["clients"])
```

#### POST /api/v1/clients — FCM 토큰 등록/갱신 (upsert)

```
Headers:
  Authorization: Bearer {access_token}
  X-Device-Fingerprint: "sha256-fingerprint" (선택)

Body:
{
  "device_type": "ios" | "android" | "web",
  "device_name": "iPhone 16 Pro",   // optional
  "fcm_token": "fMg7x...dKj2"      // optional (없으면 FCM 비활성 기기)
}

Response 200 (기존 Client 갱신): ApiResponse[ClientResponse]
Response 201 (신규 Client 생성): ApiResponse[ClientResponse]
{
  "data": {
    "client_id": "uuid",
    "device_type": "ios",
    "device_name": "iPhone 16 Pro",
    "fcm_token": "fMg7x...",
    "is_active": true,
    "created_at": "2026-03-17T10:00:00Z",
    "last_active_at": "2026-03-17T10:00:00Z"
  }
}

Errors:
  401 UNAUTHORIZED — 미인증
```

**로직**:
1. `X-Device-Fingerprint` 헤더에서 fingerprint 추출
2. `ClientRepository.get_by_user_and_fingerprint()` → 기존 Client 조회
3. 존재 시: `update_fcm_token()` (fcm_token, device_name, user_agent, ip_address, last_active_at 갱신) → 200
4. 없을 시: `ClientRepository.create()` → 201

#### GET /api/v1/clients — 사용자 클라이언트 목록

```
Headers: Authorization: Bearer {access_token}

Response 200: ApiResponse[ClientListResponse]
{
  "data": {
    "clients": [
      {
        "client_id": "uuid",
        "device_type": "ios",
        "device_name": "iPhone 16 Pro",
        "fcm_token": "fMg7x...",
        "is_active": true,
        "created_at": "...",
        "last_active_at": "..."
      }
    ]
  }
}
```

#### DELETE /api/v1/clients/{client_id} — 클라이언트 제거

```
Headers: Authorization: Bearer {access_token}

Response 204: No Content

Errors:
  404 CLIENT_NOT_FOUND
  403 CLIENT_ACCESS_DENIED
```

**로직**:
1. `ClientRepository.get_by_id()` → 없으면 404
2. 소유자 확인 → 불일치 시 403
3. `ClientRepository.deactivate()` (soft delete)

### 6.2 기존 알림 API (변경 없음)

v1-21에서 구현된 알림 API는 변경 없이 재사용:
- `GET /api/v1/notifications` — 목록 조회 (type 필터로 알림 유형별 조회)
- `GET /api/v1/notifications/unread-count` — 미읽 카운트
- `PATCH /api/v1/notifications/{id}/mark-read` — 읽음 처리
- `PATCH /api/v1/notifications/mark-all-read` — 전체 읽음

---

## 7. 스키마 정의

### 7.1 `schemas/client.py` (신규)

```python
from __future__ import annotations
import uuid
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field

class ClientRegisterRequest(BaseModel):
    device_type: Literal["ios", "android", "web"]
    device_name: str | None = Field(default=None, max_length=200)
    fcm_token: str | None = Field(default=None, max_length=500)

class ClientResponse(BaseModel):
    client_id: uuid.UUID
    device_type: str
    device_name: str | None
    fcm_token: str | None
    is_active: bool
    created_at: datetime
    last_active_at: datetime | None

class ClientListResponse(BaseModel):
    clients: list[ClientResponse]
```

---

## 8. 알림 유형별 메시지 포맷

### 8.1 FCM 메시지 구조

```python
# 일반 알림 (notification + data)
{
    "notification": {"title": "...", "body": "..."},
    "data": {
        "type": "order_execution | ai_trading_signal | price_alert | system_alert",
        # 유형별 추가 필드 (모든 값 str)
    },
    "android": {"priority": "high"},
    "apns": {"payload": {"aps": {"sound": "default"}}}
}

# Silent push (data-only)
{
    "data": {"type": "badge_update", "unread_count": "5"},
    "android": {"priority": "normal"},
    "apns": {"headers": {"apns-push-type": "background", "apns-priority": "5"}}
}
```

### 8.2 유형별 상세

| 유형 | title | body | data 필드 | dedup_key |
|------|-------|------|-----------|-----------|
| order_execution | "BTC/KRW 매수 체결 완료" | "0.1 BTC @ 50,000,000원" | type, order_id, coin_symbol, side, filled_qty, price | `order:{order_id}` |
| ai_trading_signal | "AI 매수 신호 \| BTC/KRW" | "추세 장세 감지" | type, signal_type, coin_symbol | `ai_signal:{coin}:{type}` |
| price_alert | "BTC/KRW 목표가 도달" | "85,000,000원 이상 \| 현재: 85,100,000원" | type, alert_id, coin_symbol, condition, target_price, current_price | `price_alert:{alert_id}` |
| system_alert | "시스템 경고" | "Upbit 연결 5분째 실패" | type, severity | `system:{severity}:{hash}` |

### 8.3 MongoDB Notification type 값

기존 + 신규:
- `price_alert` (기존 v1-21)
- `order_execution` (신규)
- `ai_trading_signal` (신규)
- `system_alert` (신규)

---

## 9. Rate Limiting 설계

### 9.1 Redis 키 패턴

```python
# core/redis_keys.py — 추가

class RedisTTL:
    FCM_RATE_WINDOW = 60        # 1분 (Rate Limiting 윈도우)
    FCM_DEDUP = 3600            # 1시간 (중복 알림 방지)

class RedisKey:
    @staticmethod
    def fcm_rate(user_id: str) -> str:
        """FCM 발송 분당 제한 카운터."""
        return f"fcm:rate:{user_id}"

    @staticmethod
    def fcm_dedup(user_id: str, dedup_hash: str) -> str:
        """FCM 중복 알림 방지 (SETNX)."""
        return f"fcm:dedup:{user_id}:{dedup_hash}"
```

### 9.2 Rate Limiting 흐름 (PushService 내부)

```
push_service.send_to_user() 호출
    │
    ├── _check_rate_limit(user_id)
    │     Redis INCR fcm:rate:{user_id}
    │     EXPIRE 60 (NX)
    │     count > 10 → 로깅 + return False (드롭)
    │
    ├── _check_dedup(user_id, dedup_key)
    │     SHA-256(dedup_key)[:16] → hash
    │     Redis SETNX fcm:dedup:{user_id}:{hash} EX 3600
    │     실패 → 로깅 + return False (중복)
    │
    ├── NotificationService.create_notification()
    │     MongoDB INSERT + Redis INCR + Pub/Sub
    │
    └── FCMService.send_multicast(tokens, title, body, data)
```

### 9.3 제한값

| 항목 | 값 | 설정 키 |
|------|-----|---------|
| 사용자별 분당 최대 | 10건 | FCM_RATE_LIMIT_PER_MINUTE |
| 중복 알림 방지 TTL | 3600초 (1시간) | RedisTTL.FCM_DEDUP |

---

## 10. Silent Push 설계

### 10.1 사용 시나리오

- **배지 카운트 업데이트**: 서버에서 미읽 카운트 변경 시 → silent push → 앱이 배지 갱신
- **백그라운드 데이터 동기화**: 포트폴리오 갱신 알림 등

### 10.2 FCMService.send_silent() 구조

```python
# iOS: apns-push-type: background, apns-priority: 5 (절전 모드 존중)
# Android: priority: normal (시스템이 배치 처리 가능)
# notification 필드 없음 → 시스템 트레이에 표시 안 됨

messaging.Message(
    token=fcm_token,
    data={"type": "badge_update", "unread_count": "5"},
    apns=messaging.APNSConfig(
        headers={"apns-push-type": "background", "apns-priority": "5"}
    ),
    android=messaging.AndroidConfig(priority="normal"),
)
```

### 10.3 PushService silent 호출

```python
# silent=True → NotificationService 저장 스킵, FCMService.send_silent() 사용
await push_service.send_to_user(
    user_id=user_id,
    notification_type="badge_update",
    title="", body="",
    data={"type": "badge_update", "unread_count": str(count)},
    silent=True,
)
```

---

## 11. ClientRepository 확장

### 11.1 신규 메서드

```python
# repositories/client_repository.py — 추가

async def update_fcm_token(
    self,
    client_id: uuid.UUID,
    fcm_token: str | None,
    *,
    device_name: str | None = None,
    user_agent: str | None = None,
    ip_address: str | None = None,
) -> Client | None:
    """FCM 토큰 및 메타데이터 업데이트 + last_active_at 갱신."""
    values = {
        "fcm_token": fcm_token,
        "last_active_at": datetime.now(timezone.utc),
    }
    if device_name is not None:
        values["device_name"] = device_name
    if user_agent is not None:
        values["user_agent"] = user_agent
    if ip_address is not None:
        values["ip_address"] = ip_address

    await self._db.execute(
        update(Client).where(Client.id == client_id).values(**values)
    )
    await self._db.flush()
    return await self.get_by_id(client_id)

async def get_active_fcm_tokens(self, user_id: uuid.UUID) -> list[tuple[uuid.UUID, str]]:
    """사용자의 활성 기기 FCM 토큰 목록 조회.
    Returns: [(client_id, fcm_token), ...] — fcm_token이 NULL인 기기 제외."""
    result = await self._db.execute(
        select(Client.id, Client.fcm_token).where(
            Client.user_id == user_id,
            Client.is_active.is_(True),
            Client.fcm_token.isnot(None),
        )
    )
    return [(row[0], row[1]) for row in result.all()]

async def clear_fcm_token_by_value(self, fcm_token: str) -> None:
    """실패한 FCM 토큰 NULL 처리 (ix_clients_fcm_token 인덱스 활용)."""
    await self._db.execute(
        update(Client)
        .where(Client.fcm_token == fcm_token)
        .values(fcm_token=None)
    )
    await self._db.flush()
```

---

## 12. 에러 팩토리

```python
# core/exceptions.py — 추가

class ClientErrors:
    """클라이언트(기기 세션) 도메인 에러 팩토리."""

    @staticmethod
    def not_found() -> AppError:
        return AppError("CLIENT_NOT_FOUND", "클라이언트를 찾을 수 없습니다.", 404)

    @staticmethod
    def access_denied() -> AppError:
        return AppError("CLIENT_ACCESS_DENIED", "접근 권한이 없습니다.", 403)
```

FCM 발송 실패는 AppError 발생 없이 로깅만 (fire-and-forget 원칙).

---

## 13. DI 컨테이너 (`core/deps.py`)

```python
# ── 기존 get_fcm_service 유지 (Settings만 의존) ──────────────────────────

def get_fcm_service(
    settings: Settings = Depends(get_settings),
) -> "FCMService":
    from app.services.fcm_service import FCMService
    return FCMService(settings)

# ── PushService 신규 ─────────────────────────────────────────────────────

def get_push_service(
    fcm_service: "FCMService" = Depends(get_fcm_service),
    notification_service: "NotificationService" = Depends(get_notification_service),
    client_repo: ClientRepository = Depends(get_client_repository),
    redis: Redis = Depends(get_redis),
    settings: Settings = Depends(get_settings),
) -> "PushService":
    from app.services.push_service import PushService
    return PushService(fcm_service, notification_service, client_repo, redis, settings)

# ── Type aliases ─────────────────────────────────────────────────────────

PushServiceDep = Annotated["PushService", Depends(get_push_service)]
```

---

## 14. 기존 코드 수정 사항

### 14.1 PriceAlertService — PushService로 교체

```python
# services/price_alert_service.py — _trigger_alert() 변경

# 기존: client_repo.get_by_user() → 토큰 루프 → fcm_service.send_price_alert(fcm_token, ...)
# 변경: push_service.send_price_alert_notification(user_id, ...)

class PriceAlertService:
    def __init__(
        self,
        alert_repo: PriceAlertRepository,
        coin_repo: CoinRepository,
        exchange_account_repo: ExchangeAccountRepository,
        notification_service: NotificationService,
        push_service: PushService,       # ← FCMService + ClientRepository 대체
        redis: Redis,
    ) -> None: ...

    async def _trigger_alert(self, alert, current_price, coin_symbol, exchange_type):
        # a. Redis SETNX + PG UPDATE (기존 동일)
        # b. NotificationService.create_notification() 제거
        #    → PushService.send_price_alert_notification()이 내부에서 호출

        # c. 가격 알림 전용 미읽 카운트 INCR (기존 동일)

        # d. FCM 발송 (변경) — PushService가 알림 저장 + FCM 발송 통합
        try:
            await self._push_service.send_price_alert_notification(
                user_id=alert.user_id,
                alert_id=str(alert.id),
                coin_symbol=coin_symbol,
                condition=alert.condition,
                target_price=alert.target_price,
                current_price=current_price,
            )
        except Exception:
            logger.exception("Push send failed for alert %s", alert.id)
```

**주요 변경**:
- `fcm_service` + `client_repo` → `push_service` 1개로 교체
- `notification_service.create_notification()` 직접 호출 제거 (PushService 내부에서 수행)
- 가격 알림 전용 미읽 카운트 Redis INCR은 PriceAlertService에서 유지 (PushService 범위 밖)

### 14.2 PriceAlertMonitor — FCMService → PushService 교체

```python
# ws/price_alert_monitor.py — _process_with_session() 변경

# PushService 인스턴스 생성
push_svc = PushService(fcm_svc, notification_svc, client_repo, self._main_redis, self._settings)

svc = PriceAlertService(
    alert_repo, coin_repo, exchange_account_repo,
    notification_svc, push_svc, self._main_redis,
)
```

### 14.3 deps.py — get_price_alert_service() 수정

```python
def get_price_alert_service(
    alert_repo = Depends(get_price_alert_repository),
    coin_repo = Depends(get_coin_repository),
    exchange_account_repo = Depends(get_exchange_account_repository),
    notification_service = Depends(get_notification_service),
    push_service = Depends(get_push_service),      # ← FCMService + ClientRepository 대체
    redis = Depends(get_redis),
) -> "PriceAlertService":
    return PriceAlertService(
        alert_repo, coin_repo, exchange_account_repo,
        notification_service, push_service, redis,
    )
```

---

## 15. 구현 파일 목록

### 신규 생성 파일

| # | 파일 | 역할 |
|---|------|------|
| 1 | `server/app/api/v1/clients.py` | Client CRUD API (POST/GET/DELETE) |
| 2 | `server/app/schemas/client.py` | ClientRegisterRequest, ClientResponse, ClientListResponse |
| 3 | `server/app/services/push_service.py` | Rate Limit + Dedup + 알림 타입별 발송 오케스트레이터 |

### 수정 파일

| # | 파일 | 변경 내용 |
|---|------|-----------|
| 1 | `server/app/services/fcm_service.py` | Firebase Admin SDK 기반 재구현 (저수준 전송) |
| 2 | `server/app/core/config.py` | FIREBASE_CREDENTIALS_JSON, FCM_RATE_LIMIT_PER_MINUTE |
| 3 | `server/app/core/redis_keys.py` | RedisKey.fcm_rate(), fcm_dedup() + RedisTTL 추가 |
| 4 | `server/app/core/exceptions.py` | ClientErrors 추가 |
| 5 | `server/app/core/deps.py` | get_push_service(), PushServiceDep 추가, get_price_alert_service() 수정 |
| 6 | `server/app/repositories/client_repository.py` | update_fcm_token(), get_active_fcm_tokens(), clear_fcm_token_by_value() |
| 7 | `server/app/api/v1/__init__.py` | clients 라우터 등록 |
| 8 | `server/app/services/price_alert_service.py` | PushService로 교체 (fcm_service + client_repo 제거) |
| 9 | `server/app/ws/price_alert_monitor.py` | PushService 생성 반영 |
| 10 | `server/requirements.txt` | firebase-admin>=6.0 추가 |

### 테스트 파일

| # | 파일 | 범위 | 예상 건수 |
|---|------|------|----------|
| 1 | `server/tests/unit/test_fcm_service.py` | Firebase 전송 mock 테스트 | ~12건 |
| 2 | `server/tests/unit/test_push_service.py` | Rate Limit + Dedup + 오케스트레이션 | ~16건 |
| 3 | `server/tests/unit/test_client_repository_fcm.py` | update/get/clear FCM 토큰 | ~8건 |
| 4 | `server/tests/integration/test_clients_api.py` | POST/GET/DELETE /clients API | ~10건 |
| 5 | `server/tests/integration/test_push_notification_flow.py` | 알림 유형별 발송 E2E | ~8건 |

---

## 16. 의존성 및 구현 순서

```
ST1: Settings 변경 + Redis 키/TTL + ClientErrors + schemas/client.py
  │  (config.py, redis_keys.py, exceptions.py, schemas/client.py)
  ↓
ST2: FCMService 재구현 (Firebase Admin SDK, 저수준 전송)
  │  (fcm_service.py, requirements.txt)
  ↓
ST3: ClientRepository 확장 + Client API (POST/GET/DELETE)
  │  (client_repository.py, api/v1/clients.py, api/v1/__init__.py)
  ↓
ST4: PushService 구현 (Rate Limit + Dedup + 오케스트레이션) + DI 등록
  │  (push_service.py, deps.py)
  ↓
ST5: 가격 알림 PushService 연동 변경
  │  (price_alert_service.py, price_alert_monitor.py, deps.py)
  ↓
ST6: 주문 체결 알림 연동
  │  (OrderService에서 push_service.send_order_execution() 호출)
  ↓
ST7: AI 매매 신호 알림 연동
  │  (Celery task에서 push_service.send_ai_trading_signal() 호출)
  ↓
ST8: 시스템 알림 연동
  │  (Circuit Breaker/Health 이벤트 → push_service.send_system_alert())
  ↓
ST9: Silent push 옵션 구현 + 테스트
  │  (PushService silent=True 경로 + FCMService.send_silent())
  ↓
ST10: 단위 테스트 + 통합 테스트 + 코드 리뷰
```

### 서브태스크 매핑

| 원본 서브태스크 | 설명 | 구현 단계 |
|----------------|------|-----------|
| ST1 | Firebase 설정 및 FCM SDK 통합 | ST1 + ST2 |
| ST2 | FCM 토큰 관리 API 엔드포인트 구현 | ST3 |
| ST3 | 주문 체결 알림 메시지 구성 및 발송 | ST6 |
| ST4 | AI 매매 신호 알림 구현 | ST7 |
| ST5 | 가격 알림 구현 | ST5 |
| ST6 | 시스템 알림 구현 | ST8 |
| ST7 | 알림 저장 및 미읽 카운트 관리 | ST4 (PushService가 NotificationService 호출) |
| ST8 | Rate Limiting 구현 | ST4 (PushService 내부) |
| ST9 | Silent push 옵션 및 백그라운드 처리 | ST9 |
| ST10 | E2E 테스트 및 코드 리뷰 | ST10 |

---

## 17. 비기능 요구사항

### 성능

| 항목 | 목표 |
|------|------|
| Client API 응답 (POST/GET/DELETE) | < 50ms (p95) |
| FCM 발송 (1기기) | < 500ms (Firebase API 포함) |
| FCM 발송 (5기기 멀티캐스트) | < 1s (send_each, 병렬) |
| Rate Limit 체크 | < 5ms (Redis) |
| Dedup 체크 | < 5ms (Redis) |

### 제한

| 항목 | 값 |
|------|-----|
| 사용자별 분당 FCM 발송 | 10건 |
| 중복 알림 방지 TTL | 3600초 (1시간) |
| FCM 토큰 최대 길이 | 500자 (기존 Client.fcm_token) |
| 사용자별 최대 활성 기기 | WS_MAX_CONNECTIONS_PER_USER (5) |

### 신뢰성

- **실패 토큰 자동 정리**: NotRegistered/UNREGISTERED → fcm_token NULL
- **fire-and-forget**: FCM 발송 실패가 주요 비즈니스 로직 차단하지 않음
- **Rate Limiting**: 알림 폭탄 방지 (분당 10건)
- **Dedup**: 동일 dedup_key 1시간 내 재발송 방지
- **graceful degradation**: FIREBASE_CREDENTIALS_JSON 미설정 시 → 로깅만 (기존 스텁 동작)

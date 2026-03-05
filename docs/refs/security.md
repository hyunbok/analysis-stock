# CoinTrader - 보안 & 비기능 요구사항

> 원본: docs/prd.md §9, §10 기준. 최종 갱신: 2026-03-05

---

## 9. 보안

### 9.1 인증 및 접근 제어

- **인증**: JWT (access 30분, refresh 14일 Redis 저장)
- **2FA (TOTP)**: Google Authenticator 호환, 로그인/주문/API키 변경 시 2차 인증 (선택적 활성화)
- **이메일 인증**: 회원가입 시 인증 코드(6자리), 10분 만료. 미인증 계정은 거래 기능 제한
- **세션 관리**: 활성 세션(디바이스) 목록 조회, 개별/전체 세션 강제 종료
- **새 디바이스 알림**: 미등록 디바이스 로그인 시 기존 디바이스에 푸시 + 이메일

### 9.2 암호화 및 통신

- 거래소 API Key: AES-256-GCM 암호화
- 비밀번호: bcrypt(12)
- 통신: HTTPS/WSS 필수 (TLS 1.2+)
- API Key 조회 시 마스킹, 암호화 키 환경변수 관리

### 9.3 API 보안

- Rate Limiting, CORS 화이트리스트, Pydantic 검증
- 거래소별 서버 측 Rate Limiter

### 9.4 감사 로그 (Audit Log)

- MongoDB `audit_logs` 컬렉션
- **기록 대상**: 로그인/로그아웃, 비밀번호 변경, 2FA 토글, API 키 변경, 계정 삭제
- **기록 항목**: user_id, action, ip_address, user_agent, timestamp, details
- **보관**: 1년 (TTL), 사용자 본인 조회 불가 (관리자 전용)

### 9.5 개인정보 보호

- **동의 관리**: `user_consents` 테이블, 약관 버전 관리
- **계정 삭제**: 30일 유예 후 영구 삭제, 거래 기록은 5년 보관 (익명화)
- **데이터 최소 수집**

---

## 10. 비기능 요구사항

### 10.1 성능

- API 응답: 평균 200ms 이하 (p95 < 500ms)
- WebSocket 지연: 거래소 수신 후 100ms 이내
- 동시 접속: 1,000 WebSocket 연결
- 가동률: 99.5% (월간)

### 10.2 모니터링 및 에러 트래킹

- **APM**: Sentry (서버+클라이언트) + Prometheus+Grafana (메트릭)
- **헬스체크**: `GET /health` (DB, Redis, Celery 상태 포함)
- **거래소 모니터링**: 성공/실패율, 응답시간, Circuit Breaker 상태
- **알림**: Slack/PagerDuty — 에러율 급증, 거래소 장애, 서버 다운
- **클라이언트 크래시**: Firebase Crashlytics (iOS/Android), Sentry (Web)

### 10.3 로깅

- **서버**: structlog JSON, 요청별 correlation_id
- **로그 중앙화**: Loki + Grafana 또는 CloudWatch Logs
- **보관**: 애플리케이션 로그 90일, 감사 로그 1년

### 10.4 백업 및 복구

- **PostgreSQL**: pg_dump 일일 + WAL 아카이빙 (PITR). RPO 1시간, RTO 4시간
- **MongoDB**: mongodump 일일 + oplog 증분. RPO 1시간, RTO 4시간
- **Redis**: AOF 영속화 (refresh token, rate limit 보존)
- **백업 저장소**: S3 호환, 암호화, 30일 보관

### 10.5 CI/CD

- **CI**: GitHub Actions — 린트(ruff/dartanalyze), 테스트(pytest/flutter test), 커버리지(80%+)
- **CD**: Docker 빌드 → 스테이징 자동 → 수동 승인 후 프로덕션
- **배포**: Rolling Update (무중단), 롤백 1-click
- **환경**: local → staging → production 3단계

### 10.6 앱 버전 관리

- `GET /api/v1/app-version`으로 최소 지원 버전 확인
- 강제 업데이트: 앱 진입 차단 + 스토어 이동
- API 하위호환: v1 Deprecation 시 최소 3개월 유예, `Sunset` 헤더

# CoinTrader - 프로젝트 마스터 요약

> 원본: docs/prd.md §1, §2, §12 기준. 최종 갱신: 2026-03-05

---

## 1. 개요

Flutter 크로스플랫폼 코인 트레이딩 애플리케이션.
실시간 시세 조회, 호가창 거래, AI 기반 자동매매를 핵심 기능으로 제공한다.

- 단일 코드베이스로 iOS, Android, Windows, macOS, Web 지원
- 국내/해외 주요 거래소 통합 연동 (Exchange Abstraction Layer)
- AI 기반 자동매매 시스템 (OpenAI GPT + 기술적 지표)
- 실시간 차트 및 호가창 기반 수동 거래

---

## 2. 기술 스택

### 2.1 서버 (Backend)

| 항목 | 기술 |
|------|------|
| 언어 | Python 3.12+ |
| 프레임워크 | FastAPI (async) |
| 관계형 DB | PostgreSQL 16 + SQLAlchemy 2.0 (async) — 회원, 주문, 거래소 계정 등 트랜잭션 데이터 |
| 문서형 DB | MongoDB 7 + Beanie (async ODM) — AI 매매 로그, 시세/캔들, 뉴스 등 비정형 데이터 |
| 캐시/큐 | Redis 7 (캐시, Celery 브로커, Pub/Sub, Rate Limit) |
| 마이그레이션 | Alembic (PostgreSQL) / Beanie 마이그레이션 (MongoDB) |
| 인증 | JWT (access 30분 + refresh 14일), 이메일 비밀번호 재설정, 소셜 로그인(Google/Apple OAuth2) |
| 파일 스토리지 | S3 호환 스토리지 (프로필 아바타 이미지) |
| 실시간 | WebSocket (단일 연결 + 구독 메시지 방식) |
| 비동기 작업 | Celery + Redis (AI 매매, 뉴스 스크랩) |
| AI | OpenAI GPT API (모델은 환경변수 `OPENAI_MODEL`로 관리) |
| 컨테이너 | Docker + Docker Compose |

### 2.2 클라이언트 (Frontend)

| 항목 | 기술 |
|------|------|
| 프레임워크 | Flutter 3.x (Dart) |
| 상태관리 | Riverpod 2.x |
| 차트 | TradingView Lightweight Charts (WebView) |
| HTTP | Dio |
| WebSocket | web_socket_channel |
| 로컬 저장 | SharedPreferences / Hive |
| 다국어 | flutter_localizations + intl (ko, en, ja, zh, es) |
| 테마 | Material 3 (Light / Dark) |

### 2.3 지원 플랫폼 & UI 전략

**모바일 우선 (Mobile First)**
- Phase 1: iOS 15.0+ / Android API 26+ (모바일 UI 완성)
- Phase 2: Web (Chrome, Safari, Edge 최신 2버전) + Windows 10+ / macOS 12.0+ (반응형 확장)

---

## 12. 개발 마일스톤

### Phase 1 - 핵심 기능 (국내 거래소)

| 단계 | 항목 | 범위 |
|------|------|------|
| M1 | 인프라 & 프로젝트 셋업 | 모노레포 구조, Docker Compose(PostgreSQL+MongoDB+Redis), FastAPI/Flutter 골격, CI/CD, 모니터링, DB 백업, 로그 중앙화, 스테이징 환경 |
| M2 | 인증 시스템 | 회원가입(이메일 인증), 로그인, JWT, 비밀번호 찾기/재설정, 소셜 로그인(Google/Apple), 프로필 아바타, 클라이언트 관리, 개인정보 동의 |
| M3 | 거래소 추상화 & Upbit | ExchangeProvider ABC, Factory, Upbit REST/WS 구현, Circuit Breaker, Rate Limiter, API 키 권한 검증 |
| M4 | 코인 목록 & 관심 코인 | 코인 마스터, 검색, 관심 코인 CRUD(스와이프), WS 시세 허브+연결 상태 UI |
| M5 | CoinOne 연동 | CoinOne Provider 구현 (M3 인터페이스 준수) |
| M6 | 트레이딩 & 자산 | TradingView 차트, 호가창, 주문 실행, 자산 포트폴리오, 거래소 설정 |
| M7 | AI 자동매매 | 마스터 스위치, 기술적 지표, 장세 분석, 전략 선택, Celery 5분 주기, GPT 연동, 대시보드 |
| M8 | 통계 & 리포트 & 기타 | 일별/누적 손익, 매매 로그, 통계 UI, 프로필 수정, 가격 색상, 이용약관, 감사 로그 |
| M9 | 고도화 & 보안 강화 | 2FA(TOTP), 세션 관리, 디바이스 알림, 가격 알림, 백테스팅, 푸시 알림, 알림 화면, 생체 인증, 성능 최적화 |

### Phase 2 - 확장 (해외 거래소)

| 단계 | 항목 | 범위 |
|------|------|------|
| M10 | Coinbase 연동 | Coinbase Provider 구현 |
| M11 | Binance 연동 | Binance Provider 구현 |
| M12 | 다국어 완성 | ja, zh, es 번역 및 검수 |
| M13 | 확장 기능 | 시장 현황, 코인 상세, 입출금, 가격 비교, 차트 설정, 강제 업데이트, K8s |

### 병렬 작업 가이드

```
M1 완료 후 병렬 가능:
  - M2-a 서버 기본 인증 / M2-b 클라이언트 인증(mock) / M3 Upbit Provider
  - M2-a 완료 후: M2-c 소셜 로그인 / M2-d 아바타 + File Storage

M2+M3 완료 후 병렬 가능:
  - M4 코인&관심코인 / M5 CoinOne / 거래소 설정 UI

M4+M6 완료 후:
  - M7 AI 엔진(서버) / M7 AI 대시보드(클라이언트, mock)

M7+M8 완료 후:
  - M9-a 2FA+세션 / M9-b 가격 알림+푸시 / M9-c 알림 화면 / M9-d 백테스팅 / M9-e 생체 인증
```

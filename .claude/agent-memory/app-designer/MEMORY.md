# App Designer Agent Memory

## 프로젝트 기본 정보

- 앱명: CoinTrader (크로스플랫폼 코인 트레이딩 앱)
- 플랫폼: Flutter (iOS/Android Phase 1, Web/Desktop Phase 2)
- 상태관리: Riverpod 2.x
- 테마: Material 3 (Light/Dark)
- 다국어: ko, en, ja, zh, es
- PRD 위치: /Users/hyunbokkim/workspaces/python-projects/analysis-stock/docs/prd.md
- 디자인 컨셉: /Users/hyunbokkim/workspaces/python-projects/analysis-stock/docs/design-concept.md

## 확정된 디자인 결정사항

### 컬러 컨벤션 (한국 거래소 표준)
- 매수/상승: `#F23645` (빨강) — 한국 표준 (업비트, 코인원)
- 매도/하락: `#1E88E5` (파랑) — 한국 표준
- 글로벌 전환 옵션 설정에서 지원 (녹색=상승, 빨강=하락)
- AI 활성화: `#00BCD4` (민트/시안)
- Primary Brand: `#1565C0` (Material 3 시드)

### 테마 전략
- 기본: 다크 모드 (Dark Mode First)
- 다크 배경: `#0A0A0F`, Surface: `#12131A`
- 라이트 배경: `#F5F6FA`, Surface: `#FFFFFF`

### 네비게이션 (모바일)
- Bottom Navigation Bar, 4탭: [홈|트레이딩|AI매매|더보기]
- 트레이딩 화면: 탭 방식 (차트/호가창/주문 탭 전환)

### 타이포그래피
- 한글: Pretendard (코인원 레퍼런스)
- 숫자: Inter with tabular figures (`font-feature-settings: "tnum"`)

### 브레이크포인트
- Mobile: < 600px, Tablet: 600-1200px, Desktop: > 1200px

## Stitch 화면 생성 시 참고

생성 순서: 메인 → 트레이딩 → AI대시보드 → 로그인 → 매매내역 → 거래소설정 → 설정 → 스플래시
디바이스: MOBILE 우선
테마: Dark Mode 기본
프롬프트에 항상 포함: "Material 3 Dark Mode, Primary #1565C0, 매수 #F23645, 매도 #1E88E5"

## 레퍼런스 사이트 분석 결과

- coinone.co.kr: 라이트 테마, Pretendard 폰트, Primary #0B59D5, 250ms 애니메이션
- upbit.com: TradingView 차트, 매수=빨강/매도=파랑, 거래량 컬러바
- 웹 스크래핑 한계: 두 사이트 모두 SPA 구조로 CSS/HTML 상세 분석 불가 (JS 렌더링)

## Stitch MCP 연결 관련 주의사항

- Stitch MCP 설정 파일: `/Users/hyunbokkim/workspaces/python-projects/analysis-stock/.mcp.json`
- 연결 방식: `type: "http"`, Bearer 토큰 인증
- 오류 패턴: `Incompatible auth server: does not support dynamic client registration`
  - 원인: Bearer 토큰 만료 (401 UNAUTHENTICATED) 시 발생
  - 해결: `gcloud auth print-access-token` 또는 Google 재로그인으로 새 토큰 발급 후 `.mcp.json` 업데이트
- 토큰 만료 시 MCP 재시작 필요: Claude Code 세션 재시작 또는 `/mcp` 명령어로 재연결
- 대안: Stitch 웹(stitch.withgoogle.com)에서 직접 프로젝트/화면 생성 가능

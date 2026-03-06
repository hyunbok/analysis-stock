---
name: team-executor
description: task-master-ai 통해 계획된 내용을 모든 agent를 동시에 스폰하여 자율적으로 협업하며 실행합니다.
---

# Team Execution Skill

사용법: `/team-executor {tag}:{main_task_id}`

- `tag`: 태스크 파일 tag (예: `v1`)
- `main_task_id`: 메인 태스크 번호 (예: `3`)
- 예시: `/team-executor v1:1`

## task-executor와의 차이점

| 항목 | task-executor | team-executor |
|------|--------------|---------------|
| 에이전트 스폰 | 메인 에이전트가 서브태스크별 개별 스폰 | **메인 에이전트가 팀 리더로서 전체 에이전트 동시 스폰** |
| 조율 방식 | 메인 에이전트가 중앙 조율 | **메인 에이전트 주도 + 에이전트 간 자율 P2P 소통** |
| 소통 방식 | 메인 에이전트 경유 | **SendMessage로 직접 소통** |
| 메인 에이전트 역할 | 전체 워크플로우 직접 관리 | **팀 리더: 스폰, 설계 승인, 진행 모니터링, 완료 확인** |

## 태스크 파일 규칙

- 태스크 파일: `.taskmaster/tasks/tasks.json`
- 모든 경로에 `{tag}-{task-id}` 프리픽스 사용:
  - 브랜치: `feature/{tag}-{task-id}_{task-name}`
  - 설계서: `docs/tasks/{tag}-{task-id}-{task-name}-plan.md`
  - 팀명: `team-{tag}-{task-id}`

## 메인 에이전트(팀 리더) 워크플로우

> 메인 에이전트가 직접 팀 리더 역할을 수행한다.

### 1. 태스크 파악

- `.taskmaster/tasks/tasks.json`에서 태그에 포함된 메인 태스크 로드
- 태스크 내용(title, description, details, subtasks) 확인
- 서브태스크 title의 괄호 안 에이전트 타입으로 필요한 에이전트 유형 목록 추출
  - 예: `"모노레포 디렉토리 구조 생성 (project-architect)"` -> `project-architect`

### 2. 브랜치 생성

- **현재 브랜치**에서 `feature/{tag}-{task-id}_{task-name}` 브랜치 생성 및 체크아웃

### 3. 팀 생성 및 설계 (Phase 1)

1. `TeamCreate`로 팀 생성 (팀명: `team-{tag}-{task-id}`)
2. **설계 에이전트 동시 스폰**:
   - 기본: `project-architect` + `code-architect`
   - DB 관련 서브태스크가 있으면: `db-architect`도 추가
   - 각 에이전트에게 전달:
     - 메인 태스크 정보 (title, description, details)
     - 전체 서브태스크 목록 + dependencies
     - 설계서 경로: `docs/tasks/{tag}-{task-id}-{task-name}-plan.md`
     - **자율 협업 프로토콜** (아래 섹션 전문)
   - 설계 에이전트들은 자율 협업으로 설계서를 공동 작성
3. 설계 완료 보고를 받으면 **메인 에이전트가 직접 검토 후 승인/피드백**

### 4. 구현 에이전트 스폰 (Phase 2)

1. 설계 승인 후, 서브태스크에서 추출한 **모든 구현 에이전트 유형 + `code-review-expert`**를 동시 스폰
   - 같은 유형이 여러 서브태스크를 담당하면 하나만 스폰 (한 에이전트가 여러 서브태스크 수행)
   - 각 에이전트에게 전달:
     - 메인 태스크 정보 (title, description, details)
     - 담당 서브태스크 목록 + dependencies
     - 설계서 경로
     - 팀 전체 구성원 목록과 각 담당
     - **자율 협업 프로토콜** (아래 섹션 전문)
   - `code-review-expert`에게는 전체 구현 완료 후 리뷰 수행을 지시
2. 에이전트들은 자율적으로 의존성을 확인하고, 선행 작업 완료 알림을 주고받으며 진행

### 5. 진행 모니터링

- 에이전트들의 진행 상황 보고 수신
- 블로킹/이견 발생 시 중재
- 의존성 체인 관리: 선행 완료 시 후속 에이전트에게 알림

### 6. 리뷰 및 완료

- 구현 완료 후 `code-review-expert`에게 리뷰 요청
- 리뷰 통과 확인
- 모든 에이전트에게 `shutdown_request` 전송
- `TeamDelete`로 팀 정리

### 7. 구현 검증 및 설계서 업데이트

> 팀 정리 후 메인 에이전트가 직접 수행. 자율 협업 중 설계서가 변경될 수 있으므로 최종 정합성을 확인한다.

- 설계서의 구현 파일 목록 대비 실제 파일 존재 여부 `Glob`으로 검증
- 설계서 "현재 상태"를 구현 완료 상태로 갱신 (코드 리뷰 수정사항, 추가 결정사항 포함)
- 최종 상태 요약 출력 (구현 파일 수, 테스트 수, 커밋, 리뷰 결과)
- 미커밋 코드/문서가 있으면 최종 커밋 수행

## 자율 협업 프로토콜 (에이전트 스폰 시 전달)

> 아래 내용을 각 에이전트 스폰 시 프롬프트에 포함하여 전달한다.

```
## 자율 협업 프로토콜

### 기본 원칙

1. **능동적 소통**: 막히면 스스로 관련 에이전트에게 SendMessage로 질문/요청
2. **의존성 인지**: 선행 작업에 의존하면 해당 에이전트에게 진행 상황 확인
3. **선행 작업 알림**: 완료 시 의존하는 에이전트에게 알림
4. **설계 우선**: 구현 전 관련 에이전트와 인터페이스/스펙 합의
5. **충돌 회피**: 같은 파일 수정 시 관련 에이전트와 조율
6. **팀 리더 보고**: [ESCALATE](블로킹/중재 필요)와 최종 완료 보고만 team-lead에게 전달

### 소통 패턴

| 태그 | 용도 | 예시 |
|------|------|------|
| [ASK] | 질문/요청 | [ASK] DB 스키마: User 모델에 exchange_keys 필드 타입? |
| [NOTIFY] | 알림 (완료/변경/블로킹) | [NOTIFY] 인증 API 구현 완료. 연동 가능. |
| [AGREE] | 합의 요청 | [AGREE] place_order 시그니처 제안: {내용}. 동의하면 진행. |
| [REVIEW] | 리뷰 요청 | [REVIEW] server/app/services/order_service.py 리뷰 부탁. |
| [ESCALATE] | 팀 리더 중재 요청 | [ESCALATE] API 버저닝 방식 이견. 중재 요청. |

### 팀 구성원 확인

팀 구성원은 ~/.claude/teams/{team-name}/config.json에서 확인 가능.
```

## 에이전트 유형

| 태스크 특성 | subagent_type |
|------------|---------------|
| 시스템 아키텍처 설계, 설계서 작성 | `project-architect` |
| 코드 구조 설계, API/WebSocket 규격, 컨벤션 | `code-architect` |
| DB 스키마, 인덱스, 마이그레이션, 캐싱 | `db-architect` |
| Python/FastAPI 백엔드 구현 | `python-backend-expert` |
| Flutter 프론트엔드 구현 | `flutter-frontend-expert` |
| 거래소 API 통합 (Upbit, Binance 등) | `exchange-api-expert` |
| AI 자동매매 전략, 기술적 지표, 백테스팅 | `ai-trading-expert` |
| UI/UX 디자인, 화면 설계 (Stitch) | `app-designer` |
| 코드 리뷰, 품질 검증 | `code-review-expert` |
| E2E 테스트 설계 및 구현 | `e2e-test-expert` |

## Rules

- 에이전트 정의: `.claude/agents/`
- 메인 에이전트가 직접 팀 리더 역할 수행 (project-architect에게 위임하지 않음)
- project-architect는 설계서 작성 전담
- 자율 협업 프로토콜은 반드시 각 에이전트 스폰 시 전달

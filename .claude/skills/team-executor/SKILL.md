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
| 에이전트 스폰 | 메인 에이전트가 서브태스크별 개별 스폰 | **project-architect가 팀 리더로서 전체 에이전트 스폰** |
| 조율 방식 | 메인 에이전트가 중앙 조율 | **project-architect 주도 + 에이전트 간 자율 P2P 소통** |
| 소통 방식 | 메인 에이전트 경유 | **SendMessage로 직접 소통** |
| 메인 에이전트 역할 | 전체 워크플로우 직접 관리 | **project-architect 스폰 후 승인/확인만** |

## 태스크 파일 규칙

- 태스크 파일: `.taskmaster/tasks/tasks.json`
- 모든 경로에 `{tag}-{task-id}` 프리픽스 사용:
  - 브랜치: `feature/{tag}-{task-id}_{task-name}`
  - 설계서: `docs/tasks/{tag}-{task-id}-{task-name}-plan.md`
  - 팀명: `team-{tag}-{task-id}`

## 메인 에이전트 워크플로우

> 메인 에이전트는 아래 단계만 수행한다. 나머지는 project-architect가 팀 리더로서 자율 수행.

### 1. 태스크 파악

- `.taskmaster/tasks/tasks.json`에서 태그에 포함된 메인 태스크 로드
- 태스크 내용(title, description, details, subtasks) 확인
- 서브태스크 title의 괄호 안 에이전트 타입으로 필요한 에이전트 유형 목록 추출
  - 예: `"모노레포 디렉토리 구조 생성 (project-architect)"` -> `project-architect`

### 2. 브랜치 생성

- `develop` 브랜치에서 `feature/{tag}-{task-id}_{task-name}` 브랜치 생성 및 체크아웃

### 3. project-architect 스폰 (팀 리더 위임)

`project-architect`를 **팀 리더 모드**로 스폰하고 전체 실행을 위임한다.

#### 스폰 시 전달 내용

```
## 역할
당신은 이 태스크의 **팀 리더**입니다.
팀을 구성하고, 설계를 주도하고, 구현을 조율하고, 완료까지 책임집니다.
"팀 리더 워크플로우"(모드 2)를 따라 실행하세요.

## 태스크 정보
- 팀명: team-{tag}-{task-id}
- 브랜치: feature/{tag}-{task-id}_{task-name}
- 설계서 경로: docs/tasks/{tag}-{task-id}-{task-name}-plan.md
- 메인 태스크: {title, description, details 전체}
- 서브태스크 목록: {전체 서브태스크 + dependencies + 에이전트 유형}

## 필요 에이전트 목록
- {서브태스크에서 추출한 에이전트 유형 목록}
- 필수 추가: code-architect, code-review-expert
```

### 4. 설계서 승인

- project-architect가 설계서 완료를 보고하면 검토 후 승인/피드백

### 5. 최종 완료 확인

- project-architect가 완료 보고하면 최종 확인
- `TeamDelete`로 팀 정리

## 에이전트 유형

| 태스크 특성 | subagent_type |
|------------|---------------|
| 시스템 아키텍처 설계, 에이전트 간 조율 | `project-architect` |
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
- 커밋: `/commit` 스킬 사용
- 메인 에이전트는 project-architect 스폰 후 **설계서 승인**과 **최종 완료 확인**만 관여
- 팀 리더 워크플로우, 자율 협업 프로토콜 등 상세는 `project-architect` 에이전트 정의에 포함

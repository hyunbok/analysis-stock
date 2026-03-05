---
name: task-executor
description: task-master-ai 통해 계획된 내용을 agent team 기능을 이용하여 실행합니다.
---

# Task Execution Skill

사용법: `/task-executor {tag}:{main_task_id}`

- `tag`: 태스크 파일 tag (예: `v1`)
- `main_task_id`: 메인 태스크 번호 (예: `3`)
- 예시: `/task-executor v1:1`

## 태스크 파일 규칙

- 태스크 파일: `.taskmaster/tasks/tasks.json`
- 모든 경로에 `{tag}-{task-id}` 프리픽스 사용:
  - 브랜치: `feature/{tag}-{task-id}_{task-name}`
  - 설계서: `docs/tasks/{tag}-{task-id}-{task-name}-plan.md`
  - 팀명: `task-{tag}-{task-id}-team`
  - Worktree 브랜치: `feature/{tag}-{task-name}/wt-{subtask-id}`

## 실행 워크플로우

### 1. 태스크 파악

- `.taskmaster/tasks/tasks.json`에서 태그에 포함된 메인 태스크 로드
- 태스크 내용(title, description, details, subtasks) 확인
- 서브태스크 및 의존성 파악
- 서브태스크 title의 괄호 안 에이전트 타입으로 담당 에이전트 식별
  - 예: `"모노레포 디렉토리 구조 생성 (project-architect)"` → `project-architect`

### 2. 브랜치 생성

- `develop` 브랜치에서 `feature/{tag}-{task-id}_{task-name}` 브랜치 생성 및 체크아웃

### 3. 상세 설계 및 문서 작성 (필수)

> **이 단계는 절대 생략하지 않는다.** 설계서가 완성되고 팀 리드가 검토를 마칠 때까지 구현 단계로 넘어가지 않는다.

#### 3-1. 기존 설계서 확인

- `docs/tasks/{tag}-{task-id}-*-plan.md` 파일이 있는지 확인
- **있으면**: 해당 설계서를 읽고, 현재 태스크의 서브태스크와 비교하여 충분한지 검토
  - 충분하면 → 3-3으로 이동
  - 부족하면 → 3-2에서 보완

#### 3-2. 설계서 작성

- 설계 에이전트를 스폰하여 설계서를 작성한다:
  - `code-architect` 스폰 — 코드 구조 설계, 디렉토리 구조, 모듈 의존관계
  - API/DB 설계 필요 시: `db-architect` 스폰 — DB 스키마, 인덱스, 마이그레이션
  - 시스템 아키텍처 필요 시: `project-architect` 스폰 — 전체 시스템 설계 및 조율
- 각 에이전트는 초안을 `SendMessage`로 `project-architect`에게 전달
- `project-architect`가 초안들을 취합하여 **통합 설계서 초안** 작성
- `project-architect`가 초안을 팀 리드에게 전달 → 팀 리드와 논의 후 최종 확정
- 확정된 설계서 저장:
  - 파일: `docs/tasks/{tag}-{task-id}-{task-name}-plan.md`
  - 분량: **200줄 이내**

#### 3-3. 설계서 필수 포함 항목

설계서에 다음 항목이 **모두** 포함되어야 한다:

1. **개요**: 기능 설명, 의존성, 전체 흐름
2. **API 설계** (해당 시): 엔드포인트, 메서드, 경로, 요청/응답 DTO
3. **데이터 모델** (해당 시): 도메인 모델, PostgreSQL 스키마, MongoDB 도큐먼트
4. **구현 파일 목록**: 서브태스크별 생성/수정 파일, 역할, 의존관계
5. **주요 결정사항**: 설계 선택과 근거
6. **빌드 시퀀스**: Phase별 구현 순서

#### 3-4. 팀 리드 검토

- 팀 리드가 설계서의 완성도를 검증한다:
  - 모든 서브태스크가 설계서에 반영되었는지
  - 파일 목록과 의존관계가 명확한지
  - 빌드 시퀀스가 논리적인지
- 검토 완료 후 구현 단계로 진행

### 4. 구현

- 팀 생성: `TeamCreate`로 `task-{tag}-{task-id}-team`
- **`project-architect`를 반드시 팀에 포함** — 에이전트 간 조율 및 기술 의사결정 담당
- 서브태스크 기반 팀 TaskList 생성 (의존성 포함)
- 서브태스크별 에이전트 스폰 (서브태스크 title 괄호 안의 에이전트 타입 사용):
  - 예: `(python-backend-expert)` → `python-backend-expert` 에이전트 스폰
  - 예: `(flutter-frontend-expert)` → `flutter-frontend-expert` 에이전트 스폰
- 의존성 없는 독립 서브태스크: **Git Worktree로 병렬 처리**
- 의존성 있는 서브태스크: 선행 태스크 완료 후 순차 실행

### 5. 코드 리뷰 (구현 변경 시 필수)

> 코드 구현이 포함된 태스크는 **반드시 코드 리뷰를 수행한다.** 문서/설정만 변경하는 태스크는 제외.
- `code-review-expert` 스폰 — 변경된 파일 전체 리뷰
- 리뷰 결과를 `project-architect`에게 전달
- 수정 사항이 있으면: 해당 구현 에이전트 재스폰하여 수정
- 수정 완료 후 `project-architect`가 변경 사항 검토 → 팀 리드와 협의하여 재리뷰 필요 여부 결정
  - 재리뷰 필요: `code-review-expert` 재스폰
  - 재리뷰 불필요: 다음 단계로 진행

### 6. 검증 및 완료

- 팀 리드: 빌드/테스트 최종 확인
- E2E 테스트 필요 시: `e2e-test-expert` 스폰
- 태스크 파일 완료 처리:
  - `.taskmaster/tasks/tasks.json`에서 태그에 포함된 메인 태스크의 `status`를 `"done"`으로 변경
  - 완료된 서브태스크들의 `status`도 `"done"`으로 변경
  - `updatedAt` 필드를 현재 시각(ISO 8601)으로 갱신
- 커밋: `/commit` 스킬
- feature 브랜치 push: `git push -u origin feature/{tag}-{task-id}_{task-name}`
- 종료: 에이전트 `shutdown_request` → `TeamDelete`

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

## Git Worktree (병렬 에이전트용)

병렬 에이전트 스폰 시 팀 리드 작업:

1. 서브태스크마다 worktree 생성
   ```bash
   git worktree add .worktrees/wt-{subtask-id} -b feature/{tag}-{task-name}/wt-{subtask-id} feature/{tag}-{task-id}_{task-name}
   ```
2. 에이전트에 worktree 경로 전달, 규칙 명시:
   - 해당 worktree 내에서만 작업
   - 독립적으로 커밋
   - 빌드/테스트 검증 후 커밋
3. 모든 에이전트 완료 후 feature 브랜치로 순차 머지
4. 충돌 시: 구현 에이전트 스폰하여 해결
5. worktree 및 브랜치 정리

## Rules

- 에이전트 정의: `.claude/agents/`
- `.worktrees/` 디렉토리: `.gitignore` 추가
- 커밋: `/commit` 스킬 사용
# CLAUDE.md

이 저장소에서 작업하는 Claude Code 세션을 위한 지침.

## 브랜치 병합 규칙

작업을 완료했으면 브랜치를 방치하지 말고, 그 세션 안에서 `main`까지 병합을 끝낸다.
(27개의 오래된 미병합 브랜치가 방치되어 있던 걸 정리한 이후로 적용되는 규칙 — 2026-09-13)

- 작업 단위(하나의 의미 있는 변경 묶음)가 끝나면: 전체 테스트 스위트 통과 확인 → PR 생성 → CI 통과 확인 → `main`에 병합까지 마친다.
- CI가 없거나 실패해서 병합을 못 하면, 왜 못 했는지 사용자에게 명확히 알리고 브랜치를 남겨둔 이유를 설명한다 — 그냥 조용히 방치하지 않는다.
- 병합 방식(merge/squash/rebase)은 저장소에 기존 병합 이력이 있으면 그 관례를 따르고, 없으면 `merge`를 기본으로 한다.
- 이 규칙은 2026-09-13에 사용자가 명시적으로 요청해서 추가됨 — PR을 만들지 않는다는 기존의 일반 원칙보다 이 저장소에서는 이 규칙이 우선한다.

## 브랜치 시작 규칙 (동일 브랜치 이름 재사용 시)

세션 시작 시, 같은 브랜치 이름(`claude/autonomous-ai-investment-system-plan-4-ha7y35` 등)을 이어서 쓰기 전에 **반드시** 그 브랜치가 `origin/main`의 최신 병합을 실제로 반영하고 있는지 직접 확인한다.
(외부 검증 리포트가 2026-09-17에 실제로 재현한 사고 — stale 브랜치 재사용 때문에 (1) main에 이미 있던 다른 세션의 ADR 번호와 충돌, (2) main 쪽 변경 사항을 못 본 채 코드를 계속 쌓는 문제가 동시에 발생했음. ADR-0147 참고.)

- 확인 방법: `git fetch origin main <branch-name>` 후 `git merge-base --is-ancestor origin/main <branch-name>`으로 그 브랜치가 origin/main을 진짜로 포함하고 있는지 검사한다. 포함하지 않으면(즉 origin/main이 그 브랜치의 조상이 아니면) 그 브랜치는 stale — 바로 코드를 쌓지 말고 먼저 `origin/main`으로 fast-forward(또는 rebase)한다.
- fast-forward 전에 로컬에 커밋되지 않은 변경이 있으면 먼저 `git stash push -u`로 보존한 뒤 fast-forward, 그다음 `git stash pop`으로 되돌린다 — 작업물을 잃지 않는다.
- 이 확인은 매 세션 시작 시 1회, 그리고 다른 세션/PR이 그 사이 `main`에 병합됐다는 신호가 있을 때(예: 사용자가 다른 작업을 언급하거나, PR 목록에 새 병합이 보일 때)마다 재확인한다.

## 토큰/비용 절약 규칙 (2026-09-18, 사용자 명시적 요청)

한 세션에서 백그라운드 에이전트를 여러 개 동시에 돌리다 계정 사용량 한도(rate limit)에 걸려 작업이 중단되고, 정리 비용(worktree 혼선, ADR 번호 충돌 등)까지 추가로 발생한 사고 이후 적용되는 규칙.

- **백그라운드 에이전트는 동시에 최대 1개만 실행한다.** 여러 독립 항목이 있어도 순차적으로 처리 — 병렬로 띄우면 각 에이전트가 전체 컨텍스트/테스트 스위트 비용을 독립적으로 다시 지불하고, 조율 실수(같은 작업 디렉터리 오염, ADR 번호 충돌 등)가 발생해 총비용이 더 커진다.
- **작은 항목들은 가능하면 하나의 ADR/PR로 묶어서 처리한다.** 항목마다 매번 별도로 "전체 스위트 실행 → ADR 작성 → PR → 병합"을 반복하지 않고, 서로 관련 있는 작은 변경들은 배치로 묶는다(예: 워크플로 권한 축소 + BUY_AND_HOLD 기업활동 배선처럼 서로 독립적이어도 작은 항목 2개를 한 PR로 묶은 전례 참고).
- **개발 중에는 관련된 타겟 테스트만 실행하고, 전체 스위트는 병합 직전에 한 번만 실행한다.** (브랜치 병합 규칙의 "전체 테스트 스위트 통과 확인" 요건은 그대로 유지 — 병합 게이트로서 마지막에 1회 실행하는 것까지 없애는 게 아니라, 개발 반복 중간중간 불필요하게 전체 스위트를 여러 번 돌리지 않는다는 뜻.)
- **`docs/PROJECT_STATUS.md`의 기존 로그 방식(세션별 긴 문단 누적)은 그대로 유지한다 — 이 규칙 적용 이후에도 그 파일의 포맷/컨벤션을 바꾸지 않는다.** 사용자가 명시적으로 이 파일은 건드리지 말라고 요청함.

## llmwiki MCP 도구 (Batch K, 2026-09-24)

`microsoft/llmwiki`를 이 프로젝트의 문서 위키 도구로 등록함
(`EXTERNAL_REPO_APPLICABILITY_REPORT.md` priority-6 권고). `.mcp.json`이
`llmwiki` MCP 서버를 등록한다.

**(2026-09-24 후속 수정) 매 세션 clone+build 방식은 폐기함.**
원래는 `.claude/hooks/session-start.sh`가 매 세션 시작 시
`.llmwiki-tool/`(gitignore됨)에 소스를 clone+build했는데 — MCP
클라이언트의 stdio 연결 타임아웃(~30초)과 clone+npm install+tsc
빌드 시간이 경쟁하는 구조라 네트워크가 느린 세션에서는 빌드가 늦게
끝나 `CONNECTION_CLOSED`로 실패했다. 이 레이스는 그 안에서
빌드 순서를 두 번 바꿔봐도(venv보다 먼저 실행 등) 좁혀지기만 하고
없어지지 않았음 — 실제로 2026-09-24 세션에서 재현되어 근본 원인으로
확인됨. 지금은 `esbuild`로 만든 의존성 없는 단일 번들
(`vendor/llmwiki-mcp/bin.bundle.cjs`, git에 커밋됨 — provenance/갱신
방법은 `vendor/llmwiki-mcp/NOTICE.md` 참고)을 `.mcp.json`이 바로
실행한다. 세션 시작 시 clone/npm install/tsc가 전혀 없으므로 레이스
자체가 사라짐 — `session-start.sh`의 llmwiki 관련 블록은 제거됨.
번들을 다시 만들어야 할 때(업스트림 갱신 등)만 `NOTICE.md`의 절차를
따른다.

- `.wiki/`(raw/사람 소유 원천, wiki/LLM 소유 유도물, AGENTS.md 스키마)와
  `vendor/llmwiki-mcp/`(빌드된 MCP 서버 번들)는 **git에 커밋되는 실제
  콘텐츠**다 — `.venv/`/`.llmwiki-tool/`(둘 다 gitignore, 매 세션
  재생성 또는 필요 시에만 임시로 사용)과 다르게 취급한다.
- 위키에 쓴 내용이 이 프로젝트의 실제 의사결정 경로(decision/risk 등)로
  **역류해서는 안 된다** — DuckDB가 진실 공급원이고 위키는 어디까지나
  2차 뷰. 이건 LLM Wiki 저장소 자체의 3계층 원칙이자 보고서의 경계
  명시 사항.
- MCP 서버 빌드/등록은 이 세션의 auto-mode classifier가 "외부 코드
  실행"/"신뢰 안 된 코드 통합"으로 각각 별도 분류해서 차단했던 이력이
  있음 — 향후 세션에서 이 훅이 막히면, 사용자가 직접 권한을 허용하거나
  GitHub 웹 UI로 관련 파일을 커밋해줘야 할 수 있다 (2026-09-24 세션의
  `.mcp.json`/`session-start.sh` 추가와, 같은 날 후속 수정으로 만든
  `vendor/llmwiki-mcp/` 번들 빌드/커밋이 실제로 이 경로로 처리됨).

## 사용자 액션 대기 항목 (2026-09-24)

Claude 세션이 자체적으로 처리할 수 없어서 계정 소유자가 직접 해야
하는 항목들. 완료되면 세션에 알려주면 이어서 코드 작업 진행.

- **KIS(한국투자증권) 모의투자 커넥터** (`EXTERNAL_REPO_APPLICABILITY_
  REPORT.md` priority 8, `ADR-0191`에서도 참조): 실계좌 개설 + KIS
  Developers 포털(`apiportal.koreainvestment.com`)에서 모의투자 전용
  APP KEY/APP SECRET 발급 필요. 발급받은 키는 채팅에 붙여넣지 말고
  GitHub 저장소 Settings → Secrets and variables → Actions에
  `KIS_APP_KEY`/`KIS_APP_SECRET`로 직접 등록 — `ADR-0082`의
  `MARKET_DATA_API_KEY`와 동일한 패턴. 등록 완료되면 `src/broker/kis/`
  어댑터 작성 + 실제 모의투자 API 검증 진행.
- **colibri 실행용 Oracle Cloud 서버** (`EXTERNAL_REPO_APPLICABILITY_
  REPORT.md` priority 10): Oracle Cloud Always Free 계정 생성(완료,
  2026-09-24) → `VM.Standard.A1.Flex`(ARM, 4 OCPU/24GB RAM) 인스턴스
  생성 → 그 VM에 GitHub Actions self-hosted runner 설치·등록(SSH 키를
  세션과 주고받지 않는 방법 — `runs-on: self-hosted`로 원격 작업 위임
  가능). 러너 등록되면 colibri ARM 빌드 가능 여부 확인 + 워크플로 작성
  진행.

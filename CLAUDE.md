# CLAUDE.md

이 저장소에서 작업하는 Claude Code 세션을 위한 지침.

## 브랜치 병합 규칙

작업을 완료했으면 브랜치를 방치하지 말고, 그 세션 안에서 `main`까지 병합을 끝낸다.
(27개의 오래된 미병합 브랜치가 방치되어 있던 걸 정리한 이후로 적용되는 규칙 — 2026-09-13)

- 작업 단위(하나의 의미 있는 변경 묶음)가 끝나면: 전체 테스트 스위트 통과 확인 → PR 생성 → CI 통과 확인 → `main`에 병합까지 마친다.
- CI가 없거나 실패해서 병합을 못 하면, 왜 못 했는지 사용자에게 명확히 알리고 브랜치를 남겨둔 이유를 설명한다 — 그냥 조용히 방치하지 않는다.
- 병합 방식(merge/squash/rebase)은 저장소에 기존 병합 이력이 있으면 그 관례를 따르고, 없으면 `merge`를 기본으로 한다.
- 이 규칙은 2026-09-13에 사용자가 명시적으로 요청해서 추가됨 — PR을 만들지 않는다는 기존의 일반 원칙보다 이 저장소에서는 이 규칙이 우선한다.

## `docs/PROJECT_STATUS.md` "이력 유실" 주장 — 철회됨 (2026-09-24, 같은 날 정정)

**바로 위 섹션 제목의 주장("Session 10에서 끝, 26f1c0a가 873개 파일/
208,573줄 통째 추가, main 히스토리 재시작, Session 11~38 유실")은
2026-09-24 같은 날 외부 독립 감사로 반증되어 전체 철회한다. 원인은
그 주장을 쓴 세션의 git 클론이 **shallow clone**이었던 것 — 이 저장소
자체에 이미 한 번 기록된 것과 완전히 같은 실패 패턴이다(2026-09-17
`ruflo` 브랜치를 "main과 공통 조상 없음"으로 오판한 사건도 원인이
동일했고, 그 정정 기록이 `docs/PROJECT_STATUS.md` 자체에 이미 남아있다
— 이번에도 그 교훈을 실제로 적용하지 않고 반복한 셈).

**직접 재검증(2026-09-24, `git fetch --unshallow` 후 재확인)으로 확인한
실제 사실**:
- `git show --shortstat 26f1c0a` → **"6 files changed, 611 insertions(+)"**
  (Alpaca paper broker 검증 스크립트 추가 커밋, ADR-0170) — "873개 파일/
  208,573줄 삭제 없이 추가"는 shallow 클론에서 부모 커밋(`85778e9`)이
  shallow 경계 밖에 있을 때 git이 보여주는 "빈 트리 대비 diff" 아티팩트였다.
- `26f1c0a`는 `docs/PROJECT_STATUS.md`를 **전혀 건드리지 않았다**.
- `docs/PROJECT_STATUS.md`를 건드린 커밋은 `main` 히스토리에 **233개**
  (3개가 아니라).
- 부모 커밋 `85778e9`는 실제로 868개 파일의 완전한 프로젝트 트리를 갖고
  있었다 ("이 정도 분량을 담고 있지 않았을 것"이라는 추정이 틀림).
- `docs/PROJECT_STATUS.md` 안에 Session 11~38 기록이 실제로 존재한다
  (파일 라인 7: "Last Updated: 2026-09-17 (Session 38 계속...)") — 못
  찾은 이유는 `### Session N` 헤딩 형식만 찾고, 실제로 쓰인 다른 표기
  형식(`## Completed/Previous Subtask (Session 11~38 — Phase X)`)을
  놓쳤기 때문. 유실은 없었다.
- `ADR-0185`가 이 파일을 "Session 38까지 있고 HEAD보다 2일 뒤처졌다"고
  적은 것은 **옳았다** — 그 주장이 부정확했다고 의심한 것 자체가 이번
  섹션의 오류였다.

**교훈(향후 세션 규칙)**: git 이력 분석(특히 "이 커밋이 이상하게 크다/
파일이 사라졌다" 류의 판단)을 하기 전에 반드시
`git rev-parse --is-shallow-repository`로 확인하고, shallow면
`git fetch --unshallow` 후 다시 분석한다. "부모가 이 정도 분량을 담고
있지 않았을 것으로 추정된다" 같은, 실측하지 않은 추정을 근거로 사건을
단정하지 않는다. 복구 작업은 필요 없다 — 애초에 아무것도 유실되지
않았다.

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

## llmwiki 지속 갱신 규칙 (2026-09-24)

llmwiki는 자동으로 최신 상태를 유지하지 않는다 — 코드/ADR이 바뀐다고 따라서
갱신되는 훅이나 스케줄이 없고, 2026-09-24 세션에 사람이(Claude 세션이)
`wiki_create_entity`/`wiki_create_concept`/`wiki_ingest_with_context` 등을
직접 호출해서 채운 한 시점의 스냅샷이다. 앞으로도 다음 세션들이 이 규칙을
따라 갱신해야 계속 쓸모가 유지된다.

- **작업 단위를 끝내고 `main`에 병합하기 전에, 이번 작업이 위키의 기존
  내용을 stale하게 만들었는지 확인한다.** 예: 새 `src/` 모듈 추가, 기존
  모듈의 역할/경계 변경, `docs/specifications/PHASE-*.md` 신규·수정,
  아키텍처 수준 ADR 추가(개별 버그 수정 ADR 말고 — 여러 ADR을 관통하는
  주제나 새 서브시스템 도입), `docs/operations/`의 런북 신규·대폭 개정.
- **채우는 기준은 2026-09-24 세션에서 세운 것과 동일하게 유지한다** — 자주
  재사용되고 변경이 적은 것만 선별해서 넣는다. `docs/PROJECT_STATUS.md`
  처럼 세션별로 계속 append되는 로그성 파일, `README.md`의 `## 현재 상태`
  섹션처럼 고변동 콘텐츠는 넣지 않는다(위 "llmwiki MCP 도구" 절 참고).
  ADR 191개를 전부 넣는 식의 전량 ingest는 하지 않는다 — 신호 대 잡음
  비율이 떨어지고 유지보수 부채만 커진다.
- **엔티티/개념 페이지는 새로 만들기보다 기존 페이지를 수정하는 걸
  우선한다.** 이미 있는 모듈/개념에 대한 정보가 바뀐 거면
  `wiki_update_page`로 해당 페이지를 고치고, 완전히 새로운 모듈/개념일
  때만 새 페이지를 만든다. 오래된 정보가 남아있는 것보다는 위키가 아예
  없는 게 낫다 — 확인 안 하고 넘어가지 않는다.
- **병합 직전에 `wiki_lint`와 `wiki_status`를 돌려 오류/orphan이 없는지
  확인**하고, 위키 변경분은 관련 코드 변경과 같은 PR에 묶어서 커밋한다
  (토큰/비용 절약 규칙의 "작은 항목은 배치로" 원칙과 동일).
- 이 규칙은 실행을 강제하는 훅이 아니라 **세션이 스스로 확인해야 하는
  체크리스트**다 — 훅으로 강제하려면 위키에 뭘 넣을지 판단하는 LLM
  자체가 필요해서 결정론적 셸 스크립트로는 못 만든다. 따라서 이 CLAUDE.md
  규칙을 계속 읽고 지키는 것 자체가 유일한 갱신 메커니즘이다.

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
  (2026-09-24 세션에서 실제로 프로비저닝 워크플로를 돌려봄 — 인증/
  네트워킹(VCN/서브넷/보안리스트)/SSH 키 생성/러너 등록 토큰 발급까지
  전부 성공. 인스턴스 실제 생성(`launch_instance`) 단계에서만
  `"Out of host capacity."`로 실패 — 오라클 쪽 AP-TOKYO-1 리전의
  `VM.Standard.A1.Flex` 무료 티어 재고 소진 문제이지 워크플로 버그가
  아님.
  **2026-09-26 정정**: "다른 리전/AD로 바꿔볼 것"은 더 이상 유효한
  선택지가 아님 — 이 테넌시는 이미 리전 구독 개수 한도에 걸려 2번째
  리전 추가 시도가 실제로 "maximum number of regions... exceeded"
  오류로 거부됐다(`.github/workflows/provision_oci_colibri_runner.yml`
  자체 주석에 기록됨). 대신 그 워크플로가 `workflow_dispatch`뿐 아니라
  **schedule로 자동 재시도**하도록 이미 바뀌어 있음(수분~수시간 간격,
  인스턴스가 이미 있으면 스킵하고 스스로 스케줄을 끔) — **사용자가
  수동으로 재실행할 필요 없음**, 재고가 풀릴 때까지 그냥 기다리면 됨.
  가끔 Actions 탭에서 이 워크플로의 최근 실행 결과만 확인하면 충분.)
- ~~`run_full_validation.yml`용 Release 카탈로그 업로드~~ — **완료**
  (2026-09-24 사용자 업로드, `research-catalogs-v1` 태그). 절차/배경은
  `ADR-0193` 참고. `run_full_validation.yml`이 이 태그로 2026-09-24,
  2026-09-25 두 번 모두 성공(`success`) — 87종목 `RESEARCH_UNIVERSE`
  실데이터, 2010-01-01~2023-04-28, 51개 전략/팩터 후보 walk-forward
  검증. 2026-09-25 결과: 51개 전부 `INCONCLUSIVE`(확정 알파 입증된
  후보 없음, PBO 18.6%) — `docs/research/reports/
  full-validation-20260925T160732Z.json`.

### 10차 권고 리포트 기반 추가 항목 (2026-09-26)

10차(advisory, 스코어링 아님) 외부 검증 리포트가 권고한 항목 중, 이
세션이 계정/키 없이 자체적으로 진행할 수 있는 부분(예: `exchange_
calendars`/`purgedcv` 배선, `ADR-0207`)은 이미 처리했다. 남은 항목은
전부 외부 서비스 계정 생성/키 발급이 필요해 계정 소유자가 직접
해야 한다 — 아래 항목은 아직 구체적인 배선 설계(어떤 모듈이 호출할지,
실패 시 fail-open/fail-closed 여부 등)를 하지 않은 **권고 단계**이며,
위 KIS/colibri 항목처럼 이미 설계까지 끝난 상태가 아니다. 계정/키가
준비되면 세션에 알려주면, 그때 구체 설계를 잡고 진행한다.

- **healthchecks.io + Telegram 알림 연동**: 스케줄된 잡(예:
  `run_paper_trading_cycle.yml` 등)이 죽었을 때 감지하는 데드맨 스위치용.
  healthchecks.io 계정 생성 + 체크 URL 발급, Telegram Bot 토큰 발급(
  `@BotFather`) 필요. 발급된 값은 채팅에 붙여넣지 말고 GitHub Secrets에
  등록 — 위 KIS 항목과 동일한 패턴.
- **FRED API key** (`fred.stlouisfed.org`): 매크로 경제 데이터(금리,
  CPI 등) provider 후보. 무료 발급 가능 — 발급 후 `MARKET_DATA_API_KEY`
  패턴과 동일하게 GitHub Secrets에 등록.
- **Langfuse**: `ai_gateway`를 실제로 호출하는 provider가 아직 하나도
  없는 상태(위 "Grounding Gate 배선 보류 결정" 참고)라 지금 당장은
  관측할 실제 호출이 없다 — Langfuse 계정/키 자체는 미리 준비해둘 수
  있지만, 실제 배선은 `ai_gateway`에 첫 실호출부가 생기는 시점과 함께
  가는 게 자연스럽다.
- **Uptime Kuma + rclone**: 둘 다 colibri용 Oracle Cloud VM(위 항목,
  현재 재고 부족으로 자동 재시도 대기 중) 위에서 돌리는 것을 전제로
  한 권고였다 — VM이 실제로 확보되기 전에는 독립적으로 진행할 대상이
  없다. VM 확보 후 순서: (1) Uptime Kuma를 VM에 배포해 자체 상태
  페이지로 사용, (2) rclone으로 DuckDB/리포트 백업을 클라우드 스토리지로
  동기화하는 스케줄 설정.
- **51개 전략/팩터 후보 사람 리뷰**: 계정/키 발급이 아니라 판단이
  필요한 항목. `docs/research/reports/full-validation-20260925T160732Z.json`
  결과(51개 전부 `INCONCLUSIVE`, PBO 18.6%)를 사람이 직접 훑어보고,
  후보군을 더 좁히거나 가설을 다시 세울지, 아니면 이 유니버스/기간
  설정 자체를 바꿔서 재검증할지 결정하는 것 — 세션이 대신 결론 내릴
  수 없는 영역이다.

## Grounding Gate 배선 보류 결정 (2026-09-24)

ADR-0191이 미해결로 남긴 "derived-value 체크를 실제 prompt/schema에
배선"하는 작업 — **당분간 진행하지 않기로 계정 소유자가 명시적으로
결정함** (2026-09-24 세션에서 확인).

- 이유: 재확인해보니 `ai_gateway`를 실제로 호출하는 곳이 `src/` 전체에
  하나도 없음 — `predict`/`decision` 모두 결정론적 알고리즘만 쓰고,
  유일한 provider도 `MockProviderAdapter`(가짜 응답)뿐. 배선할 실제
  대상(schema/필드)이 존재하지 않는 상태에서 미리 설계하면 투기적
  설계가 될 위험이 있다고 판단.
- `src/ai_gateway/grounding.py`(`evaluate_formula`/
  `validate_derived_value`)와 `src/decision/entropy.py`
  (`normalized_entropy`)는 이미 구현·테스트된 채로 대기 중 — ADR-0151의
  "adopt now, wire in later" 전례를 따름.
- **재개 조건**: 실제 AI 기반 predictor/decision agent를 새로 만들 때
  (즉 `response_schema`를 실제로 쓰는 첫 호출부가 생길 때) 이 시점에
  다시 꺼내서, 그때 (1) 어떤 필드를 "derived"로 취급할지, (2) 검증
  실패 시 재시도할지 전체 응답을 fail-closed 시킬지 두 가지를 함께
  결정한다.

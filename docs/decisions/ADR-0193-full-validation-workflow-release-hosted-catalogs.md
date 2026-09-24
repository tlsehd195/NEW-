# ADR-0193: Full validation workflow, fed by Release-hosted catalogs

**Status:** Accepted
**Date:** 2026-09-24
**Deciders:** Claude Code (session continued), account owner (asked to
"github actions로 진행" -- run the two outstanding real-data items via
GitHub Actions rather than the account owner's own Codespace/Colab, and
picked the "download the already-collected catalog from a durable
location" option over "re-ingest everything from scratch in Actions"
when given the choice)

## Context

Two real-data items remain outstanding (`STRATEGY-VALIDATION-REPORT.md`'s
"Outstanding real results not yet received" section): the `insider_buying`
factor's real raw IC, and a full walk-forward/PBO/DSR run including every
factor (22 of them, plus this session's own new `ml_tree`, ADR-0192)
added since the last real run. Both require the 87-symbol
`RESEARCH_UNIVERSE_STAGE4` price+fundamentals catalog, which already
exists -- collected for real in the account owner's Google Colab session
(Session 37), confirmed complete, and currently living on Google Drive.

This session's own network egress is blocked to every data provider
(verified directly, `ADR-0192`), and the account owner's Codespace and
Colab sessions both have real reliability limits (Codespace: a free-tier
usage budget that has already been exhausted once; Colab: a hard 12-hour
session disconnect). GitHub Actions runners have their own, independent
outbound network path, already verified for real by this project
(`ingest_fama_french_factors.yml`'s own docstring: confirmed reaching
`mba.tuck.dartmouth.edu` with real HTTP 200s; `ingest_insider_transactions_
full.yml` has real, successful real-SEC-data runs on record) -- and,
crucially, a workflow run is not a session anyone has to keep open: it
starts, runs to completion (up to 6 hours per job on `ubuntu-latest`),
and finishes unattended.

**Re-ingesting 87 symbols x ~13 years from scratch inside a new Actions
workflow was considered and rejected**: it would duplicate real work
already done in Colab, cost many additional hours against provider rate
limits, and gain nothing the existing catalog doesn't already have. The
account owner was asked and chose "download the existing catalog" over
"re-ingest."

**Workflow artifacts were considered and rejected as the transport for
that catalog**: this project's own workflows already default artifacts
to 90-day retention, and this catalog needs to remain available and
reusable indefinitely (every future validation run should be able to
reuse it, not just the next one within 90 days). A GitHub Release asset
has no automatic expiry -- the account owner uploads the catalog there
once, and it stays available until someone explicitly deletes it.

## Decision

Add `.github/workflows/run_full_validation.yml`: a `workflow_dispatch`-only
job that downloads `price_catalog.zip`/`fundamentals_catalog.zip`
(required) and `insider_catalog.zip` (optional -- the insider_buying
candidate is skipped when absent, exactly like omitting
`--insider-db-path` on the CLI) from a Release the account owner
specifies by tag, unzips each into the directory shape
`storage.config.StorageEngine` expects (a directory containing
`catalog.duckdb`), then runs `scripts/run_long_horizon_validation.py`
against them with `--data-status REAL` and uploads the resulting JSON
report as a workflow artifact.

`--start`/`--end` default to `2010-01-01`/`2023-04-28` -- the exact
pre-`TEST_1` boundary every prior real Stage-3/4 run has used
(`STRATEGY-VALIDATION-REPORT.md`'s Phase 33 addendum), kept as the
default so a future dispatch doesn't silently drift to a different,
un-reviewed range; both remain overridable inputs since
`run_long_horizon_validation.py`'s own `TEST_1`-overlap guard refuses
an invalid range regardless of what this workflow passes it.

**Not done by this session (the account owner's own next step)**:
creating the Release itself and uploading the two (or three) zipped
catalogs to it. This session cannot reach Google Drive to fetch them,
so it cannot upload them either -- and no GitHub Release-creation tool
is available to this session's GitHub integration (only read access to
releases). Exact upload steps are recorded in CLAUDE.md's "사용자 액션
대기 항목" section.

## Consequences

- Once the Release is populated, this workflow can be re-run for any
  future universe/date-range/catalog update without any code change --
  just a new Release tag or new assets on the existing one.
- The account owner never needs Codespace or a live Colab tab for this
  specific validation run again; only for producing a fresh catalog to
  upload, which is a separate, occasional task.
- `insider_buying`'s real result depends on `ingest_insider_transactions_
  full.yml`'s own auto-published Release (see 2026-09-24 addendum below)
  having a current catalog -- automatic, no manual upload step.

## 2026-09-24 후속 수정 -- 90일 아티팩트에 의존하는 구간을 전부 제거

이 ADR을 처음 쓸 때는 "검증 리포트는 작고 언제든 재생성 가능하니 90일
아티팩트 보관이면 충분하다"고 판단했다. **계정 소유자가 실제로 지적한
문제**: 그 리포트를 90일 안에 durable한 곳(git, Release 등)으로 옮기는
작업 자체가 **Claude 세션이 돌아와서 확인해야 이뤄지는 수동 절차**였다
— 계정 소유자가 Claude Code를 안 쓰게 되면 그 절차 자체가 멈추고,
아티팩트는 그냥 만료되어 결과가 사라진다. "체크인을 걸어두겠다"는
제안도 결국 Claude 세션이 계속 개입해야 하는 거라 같은 문제의 재포장일
뿐, 진짜 해결책이 아니었다.

**수정**: 사람/AI 개입 없이 워크플로 자신이 매번 무조건 영구 저장하도록
바꿈.

- `run_full_validation.yml`: `--report-out` 결과를 90일 아티팩트에
  더해 **`docs/research/reports/`에 직접 git commit + push**(봇
  커밋, `keepalive.yml`과 동일한 패턴) — `permissions.contents`를
  `read`→`write`로 변경.
- `ingest_insider_transactions_full.yml`의 `merge` job: 병합된
  카탈로그를 90일 아티팩트에 더해 **고정된 Release 태그
  (`insider-transactions-catalog`)에 자동 업로드**(`gh release
  create`/`gh release upload --clobber`, 매 성공한 merge마다 무조건
  실행) — 마찬가지로 `contents`를 `write`로 변경.
- `run_full_validation.yml`의 insider 카탈로그 다운로드 단계는 이제
  계정 소유자가 지정한 release, 그리고 실패 시 이 고정 태그
  순서로 시도 — insider_buying 후보가 **수동 업로드 없이도** 항상
  최신 데이터로 검증됨.

가격/재무제표 카탈로그(구글 드라이브 원본)만은 여전히 계정 소유자의
1회성 수동 업로드가 필요하다 — 이 세션이 드라이브에 접근할 방법이
없어서 자동화할 수 없는, 진짜 사람만 할 수 있는 부분이기 때문.

## Tests

`tests/deploy/test_run_full_validation_workflow.py`: manual-dispatch-only,
`contents: write` permissions, concurrency group + timeout present,
required inputs and their defaults (including the `TEST_1`-boundary
`--end` default), Release-based (never `actions/download-artifact`)
catalog download for the two required catalogs, the optional
insider-catalog download tries the account owner's release then falls
back to the auto-published one without failing the job, the validation
script is invoked with both required `--db-path`s and the
`$INSIDER_FLAG` variable, the 90-day artifact upload uses `if: always()`
with `if-no-files-found: warn`, and the durable git-commit step exists,
guards against committing a missing report, and actually pushes.
`tests/deploy/test_ingest_insider_transactions_full_workflow.py`
(updated): `contents: write`, and a new test that the merge job's
Release-publish step creates the release only if missing, always
`--clobber`s the asset, runs `if: always()`, and guards against
publishing a missing/stale catalog. Full suite run before merge as the
merge gate (see PR).

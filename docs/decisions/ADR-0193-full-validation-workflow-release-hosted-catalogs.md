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
report as a workflow artifact (the report itself is a small, freely
regenerable summary, unlike the source catalogs -- 90-day artifact
retention is the right tradeoff there, not a problem to solve).

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
- `insider_buying`'s real result depends on the separately-tracked
  `ingest_insider_transactions_full.yml` re-run (shard 8's AVB CIK
  failure, already fixed in code, re-run this session) landing in the
  Release too -- not automatically wired, since that catalog comes from
  a different pipeline on its own schedule.

## Tests

`tests/deploy/test_run_full_validation_workflow.py`: manual-dispatch-only
and read-only permissions, concurrency group + timeout present, required
inputs and their defaults (including the `TEST_1`-boundary `--end`
default), Release-based (never `actions/download-artifact`) catalog
download for the two required catalogs, the optional insider-catalog
download branches on its own success rather than failing the job,
the validation script is invoked with both required `--db-path`s and
the `$INSIDER_FLAG` variable, and the report upload uses
`if: always()` with `if-no-files-found: warn`. Full suite run before
merge as the merge gate (see PR).

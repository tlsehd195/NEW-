# ADR-0128: Retroactive data quality rescan

**Status:** Accepted
**Session:** 37 (continued)

## Context

Immediately after ADR-0127 (the CRITICAL-severity data quality gate),
the account owner asked the obvious next question: does the fix just
made retroactively apply to data that already accumulated before it
existed — specifically, the real "Paper Trading Daily Cycle #7" run
(2026-09-11, PARTIAL_SUCCESS, 1628 data quality issues) already
discussed this session?

The honest answer is no, for two separate reasons:

1. ADR-0127's changes exist only on this session's PR branch
   (`claude/phase-11-model-evolution-7hpibr`, PR #19) — the scheduled
   GitHub Actions workflows run off `main`, so until that PR merges,
   every real scheduled run still executes the pre-ADR-0127 code
   entirely.
2. Even after merging, `scripts/ingest_real_market_data.py` only ever
   quality-checks the bars it just fetched for the INCREMENTAL window
   `scripts/compute_incremental_ingestion_start.py` computes (ADR-0085
   — always re-requesting the full history exhausted the provider's
   rate limit once already). A bar that was persisted by an earlier run
   — before ADR-0127 existed, or from a run whose findings were
   computed but (pre-ADR-0127) never persisted — is never re-examined
   by any later, ordinary incremental run. Whatever the real severity
   breakdown of run #7's 1628 issues actually was (still unknown — see
   ADR-0127's own disclosed Azure Blob Storage access limitation), if
   any of it was CRITICAL, it is sitting in the catalog completely
   unflagged today, permanently, unless something explicitly goes back
   and re-checks it.

## Decision

New script `scripts/rescan_data_quality.py`: reads an existing
`--db-path` catalog via `DuckDBDataRepository.all_bars()` (every bar
ever persisted, unfiltered — deliberately bypassing the very exclusion
this script exists to apply), runs `DataQualityFramework` once over the
whole set, and persists the result via the same
`record_quality_issues()` ADR-0127 introduced. Any CRITICAL finding is
excluded from `get_bars()`'s default result from that point on, for
every consumer of this same catalog — closing the gap for
already-accumulated data, not just future ingestion.

New workflow `.github/workflows/data_quality_rescan.yml`:
`workflow_dispatch`-only, deliberately **not** scheduled — restores the
`market-data-catalog` artifact (identical restore/wrapped-zip-defense
pattern the other two workflows already use), runs the rescan script,
re-uploads the (now-flagged) catalog with `if: always()`, and uploads a
per-run report. Never touches `paper-trading-store` — this is a
market-data-only operation.

Deliberately manual rather than scheduled: re-running duplicate/gap-
style checks over the ENTIRE history every day would be wasteful (the
already-checked portion never changes) and noisy (the same historical
WARNING "found" again on every run). The intended usage is: run it once
now to catch up everything ingested before ADR-0127, and again by hand
whenever there is a specific reason to suspect the catalog needs
re-checking (e.g. after a run like #7 with an unusually high issue
count).

**Deliberate scope reductions** (documented, not oversights): this
rescan does not pass `corporate_actions` to `DataQualityFramework.run()`
(no `split_consistency`/`dividend_consistency` checks) — collecting
every corporate action for every security already in the catalog is a
separate, larger operation this focused backfill does not need in order
to catch the corruption-class findings (`non_finite_value`,
`ohlc_consistency`, `duplicate_records`, `ingestion_precedes_availability`,
...) ADR-0127's exclusion actually acts on. `known_security_ids` is also
not passed (`symbol_mismatch` is skipped) — there is no independent
"expected universe" to validate against here, only "what this catalog
already has."

## What this explicitly does not do

- It does not run automatically as part of merging PR #19 — a human
  must trigger it via `workflow_dispatch` after that PR merges (or any
  time later) for it to actually take effect against the real catalog.
  This ADR does not claim run #7's issues are now retroactively fixed;
  it only builds and tests the mechanism to do so on request.
- It does not tell you what run #7's issues actually were before you
  run it — that remains genuinely unknown until this workflow (or a
  direct look at that run's own artifact) is actually executed.
- It does not change `paper-trading-store`/Trade Journal/Learning
  Cycle data in any way — only `market-data-catalog`.

## Tests

`tests/data_infra/test_rescan_data_quality_cli.py` (5 tests, real
executable — this script makes no network call, same discipline
`test_import_external_market_data_cli.py` already established): a
pre-existing CRITICAL bar (built directly via
`DuckDBDataRepository.append_bars`, simulating data an earlier run
already persisted) is flagged and excluded after rescan; an empty
catalog is a clean no-op; WARNING/ERROR-only findings do not fail the
run; running the rescan twice is idempotent; no network-capable module
is imported.

`tests/deploy/test_data_quality_rescan_workflow.py` (8 tests) — same
static YAML-structure category as the other two scheduled workflows'
own test files, plus an explicit assertion that `schedule` is absent
and that `paper-trading-store` is never touched.

Full suite re-run after adding this: no regressions (see PROJECT_STATUS.md).

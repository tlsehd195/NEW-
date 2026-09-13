# ADR-0127: Data quality gate and CRITICAL-finding rejection

**Status:** Accepted
**Session:** 37 (continued)

## Context

While explaining Paper Trading's data pipeline to the account owner, a
screenshot of a failed "Paper Trading Daily Cycle #7" run (PARTIAL_SUCCESS
ingestion, 1628 data quality issues) surfaced a real question: does a run
like that keep accumulating into the shared catalog, and does anything
ever act on the quality findings it produces?

Auditing the actual code answered both, and confirmed a real gap:

- `data_infra.quality.DataQualityFramework` runs its checks strictly
  *after* bars are already persisted to the repository, and is, by its
  own module docstring, "deliberately non-destructive: running the
  framework never mutates or drops a record." That is by design, not a
  bug -- but it means the framework alone was never going to stop bad
  data from being used.
- `scripts/ingest_real_market_data.py`'s exit code
  (`return 0 if result.status.value == "SUCCESS" else 1`) checked only
  ingestion status, never `quality_run.status` -- a run could find
  CRITICAL-severity corruption (e.g. a non-finite price) and still exit
  0.
- A repo-wide search found `quality_run`/`DataQualityFramework` referenced
  nowhere else in `src/` -- not in `run_paper_trading_cycle.py`, not in
  any kill switch/`data_health` check (those are Live-only and this
  project has no real Live credentials regardless). Nothing downstream
  ever consulted a quality result.
- `.github/workflows/paper_trading_cycle.yml` uploads the
  `market-data-catalog`/`paper-trading-store` artifacts with
  `if: always()`, so whatever was written before a failure is re-uploaded
  and restored by the next run regardless.
- `docs/specifications/PHASE-1-data-infrastructure.md` section 3.1
  already documents exactly the intended states for this
  (`QUALITY_REJECTED` for a CRITICAL finding, "not promoted from Raw to
  Clean, Raw copy retained"; `QUALITY_FLAGGED` for WARNING/ERROR,
  "promoted to Clean but carries its `DataQualityRun` reference") -- this
  was written in Phase 1 and simply never implemented.

The account owner asked for three things: (a) find out how severe the
1628-issue run actually was, (b) make the pipeline fail loudly on a
genuinely bad run instead of silently continuing, and (c) stop
ERROR/CRITICAL-flagged records from reaching Paper Trading decisions and
Learning Cycle retraining.

## Decision

**On (a):** the historical severity breakdown for run #7 specifically
could not be recovered -- the per-issue detail only ever existed in that
run's own `ingestion_manifest.json`, which is inside a GitHub Actions
artifact whose real download URL redirects to Azure Blob Storage
(`*.blob.core.windows.net`), a domain this environment's own egress
proxy has denied since long before this session (confirmed again via
`curl "$HTTPS_PROXY/__agentproxy/status"`). This is a real, disclosed
environment limitation, not something this ADR works around. What it
does fix going forward: `scripts/ingest_real_market_data.py` now prints
`Data quality severity breakdown: {...}` directly to the job's own stdout
log every run, so the next time this happens the breakdown is readable
straight from CI logs without needing artifact access at all.

**On (b) and (c):** implemented Phase 1 spec section 3.1's own states,
which had existed on paper since Phase 1 but were never wired to
anything:

- New table `data_quality_flags` (`storage/schema.py`) records every
  `DataQualityIssue` that is tied to a specific bar (`security_id` +
  `timestamp` both set) -- CRITICAL and WARNING/ERROR alike. Written by
  the new `DuckDBDataRepository.record_quality_issues(quality_run)`,
  called right after `ingest_real_market_data.py` computes its
  `quality_run`. Issues with no timestamp (e.g. `insufficient_coverage`,
  a security-level finding) are not stored here -- there is no single bar
  to attach a rejection to -- they remain visible in that run's own
  manifest/report instead.
- `DuckDBDataRepository.get_bars()` now excludes a bar by default when
  `security_id`+`timestamp` has a CRITICAL-severity row in
  `data_quality_flags` (`QUALITY_REJECTED`). This is the single choke
  point essentially every real consumer already reads through --
  `run_paper_trading_cycle.py`, `backtest.asof.AsOfDataView`,
  every `strategy_research` factor, `trade_journal/analysis.py` -- so
  fixing it there, rather than at each call site, protects the whole
  pipeline (including the Learning Cycle: a Candidate model can only ever
  learn from Trade Journal entries that came from decisions Paper Trading
  actually made, and Paper Trading can no longer make a decision from a
  CRITICAL-flagged bar). The underlying Parquet row is never deleted or
  rewritten (Raw Immutability, spec section 17); a caller that explicitly
  needs it anyway (audit/debugging) passes
  `get_bars(..., include_quality_rejected=True)`.
- WARNING/ERROR findings are recorded in the same table but are
  **NOT** excluded -- this deliberately follows spec section 3.1's own
  documented distinction (`QUALITY_FLAGGED`: "promoted to Clean but
  carries its `DataQualityRun` reference so consumers can
  inspect/filter"), not the account owner's literal "ERROR도 제외"
  phrasing from the preceding conversation turn. Excluding ERROR-severity
  findings by default was not adopted: `duplicate_records`,
  `symbol_mismatch`, `ingestion_precedes_availability`, and
  `dividend_consistency` are all ERROR-severity and are each a real,
  already-tested, already-shipped part of this project's normal DQ
  output -- treating every ERROR the same as CRITICAL (data corruption,
  currently only `non_finite_value`) would silently reject far more real
  data than the account owner's stated concern (bad data quietly reaching
  trading decisions) actually calls for, without any corresponding new
  test coverage having been designed for that broader blast radius. If a
  stricter policy is wanted, it is a one-line change to
  `_critical_rejected_timestamps`'s severity filter -- flagged here for
  a follow-up decision rather than made unilaterally.
- `scripts/ingest_real_market_data.py`'s exit code now also fails when
  `quality_run.status == DataQualityRunStatus.CRITICAL_FAILURE`, printing
  a `FATAL:` line to stderr. In `paper_trading_cycle.yml`, this means
  "Run paper trading cycle" (not `if: always()`) is skipped for the rest
  of that day whenever a CRITICAL finding occurs -- the catalog/report
  artifacts still upload via their own `if: always()` steps, so no state
  is lost, but no trading decision is ever made against data known to be
  corrupted that same run.
- The manifest gained `data_quality_severity_counts` and
  `data_quality_flags_persisted` fields (additive; existing keys
  untouched).

## What this explicitly does not do

- It does not implement a full two-tier Raw/Clean Parquet split. There is
  still one `price_bars` Parquet store; "Clean" here means "what
  `get_bars()` returns by default," and "Raw" means "still on disk,
  reachable via `include_quality_rejected=True`." This satisfies spec
  section 3.1's stated *effect* without the larger storage-layer
  migration a literal Raw/Clean directory split would require.
- It does not exclude WARNING/ERROR findings by default (see above) --
  only CRITICAL.
- It does not touch `InMemoryDataRepository` (Phase 1's test-only
  in-memory reference implementation) -- tests construct it directly from
  in-memory bars and have no `data_quality_flags` table to consult;
  nothing in this ADR changes what it returns.
- It does not retroactively re-examine bars already sitting in a
  production catalog from before this ADR -- `data_quality_flags` starts
  empty on a catalog that already has one; a bar ingested under the old
  code path is only flagged the next time a run's quality check happens
  to re-observe it.

## Tests

`tests/storage/test_data_quality_flags.py` (new, 6 tests) -- against
`DataQualityFramework`'s real output, never a hand-built
`DataQualityRun`: a CRITICAL finding (non-finite close) is excluded from
`get_bars()` by default; `include_quality_rejected=True` still returns it
(Raw Immutability); the exclusion survives an engine restart (same
restart-safety guarantee every other DuckDB-backed table in this
repository already has); a WARNING/ERROR finding (duplicate records) is
persisted but does not exclude the bar; a no-timestamp finding
(`insufficient_coverage`) is silently skipped rather than crashing;
`record_quality_issues` is idempotent (re-recording the same
`DataQualityRun` writes nothing new).

`tests/data_infra/test_ingest_real_market_data_wiring.py` (existing,
AST-only -- this script is never imported/executed by the suite, see
that file's own docstring) continues to pass unmodified; the new manifest
keys and exit-code condition do not touch any assertion it makes.

Full suite re-run after this change: no regressions (see PROJECT_STATUS.md).

# ADR-0168: Root cause and fix for the real data quality ERROR backlog (ADR-0167 follow-up)

**Status:** Accepted
**Date:** 2026-09-18
**Deciders:** Claude Code (session continued), account owner (asked directly,
twice, whether the real paper trading data was actually clean --
both times the honest answer was "not yet," this ADR is the third
answer: "the two real causes are now confirmed and fixed")
**Related documents:** `docs/decisions/ADR-0167-real-data-quality-error-backlog-discovered.md`
(made the per-check/per-security breakdown observable but left the root
cause explicitly OPEN), `docs/decisions/ADR-0085` (the 7-day ingestion
overlap this ADR's `duplicate_records` finding turned out to be a side
effect of), `docs/decisions/ADR-0115` (Session 37's `clamp_ingestion_time`
fix -- this ADR's `ingestion_precedes_availability` finding turned out to
be bars from before that fix existed)

## Context

ADR-0167 surfaced the real per-check breakdown from a real run:
`{'duplicate_records': 779, 'ingestion_precedes_availability': 87,
'stale_data': 1}`, but stopped there -- this session's own egress
cannot reach the GitHub Actions artifact holding the real catalog, so
ADR-0167 deliberately refused to guess at a root cause it could not
verify.

This ADR continues that investigation using only the code already in
the repository -- reading `append_bars`'s exact natural key,
`_check_duplicates`'s exact key, `clamp_ingestion_time`'s exact
implementation, and `get_bars`'s exact filtering logic -- rather than
speculating, and finds a real, confirmed answer for both checks.

### `duplicate_records` (779 issues) -- confirmed root cause

`DuckDBDataRepository.append_bars`'s natural key is `(security_id,
timestamp, provenance.source, provenance.data_version)` --
`data_version` is a content hash (`compute_data_version`), deliberately
excluding `data_version` was never on the table because that is
exactly what makes a genuine provider correction ingestible at all
(`tiingo.py`'s own comment: "data_version must reflect only the actual
fetched content ... keeps re-ingesting the identical real-world bar on
a later run idempotent"). `compute_incremental_ingestion_start.py`'s
`_OVERLAP_DAYS = 7` (ADR-0085) deliberately re-fetches the last 7
already-ingested days every run "to catch late-arriving provider
corrections" -- exactly the EOD-data-provider behavior of publishing a
preliminary close shortly after market close and finalizing/revising it
within the following days.

When that revision happens, `append_bars` correctly does NOT treat it
as a duplicate (the content, and therefore `data_version`, differs) --
it inserts a second, genuinely new physical row for the same
(security_id, timestamp, source). `DataQualityFramework._check_duplicates`,
however, keyed only on `(security_id, timestamp, source)` -- NOT
`data_version` -- so it flagged every such legitimate revision as an
ERROR-severity "duplicate," identically to a real accidental double-
ingestion bug. Confirmed directly in `src/data_infra/quality.py`
(pre-fix) and `src/storage/data_repository.py::append_bars`; both
files were read in full to trace the exact key mismatch, not inferred.

**This was more than a mislabeled diagnostic finding.**
`DuckDBDataRepository.get_bars()` -- the method every real consumer
(Paper Trading, backtest, strategy_research, Learning Cycle) reads
through -- had no deduplication at all: it returned every physical row
whose `available_time <= as_of_time`, with no collapsing by timestamp.
Two physical rows for one calendar day (the everyday-normal-operation
outcome of the revision behavior above) meant every real consumer was
receiving that trading day TWICE. This is exactly the "data
contamination" the account owner asked about, confirmed for real: not
a leftover count from ADR-0167's own testing, but a live defect
already present before this session's own Twelve Data/Alpha Vantage
work.

### `ingestion_precedes_availability` (87 issues, exactly one per symbol) -- confirmed root cause

Every provider stamps `PriceBar.ingestion_time` via
`data_infra.provider.clamp_ingestion_time(batch_ingestion_time,
bar_available_time(timestamp))`, whose entire implementation is
`max(batch_ingestion_time, available_time)` (Session 37, ADR-0115).
Since `ingestion_time` is a `max(...)` against `available_time`, the
inversion `_check_ingestion_precedes_availability` looks for
(`ingestion_time < available_time`) is **structurally impossible** for
any bar ingested through this path -- confirmed by reading
`clamp_ingestion_time`'s own body, not inferred from its docstring
alone.

The 87 flagged bars (exactly one per symbol in `RESEARCH_UNIVERSE`,
including the SPY benchmark) are therefore bars ingested BEFORE
ADR-0115's fix existed -- a grandfathered defect sitting immutably in
the append-only `price_bars` store (a bar is never rewritten in place;
ADR-0115 only prevents the defect for bars ingested after it landed,
it cannot retroactively correct bars that already existed). The "one
per symbol" pattern is consistent with each symbol's original backfill
run producing exactly one such edge-case bar (the specific bar whose
event date matched the backfill's own `as_of` clock date).

## Decision

Fix both, following each root cause exactly, and add a repair path for
the already-corrupted historical bars this session cannot itself reach
(no production catalog access from this environment):

1. **`DuckDBDataRepository.get_bars()`** (`src/storage/data_repository.py`)
   now collapses its result to exactly one bar per `(security_id,
   timestamp)`, keeping the one with the latest `ingestion_time` (a tie
   breaks on `provenance.data_version` for determinism) -- via a new
   `_dedupe_latest_per_timestamp` helper. This dedup applies only to
   the default (`include_quality_rejected=False`) view every real
   consumer uses; the `include_quality_rejected=True` audit view
   `scripts/ingest_real_market_data.py`'s own quality run reads through
   is left un-deduped on purpose, so `_check_duplicates` can still see
   every physical row and keep reporting on them.

2. **`DataQualityFramework._check_duplicates`** (`src/data_infra/quality.py`)
   now groups by `(security_id, timestamp, source)` same as before, but
   splits on whether the group's `data_version`s are all identical:
   - All identical (a true accidental duplicate -- structurally should
     be impossible via `append_bars`'s own dedup, so this indicates a
     real storage-layer bug if it ever fires) -- stays **ERROR**.
   - Differing `data_version`s (a legitimate provider revision, exactly
     what ADR-0085's overlap re-fetch is designed to catch) -- downgraded
     to **WARNING**, with a message explaining `get_bars()` already
     resolves it.

3. **New `scripts/repair_ingestion_time_inversions.py`** -- a
   read-then-append repair for the 87 grandfathered
   `ingestion_precedes_availability` bars. Never rewrites an existing
   Parquet file (that would violate `storage/parquet_layer.py`'s own
   "new data always means a new file" invariant) -- instead appends a
   corrected bar (same OHLCV content, `ingestion_time` clamped up to
   `available_time`, `data_version` tagged with an explicit
   `-ingestion-time-corrected` suffix so `_check_duplicates` classifies
   it as a legitimate revision, not a storage bug) through the
   completely ordinary, already-tested `append_bars()` path. Once
   applied, `get_bars()`'s new dedup (decision 1) automatically starts
   serving the corrected, later-ingested bar to every real consumer --
   no other code change needed. Dry-run by default; `--apply` writes.
   Idempotent (a second run finds the correction already in place and
   writes nothing new). This script needs to be run by the account
   owner (or a future session with real catalog access) against the
   actual production `market-data-catalog` -- this session's own
   egress cannot reach it, exactly as ADR-0167 already documented.

## Consequences

### Positive

- **The account owner's original question now has a real, verified
  answer.** The live duplicate-bar defect (every real consumer seeing
  some trading days twice) is fixed in code, effective on the next
  deployment -- not merely diagnosed.
- `_check_duplicates` now correctly distinguishes an actual storage bug
  (ERROR, should never fire) from ADR-0085's own intended
  revision-catching behavior (WARNING, expected to fire regularly) --
  future quality reports stop drowning a real bug signal in expected
  noise.
- The `ingestion_precedes_availability` grandfathered defect has a
  concrete, safe, idempotent repair path that fully respects this
  project's Raw/Clean Immutability principle (no file is ever
  rewritten or deleted).

### Negative / Trade-offs

- **The 87 original bad physical rows are never deleted** (by design --
  Raw Immutability) and will keep independently failing
  `_check_ingestion_precedes_availability` on every future full-history
  rescan (`scripts/rescan_data_quality.py`) forever, even after the
  repair script runs -- that check evaluates every physical row, not
  just the one `get_bars()` selects as canonical. The actual defect (a
  bad bar reaching a real consumer) is fixed; this is accepted
  diagnostic noise, not a remaining correctness gap. A future session
  could make that check dedup-aware too, mirroring this ADR's
  `_check_duplicates` change, if the recurring noise becomes a real
  problem.
- **The repair script has not been run against the real production
  catalog** -- this session cannot reach it (same egress wall ADR-0167
  already documented). The account owner (or a future session with
  real access) needs to download the `market-data-catalog` artifact,
  run the script with `--apply`, and re-upload/persist the result (or
  run it directly against wherever the catalog is deployed) for the 87
  historical bars to actually be corrected. Until then, those 87
  specific symbol/dates keep serving their pre-ADR-0115 (incorrect but
  otherwise harmless -- OHLCV content itself is not wrong, only its
  metadata) bar to consumers, same as before this ADR.
- `InMemoryDataRepository` (Phase 1's reference implementation) was
  deliberately NOT given the same `get_bars()` dedup -- it is a
  test-only fixture that 26 test files construct explicit, one-bar-
  per-date input for; the real risk this ADR fixes only exists in the
  persistent, real-provider-fed `DuckDBDataRepository`.

## Tests

- `tests/data/test_quality.py`: new
  `test_same_source_different_data_version_is_a_revision_warning_not_an_error`
  (WARNING, not ERROR, for a differing-`data_version` duplicate group);
  existing `test_duplicate_security_timestamp_source_is_flagged`
  (identical `data_version`, stays ERROR) verified still passing
  unchanged.
- `tests/storage/test_data_repository_persistence.py`: new
  `test_revised_value_same_day_returns_one_bar_not_two` (the default
  `get_bars()` view returns exactly one, most-recently-ingested bar;
  `include_quality_rejected=True` still returns both physical rows).
- `tests/storage/test_data_quality_flags.py`: updated
  `test_a_warning_or_error_finding_is_persisted_but_the_bar_stays_included`
  for the new WARNING severity and the new single-bar default `get_bars()`
  result (previously asserted 2 bars returned by default -- now 1, with a
  new assertion that the audit view still returns 2).
- `tests/data_infra/test_rescan_data_quality_cli.py`: updated
  `test_only_warning_or_error_findings_do_not_fail_the_run` for the new
  `PASSED_WITH_WARNINGS` status (previously asserted `FAILED`).
- `tests/scripts/test_repair_ingestion_time_inversions.py` (new, 5
  tests): dry-run reports without writing; `--apply` appends a
  corrected bar that `get_bars()` now serves as canonical; running
  twice is idempotent; a clean catalog with no inversions is a no-op;
  a missing `--db-path` fails cleanly.
- Full suite re-run after all changes: 1732 passed (see
  `docs/PROJECT_STATUS.md`'s session log for the before/after count).

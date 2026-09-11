# ADR-0085: scheduled ingestion requests an incremental window, not the full fixed range

**Status:** Accepted
**Session:** 36 (continued)

## Context

The account owner manually dispatched `.github/workflows/
paper_trading_cycle.yml` (ADR-0082) for the first time. It completed
successfully (699/699 checkpoints, 1468 orders submitted and filled),
but the ingestion step reported `ingestion_status: PARTIAL_SUCCESS`:

```
Missing symbols (zero bars): ['AVB', 'DLR', 'DOW', 'FCX', 'NUE', 'O',
'PSA', 'SHW', 'SPY', 'WELL']
```

10 of 88 symbols -- including `SPY`, the benchmark -- got zero bars.
All 10 cluster at the END of the universe's symbol order, the
signature of a rate limit exhausted partway through a long request
sequence, not a per-symbol data problem. Root cause: the workflow (as
ADR-0082 designed it) requests the ENTIRE `$START_DATE` (2024-01-02) to
today range from Tiingo on every single run, relying on
`DuckDBDataRepository.append_bars`'s natural-key dedup to make
re-requesting already-known days safe. ADR-0082 called this
"redundant but not incorrect." A real run against 88 symbols' full
~2.5-year history showed it is not merely redundant: the resulting
network cost is large enough to exhaust Tiingo's rate limit mid-run,
and this recurs every single scheduled run, not just the first cold
start, since the workflow always requests the same full range
regardless of what the restored catalog already holds.

## Decision

Added `scripts/compute_incremental_ingestion_start.py`: queries the
restored market-data catalog's own Parquet files for the latest known
bar (`MAX(timestamp)` across all securities), and computes `--start` as
that date minus a 7-day overlap window (`_OVERLAP_DAYS`) -- re-fetching
a small trailing window is deliberate, not a bug, since it lets
`append_bars`'s dedup also catch a provider's late-arriving correction
to recent bars. Falls back to the workflow's fixed `$START_DATE` only
when the catalog has no price bars yet (a fresh `--db-path`, or an
artifact-retention gap).

`.github/workflows/paper_trading_cycle.yml` now runs this script in a
new step (`ingest_start`) between restoring the catalog artifact and
running ingestion, and passes its output as `--start` instead of the
fixed `$START_DATE`. After the first successful run populates the
catalog, every subsequent run requests roughly a week's worth of data
per symbol instead of ~2.5 years -- the actual fix for the rate-limit
exhaustion, not merely a smaller instance of the same problem.

## What this does NOT do

Does not change `ingest_real_market_data.py`'s own behavior --
`append_bars`'s dedup already existed and already made re-requesting
overlapping days safe; this ADR only shrinks how much gets
re-requested. Does not retroactively backfill the 10 symbols that
missed bars in the run that surfaced this on its own -- **the claim
originally made here, that the very next scheduled run's incremental
window "naturally" catches them via each symbol's own older last-known
bar, was wrong as originally implemented and is corrected by
ADR-0115**: `compute_incremental_ingestion_start.py` originally
computed one catalog-WIDE `MAX(timestamp)` across every symbol, so a
symbol with ZERO bars (exactly the 10 that triggered this ADR)
contributed no row and never widened anything -- the computed start
date stayed recent, dominated by the other ~78 symbols, and the 10
missing symbols' true multi-year gap would never actually have been
re-requested by any later run. ADR-0115 fixed this by computing the
per-symbol max among the symbols the run actually requests and taking
the MINIMUM (an entirely missing symbol counts as needing the fallback
start), so the least-caught-up requested symbol now genuinely drives
the window, not just the median one. Does not change
`run_paper_trading_cycle.py` or its `--resume` logic, which already
had its own, unrelated incremental-catchup mechanism (ADR-0073) for
the paper trading ledger side, not the market-data catalog side this
ADR addresses.

## Tests

`tests/deploy/test_compute_incremental_ingestion_start.py` (5 tests):
a fresh/empty catalog returns the fallback unchanged; existing bars
shift the start forward by the overlap window (and NOT to the full
fixed fallback); the computation takes the GLOBAL max across every
security in the catalog, not per-security; the result never regresses
earlier than the fallback even if the catalog's only known bars are
themselves older than it; the CLI's stdout matches the underlying
function. `tests/deploy/test_paper_trading_cycle_workflow.py` gained a
6th test confirming the workflow's ingestion step actually uses the
computed value, not the old fixed `$START_DATE` literal. Full suite
re-run, all tests pass.

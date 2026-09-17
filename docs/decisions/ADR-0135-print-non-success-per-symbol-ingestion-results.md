# ADR-0135: Print non-SUCCESS per-symbol ingestion results to stdout

**Status:** Accepted
**Session:** 37 (continued)

## Context

The scheduled "Paper Trading Actions health check" routine flagged a real
`PARTIAL_SUCCESS` on the "Paper Trading Daily Cycle" run scheduled for
2026-09-14 22:00 UTC (GitHub actually executed it 2026-09-15T00:12:59Z-
00:26:49Z, ~09:12-09:26 KST, run #8). Investigating it from CI logs alone
found:

```
Ingestion status: PARTIAL_SUCCESS
Total bars persisted: 2420 (86 securities, 2026-08-10..2026-09-14)
Missing symbols (zero bars): []
Data quality status: FAILED (400 issues: WARNING 1, ERROR 399, CRITICAL 0)
```

`quality_run.status` was not `CRITICAL_FAILURE` -- ADR-0143's gate was not
what failed this run. The `PARTIAL_SUCCESS` came from the pre-existing,
much older `IngestionRunner.run()` result status check, and
`missing_symbols` (computed only from zero-bar counts) was empty -- so
whichever symbol(s) actually caused `PARTIAL_SUCCESS` had a non-SUCCESS
per-symbol `IngestionResult` (a transient provider error partway through
a symbol's fetch, most plausibly, but not confirmed) while still ending
up with `bars_ingested > 0`. That per-symbol detail (`status`, `error`)
has existed in the manifest's `per_symbol_results` field since Phase 30,
but the manifest itself only ever round-trips as a GitHub Actions
artifact behind Azure Blob Storage (`*.blob.core.windows.net`), a domain
this development environment's own egress proxy has been unable to
reach all session -- so this specific run's real cause could not be
pinned down further from here.

This is the same shape of gap ADR-0143 already fixed for data quality
severity: real information existed in the manifest but was invisible
from CI logs alone.

## Decision

`scripts/ingest_real_market_data.py` now also prints, right after
`Missing symbols (zero bars): ...`:

```
Non-SUCCESS per-symbol ingestion results: [{'security_id': ..., 'status': ..., 'bars_ingested': ..., 'error': ...}, ...]
```

computed from `result.results` (the same `IngestionResult` sequence the
manifest's own `per_symbol_results` field already reads from), filtered
to `status.value != "SUCCESS"`. This is purely additive stdout visibility
-- no behavior, exit code, or manifest field changes. The next time a
`PARTIAL_SUCCESS` like this occurs, the real per-symbol error text is
readable directly from the CI job log, without needing artifact access
at all.

## What this does not do

- It does not retroactively explain run #8's own `PARTIAL_SUCCESS` --
  that run already completed before this print existed, so its own log
  still lacks this detail. The account owner was told this limitation
  plainly rather than a guessed root cause.
- It does not change `import_external_market_data.py` -- that script
  makes no network call, so a per-symbol failure there is a local file/
  schema problem already caught by its own existing, real end-to-end
  test coverage (`tests/data_infra/test_import_external_market_data_cli.py`),
  not the kind of opaque transient-provider issue this ADR addresses.
- It does not add a corresponding print to `scripts/rescan_data_quality.py`
  -- that script has no `IngestionResult`/provider-fetch concept at all,
  it only re-scans bars already in the catalog.

## Tests

`tests/data_infra/test_ingest_real_market_data_wiring.py` (2 new tests,
same AST-only discipline the rest of that file already uses -- this
script is never imported/executed by the suite): the new
`non_success_results` assignment reads from `result.results` and filters
on `SUCCESS`; the new print line is present in source.

Full suite re-run after this change: no regressions (see PROJECT_STATUS.md).

# ADR-0173: Ingest real Kenneth French 3-factor (Mkt-RF/SMB/HML/RF) data as BenchmarkPoint series

**Status:** Accepted
**Date:** 2026-09-19
**Deciders:** Claude Code (session continued), account owner (asked
this session to check what real user-action-required backlog items
remained, then explicitly confirmed proceeding with the Kenneth French
Data Library item after this session found it reachable via GitHub
Actions)

## Context

`docs/PROJECT_STATUS.md`'s 2026-09-17 checklist listed "SEC Financial
Statement Data Sets / Kenneth French Data Library" as an item this
session's own egress could not verify (`mba.tuck.dartmouth.edu` 403s
directly). This session built `recon_kenneth_french_library.yml`
(merged, but never actually triggered by any prior session) and, once
run for real this session, confirmed the opposite of the original
assumption: a GitHub Actions runner's own egress reaches this host
fine (`data_library.html` and `F-F_Research_Data_Factors_CSV.zip` both
returned real HTTP 200). A follow-up recon
(`recon_kenneth_french_csv_format.py`) then downloaded and printed the
REAL CSV layout of both the monthly and daily 3-factor files rather
than assuming a remembered format, confirming: a short text preamble,
a blank line, a `,Mkt-RF,SMB,HML,RF` header, `PERIOD,Mkt-RF,SMB,HML,RF`
data rows (`YYYYMMDD` daily / `YYYYMM` monthly, percent values), a
blank line, then (monthly file only) a second YEARLY-granularity
section, then a copyright footer.

Separately, `strategy_research.factor_scores.idiosyncratic_volatility_score`'s
own docstring already documents a concrete, real gap this data can
fill: that factor's real implementation regresses only against the
market (never SMB/HML, unlike the original paper) specifically because
"this project's universe ... has no independently-constructed SMB/HML
series to regress against" for a trailing ONE MONTH window of DAILY
returns.

## Decision

Added `scripts/ingest_fama_french_factors.py`: fetches the real
Kenneth French 3-factor CSV (daily by default, monthly also
supported), parses ONLY the data section immediately following the
confirmed header line (stopping at the first blank line -- this
naturally excludes the monthly file's annual section without any
special-casing), and stores each of the 4 factors (`mkt_rf`/`smb`/
`hml`/`rf`) as its own `BenchmarkPoint` series via the EXISTING
`benchmark_points` schema/`DuckDBDataRepository.add_benchmark_point`
API -- no new table. Each series is a synthetic
`base_level=100.0`-anchored TOTAL_RETURN cumulative index, compounding
the real daily/monthly percent returns exactly the same way
`backtest.total_return.build_total_return_benchmark_points` already
compounds SPY's own real total-return index (first point IS
`base_level`, every later point multiplies by `(1 + that period's real
return)`). `benchmark_id`s are frequency-scoped
(`FF_DAILY_MKT_RF`/`FF_DAILY_SMB`/`FF_DAILY_HML`/`FF_DAILY_RF`, or the
`FF_MONTHLY_*` equivalents) so ingesting both frequencies into the same
catalog never collides.

New `ingest_fama_french_factors.yml` (`workflow_dispatch`-only, a
`frequency` choice input defaulting to `daily`) runs this for real and
uploads both the resulting catalog and manifest as artifacts, mirroring
the other real single-shot ingestion workflows this session already
established.

## Explicit non-goal (RULE 0.8)

This ADR only makes the real factor-return data available for a future
consumer to read via `DuckDBDataRepository.get_benchmark("FF_DAILY_SMB", ...)`
etc. It does NOT wire `idiosyncratic_volatility_score` (or any other
factor) to actually regress against this data -- whether/how to add a
real SMB/HML control is a separate, deliberate strategy-formula
decision, matching this project's own established two-step discipline
(e.g. SEC 13F institutional-ownership data was ingested and stored,
ADR-0131, before any score was wired to read it, ADR-0134). Wiring a
factor's own regression to a new, real control changes that factor's
real output for every security already scored by it -- exactly the
kind of change RULE 0.8 says must not happen as a side effect of an
unrelated data-infrastructure addition.

## Consequences

### Positive
- A real, previously call-untested backlog item is resolved: the data
  IS reachable, and it is now actually collectible via the same
  GitHub-Actions-as-egress-proxy pattern this session used repeatedly
  elsewhere (SEC EDGAR, Alpaca), not a permanent dead end like
  stockanalysis.com.
- Reuses 100% existing schema/repository/read API -- any future
  consumer (a revised `idiosyncratic_volatility_score`, a factor-return
  attribution report, a regime feature) reads this exactly like it
  already reads SPY's own benchmark series.
- Real, executable test coverage with no network mocking risk beyond
  the single `fetch_zip_bytes` boundary (14 tests against real CSV
  fixtures matching the confirmed real layout, real DuckDB
  persistence, real idempotency check).

### Negative / Trade-offs
- The daily file's real earliest date is 1926-07-01 -- far predating
  this project's own real ingested price history (`START_DATE =
  2024-01-02`) -- so a future consumer only benefits from the small
  recent tail of this series; the full history is stored anyway since
  trimming it here would just be a future consumer's own concern, not
  this ingestion step's.
- No corporate-action-style point-in-time `available_time` staggering
  is needed or applied (unlike `build_total_return_benchmark_points`'s
  real SPY case) -- this is a single, atomically-published academic
  file, not built up from many individually-timestamped filings, so
  every point's `available_time` is simply `--as-of` itself.
- This ADR deliberately leaves the actual factor-formula wiring
  decision open (see non-goal above) -- the data existing does not by
  itself improve any real strategy result yet.

## Tests

`tests/scripts/test_ingest_fama_french_factors.py` (14 tests): period
parsing (`YYYYMMDD`/`YYYYMM`/invalid), CSV parsing against the REAL
confirmed daily and monthly layouts (including that the monthly
parser correctly stops before the annual section), benchmark-point
construction (base level, compounding, unique provenance ids), and
full `main()` end-to-end runs against a real temporary DuckDB catalog
(all four series persisted, idempotent re-run, daily/monthly
`benchmark_id` isolation, fetch/parse failures exit non-zero with a
`FATAL` message rather than failing silently). `tests/deploy/
test_ingest_fama_french_factors_workflow.py` (4 tests): workflow
structure. Full suite re-run: see `docs/PROJECT_STATUS.md`'s session
log for the exact count.

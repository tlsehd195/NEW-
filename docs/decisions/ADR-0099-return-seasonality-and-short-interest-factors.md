# ADR-0099: Return Seasonality and Short Interest Anomaly factors

**Status:** Accepted
**Session:** 36 (continued)

## Context

ADR-0098 implemented the two lowest-cost candidates from the
GitHub/web search for borrowable strategies (Residual Momentum, R&D
Expenditure Anomaly) and flagged two remaining candidates as
lower-priority: **Return Seasonality** (Heston & Sadka 2008, medium
priority, needing a genuinely new computational shape but no new data)
and **Short Interest Anomaly** (Asquith, Pathak & Ritter 2005, lowest
priority, needing a genuinely new DATA SOURCE this project had never
integrated). The user's follow-up instruction ("후보들 진행" -- "proceed
with the candidates") authorized both remaining ones, without carving
out an exception for the data-feasibility concern; this ADR builds both.

## Decision

### Return Seasonality (`return_seasonality_score`)

Groups a security's own price history by CALENDAR MONTH across multiple
non-contiguous prior years (default 5) and averages the historical
same-calendar-month "monthly returns" (month-end close over the
preceding month's end close). A genuinely different computational shape
from every other factor in `factor_scores.py`, which all read one
contiguous trailing window. Needs at least 2 valid historical
same-month observations; `None` below that. Price-only, zero new data
needed.

### Short Interest Anomaly (`short_interest_score`)

**Data source decision, made explicit rather than glossed over**: this
sandboxed session cannot reach `finra.org` (confirmed this session) to
observe FINRA's real Equity Short Interest bulk-file format, so this
project does NOT build a live FINRA scraper with a guessed URL/schema.
Instead, mirroring `data_infra.providers.file_import.LocalFileDataProvider`'s
own established precedent and stated reasoning exactly (Phase 31), this
adds:

- `data_infra.short_interest_models.ShortInterestRecord` -- a new data
  model, with `available_time` ALWAYS derived from `settlement_date`
  plus a conservative 11-calendar-day upper bound on FINRA's own
  published "7 business days" public-dissemination lag (never the
  settlement date itself -- the same look-ahead discipline
  `InsiderTransaction.available_time` already applies).
- `storage.short_interest_repository.DuckDBShortInterestRepository` --
  mirrors `DuckDBInsiderRepository`'s exact shape and point-in-time
  discipline.
- `data_infra.providers.short_interest_file_import` -- a project-owned,
  simple, explicit CSV schema (NOT a claim to reproduce FINRA's own
  real file layout) that a user's own external preprocessing step
  (reshaping whatever FINRA's real file/API actually returns, in an
  environment that CAN reach `finra.org`) is responsible for producing.
- `scripts/ingest_short_interest_data.py` -- a local-file-only CLI
  (never a network call), mirroring `import_external_market_data.py`'s
  shape exactly; safe to exercise directly in the automated test suite
  for that reason.

`short_interest_score` = the NEGATIVE of the most recent available
`days_to_cover` (short interest quantity / average daily volume,
FINRA's own published field) -- chosen over a shares-outstanding-scaled
ratio (Asquith, Pathak & Ritter's own primary construction) specifically
because `days_to_cover` needs only this ONE dedicated repository,
reusing `compute_fundamentals_ic_series`'s `fundamentals_repository`
slot exactly the way `insider_buying_score` already does, rather than a
new two-repository CLI wiring shape.

**Both wired in before any real result exists (RULE 0.8)**:
`residual_momentum`... (already ADR-0098); `return_seasonality` into
`compute_signal_ic_from_catalog.py`'s `_PRICE_ONLY_SCORES` and
`run_long_horizon_validation.py`'s `_PRICE_FACTOR_CANDIDATES`;
`short_interest` into `compute_fundamentals_ic_from_catalog.py`'s new
`_SHORT_INTEREST_SCORES` dict (+ `--short-interest-db-path` flag) and
`run_long_horizon_validation.py`'s new `_SHORT_INTEREST_FACTOR_CANDIDATES`
tuple (+ its own `--short-interest-db-path` flag, gated independently of
every other `--*-db-path` flag, same as `--insider-db-path`).

## What this does NOT do

Does not build a live FINRA network scraper -- see the data-source
decision above; a real ingestion run needs the user's own external
preprocessing step, exactly the same division of responsibility
`import_external_market_data.py` already established for real
market-data acquisition. Does not use Fama-French 3-factor SMB/HML
controls anywhere (unchanged from ADR-0098's own stated limitation).
Does not use a shares-outstanding-scaled short interest ratio -- see
the `days_to_cover` engineering-simplification reasoning above. Does
not continue the broader GitHub/web search for more borrowable
strategies further than the 4 total candidates this search round
produced (Residual Momentum, R&D Expenditure, Return Seasonality, Short
Interest) -- all 4 are now built.

## Tests

`tests/strategy_research/test_factor_scores.py::TestReturnSeasonalityScore`
(3 tests). `tests/data_infra/test_short_interest_models.py` (model
validation + the dissemination-lag helper, 12 tests),
`tests/storage/test_short_interest_repository.py` (persistence/restart/
idempotency/point-in-time/filtering, mirrors
`test_insider_repository.py`, 13 tests),
`tests/data_infra/test_short_interest_file_import.py` (CSV parsing, 9
tests), `tests/strategy_research/test_short_interest_score.py` (7
tests), `tests/data_infra/test_ingest_short_interest_data_cli.py` (a
REAL end-to-end `main()` run against synthetic local CSV fixtures, 3
tests -- safe to execute directly since this CLI makes no network
call, mirroring `test_import_external_market_data_cli.py`'s own
precedent). `test_run_long_horizon_validation_factor_wiring.py`'s
`_EXPECTED_NAMES` extended to 29 names across 6 candidate tables. Full
suite re-run after this ADR: 2589 tests pass (up from 2543 after
ADR-0098).

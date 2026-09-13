# ADR-0129: A Real, Queryable Survivorship Price-Coverage Audit (Wiring ADR-0126/ADR-0128 In, Instead of Chasing More Free Sources)

**Status:** Accepted
**Date:** 2026-09-12
**Deciders:** Claude Code (session continued), pending project owner review
**Related documents:** `docs/decisions/ADR-0126-quandl-wiki-prices-free-delisted-price-source.md`,
`docs/decisions/ADR-0128-fmp-continuously-updated-free-delisted-price-source.md`,
`docs/decisions/ADR-0033-real-historical-us-equity-data-source-decision-tree.md`

---

## Context

`ADR-0126`/`ADR-0128` found and ingested real, free price data for 59
genuinely delisted securities (54 from Quandl WIKI Prices, 1962-2018;
5 from Financial Modeling Prep's free tier, into 2025). `ADR-0127`
documented that free coverage for the remaining ~2018+ population
(195 candidates, only ~5 of which FMP's free-tier whitelist happened
to expose) is genuinely blocked, not merely under-searched.

The user then asked, in effect, "shouldn't we finish this completely
for a good result?" This ADR records the answer given and acted on:
**100% free coverage is not an achievable target** -- every remaining
avenue (Yahoo purges delisted data outright; Stooq and Macrotrends are
behind anti-bot walls that would need ongoing, fragile maintenance to
defeat; FMP's remaining ~184 candidates are blocked by an arbitrary,
undocumented per-symbol whitelist, not a gap this project can close by
searching harder) is a real, structural wall, not a research gap. The
user agreed and redirected effort toward making the 59 tickers already
recovered actually USABLE and the remaining gap HONESTLY MEASURABLE,
rather than continuing to chase diminishing-return free sources.

## Decision 1 -- Build a real price-coverage audit, distinct from the existing membership-metadata audit

`data_infra.universe.audit_survivorship` already exists, but it
answers a different question: whether a `UniverseDefinition`'s
membership records carry provider-confirmed historical dates (a
METADATA quality question). It has no way to answer the question that
actually matters for a specific backtest: **"of the securities that
were real historical constituents and have since been removed, how
many do we actually have real PRICE DATA for, right now, in this
catalog?"** That is a fundamentally different, more concrete
measurement -- a ticker can have perfectly confirmed membership dates
and still have zero real price bars (true of 136 of this project's own
195 post-2018 candidates, per `ADR-0128`).

`data_infra.providers.sp500_index_constituent_history.price_data_
coverage_for_removed_securities` (new) answers it directly: given the
real `fja05680/sp500` interval data (already used by `removed_since`)
and any repository exposing `get_bars`, it reports, for every ticker
removed on/after a given date, whether the repository holds at least
one real bar -- and returns the concrete covered/not-covered ticker
lists, not just a percentage, so a caller can see exactly which real
historical constituents remain a survivorship-bias blind spot for a
given backtest window.

## Decision 2 -- Generic over the repository, not hardcoded to one DuckDB catalog

The function takes any object exposing `get_bars(security_id, start,
end, as_of_time)` -- the exact `storage.data_repository.
DuckDBDataRepository`/`InMemoryDataRepository` protocol this project
already uses everywhere else, rather than being hardcoded to the
specific `wiki_prices_delisted_db` catalog `ADR-0126`/`ADR-0128`
happened to populate. This means the same function can be pointed at
this project's ACTUAL backtest catalog once the recovered tickers are
merged into it, or at any other catalog, without modification.

## Decision 3 -- `scripts/report_survivorship_price_coverage.py` makes no network call, so it IS test-suite-exercised

Unlike `fetch_fmp_delisted_prices.py`/`fetch_sp500_index_history.py`
(both make real HTTP calls and are therefore never imported by the
automated suite), this script only reads a local CSV and queries a
local DuckDB catalog -- the same "real executable test" category
`import_external_market_data.py` already established. Its end-to-end
test populates a real on-disk DuckDB via the existing, UNMODIFIED
`import_external_market_data.py` pipeline (one ticker with real bars,
one without), then runs this new script against it and asserts the
exact covered/not-covered split -- proving the whole chain (S&P 500
interval parsing -> `removed_since` -> real DuckDB `get_bars` query ->
JSON report) works together, not just each piece in isolation.

## Decision 4 -- A ticker with zero bars is reported `not_covered`, never distinguished by reason, at this layer

`price_data_coverage_for_removed_securities` intentionally does NOT
try to explain WHY a ticker has no bars (never fetched at all vs. a
genuinely unavailable source vs. a casing mismatch) -- that
distinction belongs to the specific acquisition attempt (`ADR-0126`'s
"not covered" vs. `ADR-0128`'s "unknown, blocked by paywall" are both
real but different reasons, tracked in THEIR OWN reports). This
function only ever answers the one question its name promises: does
this repository, right now, have real bars for this ticker. Conflating
the two would risk quietly asserting a stronger claim ("confirmed
absent from every possible source") than this project has actually
verified.

## Consequences

### Positive

- This project can now answer, for any date range, exactly how much
  real survivorship-bias exposure remains -- a concrete number and a
  concrete ticker list, not a vague acknowledgment of "known
  limitations" repeated in prose across several ADRs.
- Reusable against any future catalog (a merged production backtest
  DB, a fresh re-run after acquiring more real data from either
  `ADR-0126`'s or `ADR-0128`'s sources, or a future third source) with
  no code changes -- only a different `--db-path`/`--since`.
- Closes the loop this session's whole delisted-price-data thread
  opened: the 59 recovered tickers are no longer just isolated CSVs
  and ADR prose -- there is now a real, tested, reusable way to ask
  "does this actually help a given backtest, and by how much."

### Negative / Trade-offs

- This is an AUDIT tool, not an integration -- it does not, by itself,
  wire the 59 recovered tickers into `RESEARCH_UNIVERSE_STAGE4` or any
  `Strategy`-facing universe, and does not change `run_long_horizon_
  validation.py`'s or any backtest script's own behavior. A caller
  still has to point it at the right catalog and interpret the result;
  it does not retroactively make any past backtest survivorship-bias
  aware.
- `price_data_coverage_for_removed_securities` reports presence/absence
  of ANY bar, not data quality or date-range sufficiency -- a ticker
  with exactly one stale bar would count as "covered" under this
  function alone. This is a deliberate scope boundary, not an
  oversight: `DataQualityFramework` already exists as the place a
  caller should separately check data quality; this function answers
  only "is there anything to even check."
- Still bounded to the S&P 500 removed-ticker population
  (`data/sp500_ticker_start_end.csv`) as the candidate set, identical
  to `ADR-0126`/`ADR-0128`'s own boundary -- a delisted ticker that was
  never an S&P 500 member is invisible to this audit too.

## Tests

11 new tests: 6 in `tests/data_infra/test_sp500_index_constituent_
history.py` (`TestPriceDataCoverageForRemovedSecurities`, using a
minimal fake repository), 5 in `tests/data_infra/test_report_
survivorship_price_coverage_cli.py`, including one true end-to-end
test that builds a real on-disk DuckDB catalog via the existing,
unmodified `import_external_market_data.py` pipeline before running
this new script against it.

## Status of Implementation at Time of This ADR

`data_infra.providers.sp500_index_constituent_history.price_data_
coverage_for_removed_securities` and `PriceDataCoverageReport` (new,
pure, no network) added to the existing module. `scripts/report_
survivorship_price_coverage.py` (new, no network call, test-suite-
exercised). No changes to `data_infra/universe.py`'s existing
`audit_survivorship`, `storage/data_repository.py`, or any backtest
script -- this is purely additive.

**Real result** (account owner's own environment, run against the
actual `wiki_prices_delisted_db` catalog `ADR-0126`/`ADR-0128`
populated, `--since 2000-01-01 --as-of 2026-09-12`): of **623** real
S&P 500 tickers removed from the index on or after 2000-01-01, this
project currently holds verified real price data for **59 (9.5%)**;
**564 remain a real, named, and now precisely measured survivorship-
bias exposure** for any backtest spanning that window. This is this
session's final, honest answer to "how complete is this" -- not 100%,
not vague, but a specific number with a specific ticker list
(`not_covered_tickers` in the report JSON) that can be re-measured
after any future acquisition of more real delisted-price data, from
this project's two free sources or any other.

# ADR-0130: Backfilling Real `SecurityMaster` Records for ADR-0126/ADR-0128's 59 Recovered Delisted Tickers

**Status:** Accepted
**Date:** 2026-09-12
**Deciders:** Claude Code (session continued), pending project owner review
**Related documents:** `docs/decisions/ADR-0126-quandl-wiki-prices-free-delisted-price-source.md`,
`docs/decisions/ADR-0128-fmp-continuously-updated-free-delisted-price-source.md`,
`docs/decisions/ADR-0129-survivorship-price-coverage-audit.md`

---

## Context

The user asked to proceed on the full remaining backlog after
`ADR-0129` closed out the delisted-price-data thread's measurement
side. Of the items named, this ADR addresses the one item that is pure
code and safely actionable in this session: `ADR-0129`'s own disclosed
limitation that its audit tool "does not, by itself, wire the 59
recovered tickers into `RESEARCH_UNIVERSE_STAGE4` or any
`Strategy`-facing universe." (SEC 13F and broader FINRA collection
both require the account owner's own real-world API/account actions,
as `ADR-0125`'s FINRA work did; Live Trading activation is a real-
capital decision requiring explicit confirmation, not something to
proceed on unprompted -- both deferred, not silently dropped.)

Investigating that gap concretely: `scripts/import_external_market_
data.py --symbols` (used to ingest the 59 recovered tickers) only
builds `SecurityMaster` records when run in `--universe` mode
(`build_security_masters`, `data_infra.universe`) -- in `--symbols`
mode, real price bars are persisted, but `repository.get_security(...)`
returns `None` for every one of the 59 tickers. This is a real,
concrete gap: a caller cannot even ask "what is this security's status
as of this date" for a ticker whose real prices are already in the
same catalog.

## Decision 1 -- Derive `valid_from`/`valid_to` from the security's own real bars, never from the S&P 500 membership dates

`data_infra.providers.sp500_index_constituent_history` already has
each of these tickers' real S&P 500 membership `end_date` -- but using
that as `SecurityMaster.valid_to` would conflate two different
concepts: INDEX MEMBERSHIP (was this ticker in the S&P 500) is not the
same claim as EXCHANGE LISTING (was this security actually trading).
A company can leave the S&P 500 for reasons unrelated to its own
listing status (this project's own `ADR-0128` Decision 5 found exactly
this: `AAL`/`ETSY` left the index while remaining fully listed and
traded). Using membership dates as listing dates would silently assert
something this project has not verified, the same category of mistake
`ADR-0125` Decision 3 refused to make for FINRA's `averageShortShareNumber`.

`data_infra.security_master_backfill.build_delisted_security_masters_
from_bars` (new) instead derives `valid_from`/`valid_to` directly from
the security's own REAL PERSISTED price bars in the target repository
(earliest and latest bar timestamp) -- grounded in data this project
has already verified (`ADR-0126`/`ADR-0128`'s own real-corporate-event
cross-checks), not a second dataset's different concept.

## Decision 2 -- `valid_to` is one day past the last real bar, matching the project's exclusive-upper-bound convention

`SecurityMaster.valid_to`/`UniverseMembership.valid_to` are both
documented elsewhere in this project as an EXCLUSIVE `[valid_from,
valid_to)` boundary. Setting `valid_to` to the last bar's OWN
timestamp would make `is_valid_at(that_exact_date)` incorrectly return
`False` for the security's genuine last trading day -- an off-by-one
that would silently exclude the one day this whole effort was built to
recover. `valid_to = max(bar_timestamps) + timedelta(days=1)` avoids
this; also required so `SecurityMaster.__post_init__`'s `valid_to >
valid_from` check never fails for a ticker with only one real bar.

## Decision 3 -- A ticker with zero real bars is silently skipped, never fabricated

`build_delisted_security_masters_from_bars` takes an explicit
`security_ids` list and queries `repository.get_bars` for each --
consistent with `scripts/backfill_delisted_security_masters.py`'s own
CLI. A requested symbol with no real bars in that specific catalog is
skipped (reported, not silently swallowed at the CLI layer), never
given a fabricated record; the whole run is `FATAL` only if literally
every requested symbol has zero bars, matching this project's
established "missing_symbols reported, not fatal unless total"
convention (`ingest_short_interest_data.py`, `import_external_market_
data.py`, `check_wiki_prices_delisted_coverage.py`).

## Decision 4 -- Reuses `build_security_masters`'s exact honest-sentinel convention for `exchange`/`company_id`

Neither `ADR-0126` (Quandl WIKI Prices) nor `ADR-0128` (FMP)'s real
responses carry an `exchange` field. `exchange="UNKNOWN"` (a real
sentinel, never a guessed exchange name) and `company_id=
f"COMPANY-{security_id}"` (a synthetic internal key) are the exact
same conventions `data_infra.universe.build_security_masters` already
uses for its own hand-curated universe -- one honest convention across
this project, not two different ones for two different code paths.

## Consequences

### Positive

- `repository.get_security(ticker, as_of_time)` now returns a real,
  correctly-dated `DELISTED` record for any of the 59 recovered
  tickers, for any catalog this script is pointed at -- closing the
  concrete gap `ADR-0129` disclosed, without touching `RESEARCH_
  UNIVERSE_STAGE4` (a live/current-trading universe this data was
  never meant to join) or any existing universe-building code.
- No network call -- unlike `fetch_fmp_delisted_prices.py`/`fetch_
  sp500_index_history.py`, this script IS exercised by the automated
  test suite, including a true end-to-end test against a real DuckDB
  catalog built via the existing, unmodified `import_external_market_
  data.py` pipeline.

### Negative / Trade-offs

- This still does not make the 59 tickers appear in any
  `Strategy`-facing tradeable universe -- it only makes their identity/
  status metadata queryable alongside their already-persisted bars.
  Actually running a survivorship-bias-aware backtest would need a
  further step: pointing a backtest at the `SP500_INDEX_HISTORICAL`
  universe (which already includes these tickers for their real
  historical membership windows, via `ADR-0120`) against a catalog
  that merges this project's regular current-universe bars with these
  recovered delisted-ticker bars -- not attempted here, left as a
  clearly separate future integration.
- `exchange="UNKNOWN"` for all 59 records is a real, disclosed
  information gap, not a defect -- a caller needing real exchange data
  for these specific tickers would need a separate source.

## Tests

16 new tests: 6 in `tests/data_infra/test_security_master_backfill.py`
(pure, fake-repository-based), 5 in `tests/data_infra/test_backfill_
delisted_security_masters_cli.py`, including one true end-to-end test
that populates a real on-disk DuckDB via the existing `import_
external_market_data.py` pipeline, runs the new backfill script
against it, then independently verifies via `repository.get_security`
that the record is real and correctly `DELISTED`.

## Status of Implementation at Time of This ADR

`data_infra/security_master_backfill.py` (new, pure, no network) and
`scripts/backfill_delisted_security_masters.py` (new, no network call,
test-suite-exercised). No changes to `data_infra/universe.py`'s
existing `build_security_masters`, `storage/data_repository.py`, or
any backtest script.

**Real result** (account owner's own environment, run against the
actual `wiki_prices_delisted_db` catalog): all **59/59** recovered
tickers backfilled successfully, zero skipped. Spot-checked dates
confirm the derivation is correct: `DELL` `valid_to=2013-10-30` (its
real last trade was 2013-10-29, `+1` day per Decision 2), `ATVI`
`valid_to=2023-10-13` (real last trade 2023-10-12, matching Microsoft's
real acquisition close date exactly), `WBA` `valid_to=2025-08-28` (real
last trade 2025-08-27 -- the most recent date any `SecurityMaster` in
this project has ever carried). `repository.get_security(...)` now
returns a real, correctly-dated `DELISTED` record for all 59 tickers in
that catalog.

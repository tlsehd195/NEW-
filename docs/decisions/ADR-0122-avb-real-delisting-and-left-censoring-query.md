# ADR-0122: Real Confirmed AVB Delisting; Left-Censoring Made Queryable

**Status:** Accepted
**Date:** 2026-09-11
**Deciders:** Claude Code (documentation cleanup session, continued), pending project owner review
**Related documents:** `docs/decisions/ADR-0120-sp500-index-constituent-history.md`,
`docs/decisions/ADR-0121-wire-sp500-index-history-into-universe-membership.md`,
`docs/decisions/ADR-0061-sp500-pit-listed-from-wiring.md`,
`docs/decisions/ADR-0033-real-historical-us-equity-data-source-decision-tree.md`

---

## Context

The user asked to review the three items left open after `ADR-0121`:
(1) real historical price data for delisted S&P 500 tickers, (2)
actually using `SP500_INDEX_HISTORICAL` for something beyond raw
queryability, and (3) this project's own documented, unaddressed
left-censoring caveat.

## Decision 1 -- Item 1 (delisted-ticker price data): still `ENVIRONMENT_BLOCKED`, no new alternative found

Re-confirmed this session: `api.tiingo.com`, `stooq.com`,
`data.nasdaq.com`, `api.polygon.io`, `www.alphavantage.co`,
`financialmodelingprep.com` all still return `connect_rejected` through
this sandbox's egress proxy. Searched for a GitHub-hosted (therefore
reachable, per the `fja05680/sp500` precedent) free alternative
covering delisted-security price history; the one candidate found
(`irachex/open-stock-data`) explicitly covers only currently-listed
symbols with 2-3 years of history, unsuitable for both reasons
(no delisted coverage, and this project's 2010-2026 backtest window).
**No code change results from this decision** -- `ADR-0033`/`ADR-0034`'s
conclusion (CRSP/WRDS remains the only `REALISTIC` source, requiring
an institutional subscription this project has no path to acquire
autonomously) stands unchanged.

## Decision 2 -- Item 2 (use the new data for something concrete): found and fixed a REAL, currently-active staleness bug

Rather than force a synthetic "audit" against the new data, cross-checked
`PILOT_UNIVERSE_V1`/`RESEARCH_UNIVERSE_STAGE4`'s actual symbol lists
against the real `fja05680/sp500` intervals already fetched
(ADR-0120/ADR-0121). Found: **`AVB` is the only symbol in either
universe that is not a current S&P 500 constituent per the real data**
(`constituents_as_of` for today's date excludes it; its one real
interval ends `2026-08-18`).

Independently cross-verified via `WebSearch` against real news
coverage, not taken on the dataset's word alone: AvalonBay Communities
and Equity Residential completed a merger of equals on **2026-08-17**,
forming "Vivmark Residential," trading under a new ticker `VMRK` from
**2026-08-18**. Reddit replaced `AVB` in the S&P 500 the same day. `AVB`
as a distinct, independently tradeable security genuinely stopped
existing on this date -- two fully independent real sources (the
dataset and live news) agree.

This means `RESEARCH_UNIVERSE_STAGE4` (via `_real_symbol_metadata`,
`universe.py`) has been reporting `AVB` as `SecurityStatus.ACTIVE`
with no `listed_to` when it should be `DELISTED` with a real removal
date -- a genuinely stale, incorrect record, not a hypothetical one.
Fixed directly:

- Added `_SP500_PIT_CONFIRMED_LISTED_TO = {"AVB": "2026-08-18"}` to
  `universe.py` (the first entry in this project's history for this
  dict -- `ADR-0061` explicitly noted zero removals were confirmable
  from its own dataset at the time).
- `_real_symbol_metadata` now also populates `SymbolMetadata.listed_to`
  from it, independently of `listed_from`/`sector`/`exchange` (same
  independence discipline `ADR-0058`/`ADR-0061` already established
  for the other fields).
- **Zero changes to `build_security_masters`/`build_universe_
  memberships` themselves** -- their existing `DELISTED if listed_to
  is not None else ACTIVE` rule (Phase 29) already does the right
  thing once a real `listed_to` exists; this ADR only supplies the
  first real date that rule has ever actually seen.

Verified: `build_security_masters(RESEARCH_UNIVERSE_STAGE4, ...)` now
reports `AVB` as `SecurityStatus.DELISTED` with `valid_to =
2026-08-18`; every other Stage 4 symbol is unaffected.
`build_universe_memberships`'s `AVB` record correctly reports
`is_member_at(2026-09-01) == False`.

This is deliberately a narrow, surgical fix (one symbol, one real
date) -- not a general survivorship-bias audit tool, since a broader
tool comparing "which real S&P 500 members are absent from an
87-symbol curated universe" would trivially report ~420 "missing"
names without being a meaningful diagnostic (`RESEARCH_UNIVERSE_
STAGE4` was never curated to BE a full index-tracking universe).

## Decision 3 -- Item 3 (left-censoring): made queryable, not just prose

Added `dataset_coverage_start(intervals)` (the real earliest
`start_date` across the parsed dataset) and `left_censored_tickers
(intervals)` (every ticker whose OWN earliest interval starts exactly
at that boundary -- its real join date is unknown and may predate the
dataset) to `sp500_index_constituent_history.py`. This makes the
caveat this module's docstring already stated in prose (item 4)
actually queryable, matching `sp500_pit_membership.
ReconstructedMembershipInterval`'s own explicit `left_censored` field
-- the two modules' honesty disciplines are now symmetric.

Deliberately does NOT add a `left_censored` field directly onto
`TickerMembershipInterval` itself -- that would require computing it
relative to the whole dataset at parse time, entangling a
single-interval's shape with a cross-dataset property; kept as a
separate query function instead, matching `removed_since`'s own
existing style.

## Tests

9 new tests total: 2 in `TestRealSymbolMetadata`/1 updated in
`TestResearchUniverseStage4` (`universe.py`'s AVB fix), 2 new in
`TestConverters` (`build_security_masters`/`build_universe_
memberships` regression against the real Stage 4 data), 8 new
(`TestDatasetCoverageStart`/`TestLeftCensoredTickers`) in
`test_sp500_index_constituent_history.py`, synthetic fixtures only.

## Consequences

### Positive

- The first real, verified `DELISTED` `SecurityMaster` status this
  project has ever produced from its own universe-building pipeline --
  a genuine correctness improvement, not just new query capability.
- Left-censoring's caveat is now enforceable/testable, not only
  documentation a caller might miss.

### Negative / Trade-offs

- Item 1 remains genuinely unsolved -- this ADR does not change the
  project's ability to backtest with real prices for any removed
  ticker, `AVB` included.
- The AVB fix is a single, hand-applied entry, not an automated
  reconciliation process -- a future symbol leaving the index would
  need the same manual cross-verification-and-entry step repeated
  (consistent with `ADR-0058`/`ADR-0061`'s own established, deliberate
  "script computes and reports, a human applies it" division of
  responsibility -- not automated here either).

## Status of Implementation at Time of This ADR

`_SP500_PIT_CONFIRMED_LISTED_TO`/`_real_symbol_metadata` updated in
`src/data_infra/universe.py`. `dataset_coverage_start`/
`left_censored_tickers` added to `src/data_infra/providers/
sp500_index_constituent_history.py`. No new external data fetched this
step (reuses the same `data/sp500_ticker_start_end.csv` from
ADR-0120/ADR-0121).

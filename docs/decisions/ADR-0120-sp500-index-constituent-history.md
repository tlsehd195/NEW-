# ADR-0120: Point-in-Time S&P 500 Index Constituent History from `fja05680/sp500`

**Status:** Accepted
**Date:** 2026-09-11
**Deciders:** Claude Code (documentation cleanup session, continued), pending project owner review
**Related documents:** `docs/decisions/ADR-0033-real-historical-us-equity-data-source-decision-tree.md`,
`docs/decisions/ADR-0034-real-data-acquisition-strategy.md`,
`docs/decisions/ADR-0037-sp500-point-in-time-membership.md`,
`docs/decisions/ADR-0061-sp500-pit-listed-from-wiring.md`

---

## Context

The user asked to revisit a previously-deferred item: `teddykoker/
survivorship-free-spy`, evaluated and rejected in this session's
immediately-prior work (recorded in `docs/PROJECT_STATUS.md`) because
its price source (Quandl WIKI Prices) and constituent source (iShares
historical holdings) are both discontinued, freezing its usable data at
mid-2019. The user then asked to look further ("3번 검토해봐"), which
led to a broader web search for currently-maintained alternatives. That
search found `fja05680/sp500` (https://github.com/fja05680/sp500,
MIT license), which -- unlike the rejected candidate -- is actively
maintained through the present (commit history verified this session
through 2026-09-07) and directly reachable from this sandboxed session:
`raw.githubusercontent.com` returns `200` where every commercial
market-data provider host and `data.sec.gov`/`www.sec.gov` return
`connect_rejected` (re-confirmed this session, same finding
ADR-0037/ADR-0061 already established for GitHub specifically).

This turned out to be closely related to, but a genuine improvement
over, work this project had already done: `ADR-0037` adopted
`hanshof/sp500_constituents` (a different, MIT-licensed, Wikipedia-
scrape dataset) and built `data_infra.providers.sp500_pit_membership`
to reconstruct approximate membership intervals with explicit
uncertainty windows from its raw snapshots. `ADR-0061` used that module
to confirm `listed_from` for 32/87 symbols already in this project's
existing (current-holdings-only) universes, explicitly declining to
set `listed_to` for any of them (none had left the index) and
explicitly stating the remaining, unsolved gap: a symbol that left the
index and is therefore absent from `RESEARCH_UNIVERSE_STAGE4`/
`PILOT_UNIVERSE_V1` entirely is untouched by that work. `ADR-0033`
Decision 1 had already named this precisely: "historical index
constituent universe... **Not modeled by this project at all.**"

`fja05680/sp500`'s `sp500_ticker_start_end.csv` file is a different
shape from `hanshof`'s: instead of raw snapshots requiring
uncertainty-windowed reconstruction, its maintainer has already
computed per-ticker join/leave **intervals** (`ticker,start_date,
end_date`), including tickers that left the index entirely (a real
`end_date`) -- exactly the missing primitive.

## Decision 1 -- Adopt as a second, complementary source; do not replace `sp500_pit_membership`

Built `data_infra.providers.sp500_index_constituent_history` as a new,
separate module (not a modification of `sp500_pit_membership.py`) --
the two sources have different shapes and different honesty caveats,
and this project's precedent (ADR-0037 itself, built as a standalone
parser rather than folded into `universe.py`) is to keep a new external
data source's parsing/query logic in its own scoped module until a
deliberate, separate wiring decision is made.

`parse_ticker_intervals` reads the `ticker,start_date,end_date` schema
into `TickerMembershipInterval` records (never collapsing multiple
intervals for a re-entering ticker, e.g. real `AAL`: 1996-01-02 to
1997-01-15, then 2015-03-23 to 2024-09-23). Three query functions:

- `constituents_as_of(intervals, as_of)` -- every ticker that was an
  index member on a historical date, **including tickers no longer in
  today's index**. This is the capability `sp500_pit_membership.
  membership_as_of` cannot offer (it only answers from the nearest
  snapshot's ticker set, never a continuously-valid interval).
- `history_for_ticker` -- all intervals for one ticker.
- `removed_since(intervals, since)` -- every ticker whose membership
  ended on/after a cutoff date. This is the query that actually
  surfaces the class of survivorship bias `audit_survivorship`
  (`universe.py`) structurally cannot detect on its own, since that
  function only ever audits symbols already present in a
  `UniverseDefinition` -- a removed ticker was never in that list to
  begin with.

## Decision 2 -- Real fetch and computation performed directly in this session

Unlike `hanshof/sp500_constituents` (ADR-0037/ADR-0061, which needed a
full `git clone` for a 6.7MB file), `fja05680/sp500`'s
`sp500_ticker_start_end.csv` is a small (~40KB, 1262 data rows) single
file directly fetchable over HTTPS. `scripts/fetch_sp500_index_history.py`
makes a real network call to
`https://raw.githubusercontent.com/fja05680/sp500/master/sp500_ticker_start_end.csv`,
parses it, and writes a JSON report -- run for real this session
(`--as-of 2026-09-11`, output not committed, `data/` is gitignored,
matching `LocalFileDataProvider`/ADR-0037's external-dataset
discipline):

```
Parsed 1262 ticker-interval rows.
503 tickers were S&P 500 constituents as of 2026-09-11.
142 tickers left the index on/after 2020-01-01.
```

**Cross-verified against `hanshof/sp500_constituents`'s own already-
confirmed fact (ADR-0061)**: that ADR flagged `META`'s confirmed
`listed_from=2022-06-09` as "very plausibly the FB->META ticker
rename" but explicitly declined to assert it without a verified
source ("doing so without a verified source would itself be exactly
the kind of fabrication this project's discipline forbids"). This
session's real fetch from the independent `fja05680/sp500` source
confirms it exactly: `FB` has `end_date=2022-06-09`, `META` has
`start_date=2022-06-09`, in the same file. Two independent
third-party sources now agree on the same date for the same event --
a genuine strengthening of that prior finding, not a new guess.

Because this script makes a real network call, it is -- like
`ingest_insider_transactions.py`/`ingest_fundamentals_data.py` -- never
imported or executed by the automated test suite. Only the pure
`sp500_index_constituent_history` module is unit-tested (20 new tests,
`tests/data_infra/test_sp500_index_constituent_history.py`, synthetic
fixtures mirroring `test_sp500_pit_membership.py`'s own discipline).

## Decision 3 -- Honesty caveats, carried forward and documented in the module itself

1. **Not an official source.** Single-maintainer (`fja05680`),
   cross-references Wikipedia's "Selected Changes" section with
   independent research; the maintainer's own README states that
   source is incomplete ("You can't reconstruct the past with only the
   Wikipedia changes mentioned") and that the earliest years
   (1996-2001) undercount constituents (487 vs. the standard ~500,
   "no way to independently check"). `Provenance.source` for any
   record ever built from this module must read
   `"fja05680_sp500_ticker_start_end"`, never anything implying an
   official S&P Global source.
2. **Left-censoring is real but not flagged.** A ticker present at the
   dataset's very first row (1996-01-02, e.g. `GE`) has `start_date`
   set to that coverage-start date, not its real join date (GE has
   been an S&P 500 member since long before 1996). Unlike
   `sp500_pit_membership.reconstruct_intervals` (which has an explicit
   `left_censored` flag), this module does not add one -- documented
   plainly in the module docstring as the caveat a caller must apply
   by hand for now.
3. **Ticker-keyed, not corporate-identity-keyed** -- identical caveat
   ADR-0061 already established: a ticker rename looks like one ticker
   leaving and a different one joining, not the same company
   continuing.

## Decision 4 -- Wiring into `universe.py`/`UniverseDefinition` is deliberately NOT done here

Same incremental discipline ADR-0037 itself established: this ADR
builds and verifies the parsing/query/fetch primitive against real
data. Actually using `removed_since`/`constituents_as_of` to build a
genuine historical-index-constituent `UniverseDefinition` (which would
require deciding whether `UniverseDefinition.role` gains a new
`"INDEX"` value distinct from the existing `"PILOT"`/`"RESEARCH"` --
ADR-0033 Decision 1's own table treats "historical tradable universe"
and "historical index constituent universe" as two different
questions, so conflating them into the existing role enum without a
deliberate decision would itself be a form of the conflation ADR-0033
warned against) is left as a separate, explicitly future step. No
existing `UniverseDefinition`, `audit_survivorship` call, strategy,
backtest, or Paper Trading code is touched by this ADR.

## Consequences

### Positive

- This project now has, for the first time, a real, working, directly
  fetchable-in-session primitive that answers "which tickers were S&P
  500 index members on this historical date, including tickers no
  longer in today's index" -- the exact gap ADR-0033 named as "not
  modeled at all."
- Independent cross-verification of the FB->META rename date
  strengthens (does not merely repeat) ADR-0061's own prior, more
  cautious finding.
- Zero dependency added (stdlib `csv`/`dataclasses`/`datetime`/
  `urllib.request` only, matching `StooqHttpTransport`'s own pattern
  for a minimal, isolated network call).

### Negative / Trade-offs

- Still not a full delisted-securities-across-all-exchanges dataset --
  index REMOVAL (by committee decision, e.g. falling market cap) and
  actual corporate delisting/bankruptcy/merger remain indistinguishable
  from this data alone, identical to ADR-0037 Decision 3's limitation.
- Left-censoring is undocumented in this module's own output (Decision
  3.2 above) -- a future caller must apply that caveat manually until
  a follow-up adds an explicit flag, mirroring what
  `sp500_pit_membership` already does.
- Wiring this into an actual, strategy-consumable universe is
  deliberately not done here (Decision 4) -- this ADR closes the
  "primitive exists and is real-data-verified" gap, not the "a
  strategy can now be backtested against a true historical S&P 500
  universe" gap.

## Status of Implementation at Time of This ADR

`src/data_infra/providers/sp500_index_constituent_history.py` (new,
pure, no network), `scripts/fetch_sp500_index_history.py` (new, real
network call, run successfully this session against the live source),
`tests/data_infra/test_sp500_index_constituent_history.py` (20 new
tests, synthetic fixtures only). `data/sp500_ticker_start_end.csv` and
`data/sp500_index_membership_report.json` were generated by the real
run this session and are gitignored (`data/*`), not committed,
consistent with `LocalFileDataProvider`/ADR-0037's external-dataset
discipline.

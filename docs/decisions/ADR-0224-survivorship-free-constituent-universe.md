# ADR-0224: Point-in-time S&P 500 universe with delisted names

**Status:** Accepted (coverage measured, backtest plumbing built; price ingestion pending)
**Date:** 2026-09-27
**Deciders:** account owner (asked to fix the known weaknesses), Claude Code session

## Context

Every research run so far uses `RESEARCH_UNIVERSE_STAGE5`, 203 names
that are in today's S&P 500. Names that left the index (acquired,
bankrupt, dropped) never appear, which inflates results, momentum most
of all. ADR-0176 added an opt-in point-in-time universe for one as-of
date, and ADR-0126/0128/0174 tried free sources for delisted prices.
No run has used a survivorship-free universe yet, because the price
data for removed names was never ingested.

Tiingo is the project's working price provider, so the first question
is how many historical members Tiingo carries at all.

## Decision

`scripts/report_tiingo_constituent_coverage.py` plus the dispatch-only
workflow `report_tiingo_constituent_coverage.yml` compare
`fja05680/sp500`'s membership intervals with Tiingo's public
`supported_tickers.zip`. Neither download uses the API key, a request,
or the monthly symbol quota. A ticker counts as listed only when a
Tiingo stock listing with that ticker overlaps the membership interval,
so a reused ticker counts as missing.

## Result (run 36314203228, 2026-09-27)

Window 2000-01-01..2016-07-11 (the unlocked research window, ADR-0222):

| | count |
|---|---|
| Distinct tickers that were members inside the window | 895 |
| Listed by Tiingo | 617 (69%) |
| No longer members today | 566 |
| No longer members and listed by Tiingo | 291 (51%) |

What the 278 unlisted tickers are, from spot checks in the same run:

- **Bankruptcies are missing.** `LEHMQ`, `ENRNQ`, `WAMUQ`, `WCOEQ`,
  `BSC` and similar have no Tiingo listing. These are the names whose
  absence biases results upward the most.
- **Pre-2016 acquisitions are often missing or reused.** `DTV` is
  listed only for 2016-09-30..2019-09-30, a different security from
  DirecTV (2004-2015). `YHOO`/`AABA` are listed with full history.
- **Renamed companies appear under their new ticker only.** `ANTM` is
  missing but `ELV` is listed from 2001-10-30. `BK`, `MMC`, `EQR`,
  `GPS`, `BLL` fall in the same group. A rename map would recover them;
  none is built yet.

Tiingo's paid Power plan ($30/month individual, per tiingo.com/about/pricing
on 2026-09-27) raises the quota (500 to 110,110 unique symbols a month)
but not this coverage, because `supported_tickers.zip` is the same list
for every plan.

## Decision 2: backtest plumbing for a point-in-time universe

- `BacktestConfig.restrict_strategy_to_universe` (needs a dynamic
  `universe`): the strategy receives a `MembershipFilteredDataView` that
  returns no bars for names outside that checkpoint's universe. Every
  ranking strategy already skips names without bars, so a strategy built
  over every name ever in the index ranks only that date's members,
  with no per-strategy change.
- `BacktestIntegrityChecker.check_universe` no longer flags a SELL of a
  held name that has left the universe (an index fund sells its
  removals). A BUY outside the universe is still an ERROR.
- `BacktestConfig.settle_after_missing_checkpoints`: a held name with no
  bar for N checkpoints in a row is settled to cash at its last close
  (`PortfolioAccounting.settle_position`, a WARNING
  `stale_position_settled`). Until then it is marked at its last close,
  not at cost. Nothing after the last bar is used, so no look-ahead.
  The last close is the right value for a cash acquisition. For a
  bankruptcy the real delisting return is usually worse than the last
  close; that is a known optimistic bias of this rule.
- `run_gross_and_net` / `run_walk_forward_evaluation` take
  `point_in_time_universe`; it turns both options on (N=5).
- `run_long_horizon_validation.py --sp500-history-csv` stores the
  fja05680 intervals as `SP500_INDEX_HISTORICAL`, evaluates every member
  in the window that has bars in the catalog, and writes
  `point_in_time_sp500` (per-Jan-1 member coverage, members without
  data) into the report. `run_full_validation.yml` exposes it as the
  `sp500_point_in_time` input. Renamed tickers are mapped to the ticker
  their prices are stored under by
  `docs/research/reference/sp500_ticker_renames.csv` (18 hand-checked
  renames picked from the coverage report's same-day rename candidates;
  the candidate list itself is noisy and is not used directly).
- The ADR-0120 docstring said `SP500_INDEX_HISTORICAL` is never a
  strategy's universe. It now is, through the dynamic-universe path
  above, which is the use that docstring was guarding against doing
  without membership filtering.

Smoke run on the current Stage 5 catalog, 2008-01-01..2009-12-31: 561
names were members in the window, 191 have prices; on 2008-01-01 only
186 of 497 members (37%) have data. All 22 price candidates ran 6
walk-forward folds each with no integrity-excluded fold. This is the
size of the survivorship gap in every result so far, before any new
ingestion.

## Consequences

- Free Tiingo alone can remove about half of the removed-name gap, and
  the half it leaves is biased toward failures. Any result from such a
  universe must report per-date coverage next to it.
- The free quota is 500 unique symbols a month. The ~414 listed names
  not already in the Stage 5 catalog fit in one month, but not in
  September 2026, which already spent symbols on the Stage 5 ingestion.
- Next step, pending the account owner's choice of data source: ingest
  prices for the listed members not yet in the catalog, then run
  `run_full_validation.yml` with `sp500_point_in_time=true`.

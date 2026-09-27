# ADR-0224: Point-in-time S&P 500 universe with delisted names

**Status:** Proposed (step 1 of several: measure coverage)
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

## Consequences

- Free Tiingo alone can remove about half of the removed-name gap, and
  the half it leaves is biased toward failures. Any result from such a
  universe must report per-date coverage next to it.
- The free quota is 500 unique symbols a month. The ~414 listed names
  not already in the Stage 5 catalog fit in one month, but not in
  September 2026, which already spent symbols on the Stage 5 ingestion.
- Next steps, pending the account owner's choice of data source: a
  rename map, delisting settlement in `BacktestEngine` (today a held
  name that stops trading is marked at cost and flagged as an ERROR),
  and a point-in-time membership filter for the strategies.

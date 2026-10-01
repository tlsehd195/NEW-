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

## Decision 3: ingest the missing members with free Tiingo

The account owner chose free Tiingo over the WIKI file and paid
Sharadar (2026-09-27). `extend_research_price_catalog.yml` downloads
the Stage 5 catalog, picks the members of 2000..2016-07-11 that Tiingo
lists (renames applied, names that left the index first, class-share
tickers skipped) and that the catalog lacks
(`scripts/sp500_catalog_extension.py missing`), and ingests them
`--tiingo-only`, 20 symbols an hour (`scripts/ingest_symbol_batches.sh`),
in five chained jobs. It prints per-date member coverage and publishes
to a new release, `research-price-catalog-sp500-pit-2000`, so reports
built on `research-price-catalog-stage5-2000` stay reproducible.

The free plan caps unique symbols at 500 a month and September 2026
already spent part of that on Stage 5. Symbols past the cap fail one by
one; a rerun with `resume_from_run_id` in October fetches only what is
still missing.

## Consequences

- Free Tiingo alone can remove about half of the removed-name gap, and
  the half it leaves is biased toward failures. Any result from such a
  universe must report per-date coverage next to it.
- The free quota is 500 unique symbols a month. The ~414 listed names
  not already in the Stage 5 catalog fit in one month, but not in
  September 2026, which already spent symbols on the Stage 5 ingestion.
- After the extended catalog is published, run `run_full_validation.yml`
  with `price_only=true`, `sp500_point_in_time=true` against
  `research-price-catalog-sp500-pit-2000`.

## Other sources checked (2026-09-27)

These sources were checked before accepting the Tiingo quota delay.

- Twelve Data (free, 800 calls/day) does not return splits (ADR-0203).
  It also returns at most 5,000 bars per series, which would truncate a
  2000-start history.
- Alpha Vantage allows only 25 calls a day.
- FMP's free plan gates `historical-price-eod/full` by an undocumented
  per-symbol whitelist (ADR-0128).
- EODHD's free plan, probed with the owner's key on a GitHub Actions
  runner (8 calls), serves only the past year of end-of-day prices.
  Requests for 2000, 2008 or 2023 return "Data is limited by one year
  as you have free subscription". The plan allows 20 calls a day.
- EODHD's delisted US symbol list (60,303 rows) does include `LEH`,
  `WAMUQ`, `BSC`, `CFC`, `MER` and `SPLK`, but not `ENE`. Splits and
  dividends work on the free plan.
- The paid "EOD Historical Data — All World" plan costs $19.99 a month.
  EODHD's FAQ says delisted tickers are in every paid package, mostly
  from January 2000. That claim is unverified here.
- The owner chose to stay on the free plan. Bankrupt names therefore
  remain missing, and the known upward bias stays documented above.

A second probe (2026-09-27, run 36357090428) covered the owner's existing
Twelve Data and Alpha Vantage keys:

- Twelve Data's free plan refused `LEH`, `BSC`, `CFC`, `MDP` and `XLNX`
  ("available starting with the Grow/Venture plan").
- Twelve Data's `WM` data for 2007 was Waste Management, the ticker's
  current owner, not Washington Mutual. Mixing sources by ticker would
  have added wrong prices silently.
- Twelve Data's free prices are split-adjusted and reach back to 2000.
- Alpha Vantage rejected `LEH`. For `XLNX` it returned only the last
  100 days.

No free source adds removed names beyond Tiingo.

## Throughput fix (2026-09-28)

The owner noticed that each hourly batch left about 10 of Tiingo's 50
requests unused. `--tiingo-only` ingestion fetched corporate actions and
then prices from the same EOD endpoint and range, which cost 2 requests
a symbol. `TiingoDataProvider(reuse_eod_response=True)` now serves the
second call from the first response, so each symbol costs 1 request.
`ingest_real_market_data.py` turns this on for `--tiingo-only`.

`extend_research_price_catalog.yml` batches go from 20 to 36 symbols an
hour: 36 requests of the 50/hour limit, and 864 a day, which leaves room
for `paper_trading_cycle.yml` under Tiingo's 1,000/day. The monthly cap
of 500 unique symbols is unchanged.

## Monthly cap hit (2026-09-28)

Extension run 36316763832 fetched 297 of the 432 missing members, then
X, XEC and XL came back as a JSON object instead of a price array. The
Tiingo account page still showed hourly and daily requests left, but it
does not show the monthly unique-symbol count. A one-shot probe (run
36373252105) asked again: AAPL, already fetched this month, returned
prices, and all three failed names returned HTTP 200 with
`{"detail": "You have run over your 500 symbol look up for this month. ..."}`.
So the stop was the 500-symbols-a-month cap. The run was cancelled with
its part-3 artifact kept, and the remaining symbols resume on 2026-10-01
with `resume_from_run_id=36316763832`. Ingestion errors now include
Tiingo's `detail` text, so this shows in the log directly next time.

## First point-in-time run and a fix (2026-10-01)

The resumed extension (run 36827840347) fetched the last 137 names, and
only MDP and NYX came back empty. Members with prices: 37% → 81% on
2008-01-01 (401/497) and 92% on 2016-01-01 (463/502). The rest are
mostly bankruptcies that Tiingo does not carry.

`run_full_validation.yml` with `sp500_point_in_time=true` over
2000-01-01..2016-07-11 (report `full-validation-20261001T122226Z.json`,
602 names) exposed a plumbing bug. `MembershipFilteredDataView` hid
every non-member, including SPY, so the seven scores that read SPY
(`low_beta`, `idiosyncratic_volatility`, `residual_momentum`,
`idiosyncratic_skewness`, `downside_beta`, `coskewness`, `price_delay`)
returned no score and never traded. The view now always shows the
benchmark. It stays untradable, because strategies only rank the
security_ids they were built over, and SPY is never an S&P member. That
report's numbers for those seven are void. A local 2000..2002-07 run on
the same catalog shows all seven trading.

For the other candidates, the report shows what removing survivorship
does. Median gross excess return over SPY per two-month fold, 203 names
→ point-in-time universe:

| candidate | 203 names | point-in-time |
|---|---|---|
| illiquidity | +2.98% | +1.44% |
| high_volume_return_premium | +2.23% | +2.03% |
| rs_rating | +2.27% | +0.59% |
| risk_controlled_momentum | +2.18% | +0.34% |
| frog_in_the_pan | +2.15% | +0.86% |
| long_term_momentum | +1.77% | +0.13% |
| fifty_two_week_high | +0.97% | +0.98% |
| max_effect | +0.90% | +1.07% |

Most of the edge the 203-name runs showed came from picking today's
survivors. `buy_and_hold`'s net figures (median net excess −3.1%) are
dominated by costs, not data: it buys about 450 names with $10,000, so
the per-order minimum commission is about $357 per fold. Its gross
excess is +0.55%. Re-run the point-in-time validation after this fix
before re-judging any candidate.

# ADR-0211: Longer research history (price factors from 2000) + RESEARCH_UNIVERSE Stage 5 (203 symbols)

**Status:** Accepted (code/config only -- no new data ingested, no backtest run)
**Date:** 2026-09-26
**Deciders:** account owner (chose "둘 다 확대" -- widen both the period and the universe), Claude Code session

**Related documents:** `src/strategy_research/locked_windows.py`
(TEST-1, TEST-2), `ADR-0209` (TEST-2 lock), `ADR-0176`
(`--point-in-time-universe-as-of`), `ADR-0120`/`ADR-0122`
(`fja05680/sp500` interval data), `src/data_infra/universe.py`,
`docs/operations/MARKET-DATA-PROVIDER.md`, `ADR-0164` (provider chain).

## Context

The account owner asked for factor research over a longer history and
more symbols. State before this ADR:

- Universe: `RESEARCH_UNIVERSE_STAGE4`, 87 hand-curated symbols.
- Last real run: 2010-01-01..2023-04-28. Its held-out TEST
  (2020-08-28..2023-04-28) is now locked as TEST-2 (ADR-0209), and
  TEST-1 covers 2023-04-28..2026-08-27. The only not-yet-TEST-observed
  range from 2010 onward is therefore **2010-01-01..2020-08-28, about
  10.7 years**. There is no room to grow forward; growth has to go
  backward in time.
- `run_full_validation.yml`'s `end` default was still `2023-04-28`,
  which overlaps TEST-2, so a default dispatch would be refused by
  `run_long_horizon_validation.py`'s own locked-window guard.

## Decision 1: history window

- **Price-based factors** (momentum, reversal, volatility, beta,
  liquidity, ...): **2000-01-01..2020-08-28** (~20.7 years, adds the
  2000-2002 and 2008 drawdowns). Run without `--fundamentals-db-path`
  (and the other optional catalogs) so only price-derived candidates
  run.
- **Fundamentals factors**: stay at **2010-01-01..2020-08-28**. SEC
  XBRL company facts only become broadly available from 2009-2011
  (general industry knowledge, not re-verified against this project's
  catalog), so earlier folds would hold no fundamentals signal and
  would dilute the walk-forward evidence rather than add to it.
- The 2010-2020 span was TRAIN/VALIDATION (not TEST) in the prior run,
  so it is not locked. Reusing it is allowed under RULE 0.8, but the
  new split's TEST window will sit inside ranges earlier candidates
  have trained on -- report that alongside any result.
- `run_full_validation.yml`'s `end` default becomes `2020-08-28`
  (`earliest_locked_window_start()`); its test now asserts against the
  locked-window registry instead of a literal date. The `start`
  default stays `2010-01-01` because that workflow always loads the
  fundamentals catalog.

## Decision 2: RESEARCH_UNIVERSE Stage 5

One mechanical rule, fixed before any Stage 5 backtest: **current S&P
500 members whose current, uninterrupted interval in
`fja05680/sp500`'s `sp500_ticker_start_end.csv` began on or before
2000-01-03**, minus symbols already in Stage 4. On the 2026-09-26 fetch
that is 117 tickers; `BF.B` is excluded (class-share spelling differs
across providers), leaving **116 new symbols, 203 total**.

- "Current interval" rather than "any interval" drops tickers reused
  by a different company after a gap (`CEG`, `HLT`, `AMP`, ...).
- New entries carry `source="sp500_pit_rule_since_2000"` so they are
  distinguishable from the hand-curated Stage 2-4 entries.
- `listed_from`/`listed_to` are not invented: they still come only from
  the existing confirmed tables in `universe.py`.
- Stage 5 is an **opt-in name** (`--universe RESEARCH_UNIVERSE_STAGE5`
  in `ingest_real_market_data.py` and `run_long_horizon_validation.py`),
  not the `RESEARCH_UNIVERSE` binding, because `paper_trading_cycle.yml`
  ingests `RESEARCH_UNIVERSE` every cycle and 203 symbols would exceed
  its hourly Tiingo budget.

Request budget (confirmed Tiingo free tier: 50/hour, 1,000/day; 2
requests per symbol): the 116 additions are 232 requests (5 hourly
windows); a full 203-symbol ingestion is 406 requests, under one day's
cap. Extending the date range adds no requests.

## Known limitations (must accompany any Stage 5 / 2000-start result)

1. **Survivorship bias gets worse, not better.** "In the index in 2000
   and still in it today" is a 26-year survivor filter. Delisted-price
   recovery only covers removals from 2020 onward, so nothing corrects
   this for the 2000s. `--point-in-time-universe-as-of` (ADR-0176) is
   the membership-correct alternative, limited to symbols with price
   data.
2. **Fallback providers may truncate long history.** Twelve Data's free
   tier caps a time series at 5,000 bars (~20 years) per request
   (from its public docs, not re-verified here), and Alpha Vantage's
   free `compact` output is ~100 bars. A 2000-start backfill should run
   while Tiingo is answering, and each symbol's earliest ingested bar
   must be checked before a run is trusted.
3. **Not yet runnable.** The current Release price catalog starts
   2010-01-01, and real ingestion is currently blocked by a separate
   DuckDB schema-migration issue (tracked in another thread). Order:
   fix ingestion, ingest Stage 5 from 2000-01-01, publish a new Release
   catalog, then dispatch the price-only and fundamentals runs.

## Consequences

- No result exists yet; this ADR changes what can be run, not any
  evidence level.
- A future TEST-3 starting before 2020-08-28 would move
  `earliest_locked_window_start()`; the workflow test will then fail
  until the default is updated, which is intended.

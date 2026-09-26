# ADR-0217: Point-in-time (ALFRED) macro data, and the macro-filter design

**Status:** Accepted (stage 1: data layer + design only; no strategy or backtest reads this data yet)
**Date:** 2026-09-26
**Deciders:** account owner (asked for rates, dollar index, bonds, employment, CPI, PCE, VIX, news and the fear & greed index to inform real investment decisions), Claude Code session

**Related documents:** `docs/decisions/ADR-0208` (the FRED adapter this
extends), `docs/decisions/ADR-0151` ("adopt now, wire in later"),
`src/regime/` (the existing price-only regime detector),
`src/strategy_research/locked_windows.py` (TEST_1/TEST_2 are off limits).

## Context

The account owner wants macro conditions (rates, the dollar, bonds, jobs,
CPI, PCE, VIX, news, fear & greed) to inform real decisions. Two facts
shape how:

1. These inputs describe the market as a whole, not one stock. They
   belong in a **macro filter** that scales total equity exposure (how
   much of the portfolio is in stocks vs. cash), not in stock selection.
2. Most macro numbers are published with a lag and revised afterwards
   (January payrolls: first print early February, revised in March and
   April, then again at the annual benchmark). A backtest that reads
   today's FRED value for a past date uses numbers nobody had at the
   time, the same class of error as the corporate-action `available_time`
   bug found this week. So the data layer must be point-in-time first.

## Decision 1 (implemented): store every ALFRED vintage

- `FredHttpTransport.get_series_vintage_observations` /
  `FredMacroProvider.fetch_series_vintages` request
  `fred/series/observations` over the whole real-time range
  (`realtime_start=1776-07-04`, `realtime_end=9999-12-31`,
  `output_type=1`), paged by `count`/`offset`. Each row is one value as
  published during `[realtime_start, realtime_end]`.
- `data_infra.macro_models.MacroObservationRecord` and a new
  `macro_observation_vintages` table keep **every** vintage (natural key
  `fred:series:observation_date:realtime_start`), so revisions coexist
  instead of overwriting each other.
- `available_time = realtime_start + 1 day, 06:00 UTC`. ALFRED dates carry
  no time of day; this is the first instant no US time zone is still on
  that date. It can be up to ~20 hours later than the real release, never
  earlier.
- `DuckDBMacroRepository.get_series_as_of(series, as_of)` returns, per
  observation date, the latest vintage with `available_time <= as_of`,
  dropping FRED's "." values and observations FRED later withdrew. This
  is the only read a backtest or live decision may use;
  `get_all_vintages` is for audits.
- `scripts/ingest_fred_macro_vintages.py` + `ingest_fred_macro_vintages.yml`
  (`workflow_dispatch`, `FRED_API_KEY` secret) fetch
  `MACRO_SERIES_CATALOG` into a fresh store, upload it as an artifact and
  print a per-series coverage report (first archived vintage, median
  release lag, share of revised observations).

**Not yet verified against real data.** This development sandbox cannot
reach `api.stlouisfed.org` (proxy `connect_rejected`, checked
2026-09-26). The vintage request/response shape follows FRED's own API
documentation (`fred/series/observations`: `realtime_start`,
`realtime_end`, `output_type`, `offset`, `limit` up to 100000, and
`realtime_start`/`realtime_end` on every observation) and is covered by
stubbed tests only. The first real run of the workflow is what confirms
it.

### Series (`MACRO_SERIES_CATALOG`)

| Asked for | FRED series |
|---|---|
| Rates | DFF, DGS3MO, DGS2, DGS10, T10Y2Y, T10Y3M |
| Bonds / credit | BAA10Y |
| Dollar index | DTWEXBGS |
| Employment | PAYEMS, UNRATE, ICSA |
| CPI | CPIAUCSL, CPILFESL |
| PCE | PCEPI, PCEPILFE |
| VIX | VIXCLS |
| Financial conditions | NFCI |
| Bitcoin | CBBTCUSD (Coinbase, from 2014-12-01) |

Left out on purpose:
- **ICE DXY** is not on FRED. DTWEXBGS (Fed broad dollar index, from
  2006) is the FRED stand-in; a DXY-like traded proxy (UUP) would come
  through the existing price catalog instead.
- **ICE BofA high-yield OAS (BAMLH0A0HYM2)**: the FRED series page
  (read 2026-09-26) says that since April 2026 it only includes 3 years
  of observations (ICE licensing). Too short to backtest; BAA10Y (from
  1986) is the long-history credit-spread stand-in.
- **Gold price**: FRED removed the LBMA gold series in January 2022
  (ICE Benchmark Administration licensing; `GOLDAMGBD228NLBM` now
  redirects to FRED's removal notice). Gold comes in as the GLD ETF
  (listed 2004-11-18) through the existing price catalog, which is
  already point-in-time (a close is known at the close). No gold history
  before 2004-11 from any source this project has.

### Open question the first real run answers

For daily market series (VIX, Treasury yields) ALFRED may only have
archived vintages from some later year; every older observation then
carries that first vintage date and is invisible to a backtest before
it. That is safe but could leave too little history. If the coverage
report shows it, stage 2 decides whether series flagged `revised=False`
(market prices that are not revised) may instead use
`observation_date + a fixed, conservative publication lag`. That rule is
**not** implemented now: it is a point-in-time judgement that should be
made on the real coverage numbers, not in advance.

## Decision 2 (design only): the macro filter

A portfolio-level exposure multiplier `m ∈ [m_min, 1]` applied to any
strategy's target weights (the rest held as cash), computed only from
`get_series_as_of(..., as_of=decision time)`. It does not choose stocks
and does not change the backtest engine; it will sit between a
strategy's target weights and order generation, in a new module, in
stage 2.

Candidate risk-off signals, each a fixed rule from published practice,
not a fitted threshold:

| Signal | Rule (risk-off when) | Series |
|---|---|---|
| Volatility | VIX above its trailing 1-year 80th percentile | VIXCLS |
| Yield curve | 10y − 3m spread below 0 | T10Y3M |
| Credit stress | Baa − 10y spread up more than 1 point over 3 months | BAA10Y |
| Labor (real-time Sahm rule) | 3-month average unemployment ≥ 0.5 pt above its 12-month low, using vintages | UNRATE |
| Rate shock | 2-year yield up more than 1 point over 3 months | DGS2 |
| Dollar squeeze | Broad dollar up more than 5% over 3 months | DTWEXBGS |
| Financial conditions | NFCI above 0 | NFCI |

Combination: count of active flags maps to exposure (0–1 flags → 100%,
2 → 75%, 3+ → 50%). The mapping and every threshold are pre-registered
in a config before the first backtest; any change afterwards counts as
a new trial for the DSR/PBO penalty.

### Validation plan

- Research window only: data before 2020-08-28 (TEST_1/TEST_2 in
  `locked_windows.py` stay untouched). The price catalog starts in 2000.
- Compare SPY vs. SPY + filter, and the best existing candidate vs. the
  same candidate + filter, walk-forward, reporting Sharpe, MDD, turnover
  and time spent de-risked.
- Expected limitation, stated up front: 2000–2020 holds about three
  equity-bear episodes (2001–02, 2008–09, 2020). A macro filter is
  judged on how few regime switches it gets right, so the result will
  very likely be **INCONCLUSIVE** on this sample however good it looks.
  A real `VALIDATED` claim would need either a longer history (pre-2000
  prices) or out-of-sample paper trading.

### Gold and bitcoin as filter inputs (added at the account owner's request)

- **Gold (GLD)**: usable across 2004-11 to 2020-08, about 16 years of
  the research window. A plausible risk-off input is "gold outperforming
  SPY over 3 months" (a flight-to-safety sign), added to the table above
  only if pre-registered before the first backtest.
- **Bitcoin (CBBTCUSD)**: stored, but not a filter input for now. The
  research window only covers 2014-12 to 2020-08 (under six years, one
  equity bear episode, the 2020 crash), and bitcoin's co-movement with
  stocks changed a lot after 2020, so a rule fitted on that stretch
  would say little about later years. It is kept for paper-trading
  observation and a later re-evaluation.

## Decision 3 (research only): news and the fear & greed index

**CNN Fear & Greed**: no official API. Community copies (e.g.
`github.com/whit3rabbit/fear-greed-data`, MIT) reach back to 2011, but
their own README says values before 2021-02-01 are not accurate
(reconstructed from other archives), and data from 2021 on is re-pulled
from CNN's live endpoint on every run, so CNN's own past numbers can
change. Neither is point-in-time. Recommendation: do not backtest CNN's
number. The index is built from public ingredients (VIX, S&P 500 vs. its
125-day average, stock vs. bond returns, junk-bond demand, breadth,
put/call); a self-built composite from point-in-time pieces we already
have or can get (VIXCLS, SPY/bond-ETF prices from the price catalog,
BAA10Y) is backtestable. CNN's live value could still be recorded going
forward for paper trading only.

**News**: timestamped historical archives exist (GDELT from 2015;
Benzinga news via Alpaca's market-data API, reportedly from 2015). Not
verified in this session, from general knowledge only. Timestamps make
point-in-time use possible, but (a) 2015–2020-08-28 is under six years of
research window, (b) turning headlines into a signal needs an NLP/LLM
step, which is exactly the AI-call wiring CLAUDE.md defers until a real
AI predictor exists. Recommendation: last, after the FRED filter has a
result.

## Consequences

- The project now has a point-in-time macro store and a way to fill it;
  nothing reads it yet, so no existing backtest, paper-trading or
  validation number changes.
- `risk_free_rate=0.0` (ADR-0208) is still unchanged; DGS3MO vintages
  make a later, deliberate change possible.
- Next steps: run `ingest_fred_macro_vintages.yml`, record the real
  coverage report here, then stage 2 (filter module + validation) as a
  separate PR.

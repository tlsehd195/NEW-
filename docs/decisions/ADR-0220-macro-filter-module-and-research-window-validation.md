# ADR-0220: Macro filter module and its research-window validation (pre-registration)

**Status:** Accepted (design and pre-registration; results are added
under "Results" after the first real run, and nothing above it changes)
**Date:** 2026-09-27
**Deciders:** account owner, Claude Code session

**Related documents:** `docs/decisions/ADR-0217` (point-in-time macro data,
filter design)

## Context

ADR-0217 stored 18 FRED/ALFRED series point-in-time and sketched a
portfolio-level macro filter. The account owner asked to go ahead with
stage 2: build the filter and test it on the research window.

## Decision

### Module (`src/macro_filter/`)

- `config.py`: `MacroFilterConfig` (`macro_filter_config_v1`) freezes every
  threshold, window, staleness limit, fallback lag and the exposure
  mapping. `configuration_version()` is a content hash; any change is a
  new trial.
- `series.py`: `PointInTimeMacroSeries` answers as-of reads in memory with
  the repository's rules (latest vintage known at `as_of`, "." and
  withdrawn values skipped), plus the ADR-0217 fallback below.
- `signals.py`: `MacroSignalEngine` computes the ten signals per
  checkpoint (cached); `ExposureRule` maps flags to exposure.
- `strategy.py`: `MacroExposureStrategy` holds SPY at the rule's exposure,
  the rest in cash, through the unmodified `BacktestEngine`. It trades when
  the target changes or the invested share drifts more than 2.5 points
  from target (the same band for every rule, the baseline included, so
  dividends paid as cash are reinvested alike).

`strategy_research.pbo_dsr.compute_dsr_for_all_candidates` gains
`zero_sharpe_trials`: rules that never differed from the baseline still
count as trials with Sharpe 0, so the winners are not under-deflated.

### Pre-archive fallback (the open question ADR-0217 left for stage 2)

For never-revised series only (`revised=False`), an observation older
than the series' first archived vintage counts as known
`observation_date + lag` (then the usual next-day 06:00 UTC stamp). The
lag is the series' maximum release lag seen in the vintage era, at least
1 day: DFF 9, DGS3MO/DGS2/DGS10 11, T10Y2Y/T10Y3M 6, BAA10Y 1, VIXCLS 1.
Revised series (UNRATE, ICSA, NFCI, DTWEXBGS) get no fallback, so claims
start in 2009-05, NFCI in 2011-06 and the broad dollar in 2019-02; before
that those signals are unavailable and never count as risk-off.

### Signals (exact definitions)

| Signal | Risk-off when |
|---|---|
| `vix_high` | latest VIX above the nearest-rank 80th percentile of the trailing 365 days (at least 200 values) |
| `curve_10y3m_inverted` | latest T10Y3M < 0 |
| `credit_widening` | BAA10Y up more than 1.0 point vs. the value 91 days earlier |
| `sahm_rule` | 3-month average UNRATE at least 0.5 pt above its minimum over the previous 12 months (15 consecutive months of first-known vintages) |
| `rate_shock` | DGS2 up more than 1.0 point over 91 days |
| `dollar_squeeze` | DTWEXBGS up more than 5% over 91 days |
| `nfci_positive` | latest NFCI first print > 0 |
| `claims_rise` | 4-week average ICSA more than 20% above the lowest 4-week average of the trailing 52 weeks |
| `curve_10y2y_inverted` | latest T10Y2Y < 0 |
| `gold_flight` | GLD out-returned SPY over the last 63 trading days (adjusted-close ratios) |

A value is stale, and the signal unavailable, after 14 days (daily), 30
days (weekly) or 100 days (monthly).

### Trials (12, fixed now)

- `no_filter`: always 100% (the baseline).
- `combined`: the nine ADR-0217 table signals; 0–1 active → 100%,
  2 → 75%, 3+ → 50%. Gold is not in the count, so the frozen table stays
  as written.
- `only_<signal>` for all ten signals: 50% while that signal is active,
  else 100%.

Trial count for deflation: 11 (every rule except the baseline).

### Validation run (`scripts/run_macro_filter_validation.py`,
`run_macro_filter_validation.yml`)

- Data: `research-price-catalog-stage5-2000` (SPY), GLD from Tiingo, and
  the merged ALFRED store (`fred-macro-vintages-v1`, built by
  `publish_fred_macro_store.yml` from runs 36266048908 and 36305920713).
- Window: 2000-01-01 to 2020-08-27. The script refuses any overlap with
  TEST_1/TEST_2.
- Continuous net-of-cost run per rule: CAGR, Sharpe, max drawdown,
  turnover, share of days de-risked.
- Walk-forward: 6-month test folds, 6-month step (12-month warm-up), fresh
  capital per fold, which gives 39 folds (the last one 2020-01 to 2020-07) and includes the 2001–02,
  2008–09 and 2020 drawdowns. PBO (8 groups) over all 12 rules; DSR over
  each rule's per-fold return minus the baseline's.

### Pass rule (fixed before the first run)

A rule is a research-window **CANDIDATE** only if all three hold:
1. DSR of its per-fold excess return over `no_filter` ≥ 0.95, with 11
   trials;
2. continuous-run Sharpe above `no_filter`'s;
3. continuous-run max drawdown shallower than `no_filter`'s.

Everything else is **INCONCLUSIVE**. Nothing in this run can be
VALIDATED: a CANDIDATE would still need out-of-sample paper trading (the
TEST windows are locked), and a CANDIDATE `only_*` rule while `combined`
fails is reported as a single-signal result, not as support for the
combined filter.

## Known biases, stated before the run

- Cash earns 0% (`risk_free_rate=0.0`, ADR-0208). This understates every
  rule that holds cash, most in 2000–2008 when T-bills paid 1–6%.
- About three bear episodes in 20 years: a filter is judged on very few
  regime switches, so INCONCLUSIVE is the expected outcome.
- The fallback lags make pre-2005 yields and pre-2010 VIX usable but are a
  modelling choice, not archived vintages.

## Results

Not run yet.

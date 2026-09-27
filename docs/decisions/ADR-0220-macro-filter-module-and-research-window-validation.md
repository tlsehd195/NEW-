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
`observation_date + lag` (then the usual next-day 06:00 UTC stamp). DFF,
DGS3MO/DGS2/DGS10 and T10Y2Y/T10Y3M use the maximum release lag seen in
the vintage era: 9, 11 and 6 days. BAA10Y and VIXCLS use 1 day. Their
measured maxima in the merged store's coverage report (run 36309849364)
are 166 and 9,053 days, but those come from a few old observations first
added to the archive years late, not from the daily release: the median
lag is 1 and 0 days. So for these two, 1 day is a judgement about the
daily publication schedule, not the worst case in the archive. Old
observations that ALFRED added late keep their late `realtime_start`,
because the fallback only touches rows stamped with the first vintage.
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

## Results (run 36310412611, 2026-09-27)

Report: `docs/research/reports/macro-filter-validation-20260927T094725Z.json`
(config `macro_filter_config_v1`, 5,197 daily checkpoints 2000-01-03 to
2020-08-27, 39 of 39 walk-forward folds valid). The unfiltered baseline
reproduces the SPY total-return benchmark (+252.0% vs. +251.3%).

**Every rule is INCONCLUSIVE.** No rule reached the DSR bar; the highest
is 0.25. PBO over the 12 rules is 28.6%.

| Rule | CAGR | Sharpe | Max DD | Days de-risked | DSR (excess) |
|---|---|---|---|---|---|
| no_filter | 6.28% | 0.41 | -53.9% | 0% | — |
| combined | 5.95% | 0.43 | -47.9% | 16% | 0.02 |
| only_sahm_rule | 7.09% | 0.51 | -36.8% | 18% | 0.22 |
| only_rate_shock | 6.52% | 0.42 | -52.4% | 0.6% | 0.25 |
| only_credit_widening | 6.31% | 0.43 | -49.8% | 2% | 0.10 |
| only_vix_high | 5.63% | 0.44 | -47.3% | 20% | 0.02 |
| only_gold_flight | 4.99% | 0.40 | -46.5% | 34% | 0.00 |
| only_curve_10y3m_inverted | 6.01% | 0.41 | -54.1% | 10% | 0.00 |
| only_curve_10y2y_inverted | 5.74% | 0.39 | -53.9% | 9% | 0.00 |
| only_claims_rise | 5.29% | 0.37 | -53.9% | 4% | 0.00 |
| only_nfci_positive | 5.94% | 0.40 | -53.9% | 0.2% | 0.00 |
| only_dollar_squeeze | 5.78% | 0.39 | -53.9% | 0.8% | 0.00 |

What the numbers say, and what they do not:
- The combined filter cut the worst drawdown by 6 points and nudged
  Sharpe up, but gave up 0.3 point of CAGR and beat the baseline in only
  7 of 39 folds. It does not add return.
- The Sahm rule alone looks best: higher CAGR, Sharpe 0.51, max drawdown
  -37% instead of -54%. But it changed exposure only 5 times in 20 years,
  around the 2001, 2008 and 2020 recessions, so the whole edge rests on
  two or three events.
  That is why its DSR is 0.22, not 0.95. It is the one lead worth
  watching in paper trading. The research window cannot confirm it.
- VIX and gold reduce drawdowns but cost return (sold after the fall,
  bought back late).
- Curve inversions, claims, NFCI and the dollar did nothing useful here.
  NFCI, claims and the dollar were also unavailable for most of the
  window (point-in-time data only from 2011, 2009 and 2019).
- Known bias against every de-risking rule: cash earned 0%.

Consequence: no macro rule is wired into paper trading or any strategy
by this ADR. Changing a threshold now and re-running would be a new
trial and must be pre-registered as `macro_filter_config_v2`.

## Follow-up: observe-only Sahm log (2026-09-27, account owner's choice)

The account owner chose to watch the Sahm rule going forward rather than
change it. `observe_sahm_rule.yml` (weekdays 14:00 UTC) runs
`scripts/record_sahm_observation.py`, which reads FRED's current UNRATE
(what is known that day, so point-in-time by construction), computes the
rule with the same `sahm_rule_reading` the backtest used, and appends to
`docs/research/macro_observations/sahm_rule.jsonl` only on a new release
or revision. A flip of the rule's state is posted to Discord. Nothing
trades on it; paper trading is unchanged.

The first observation run (36313455609) found FRED has no UNRATE value
for 2025-10 (the BLS skipped that month during the government shutdown),
and the rule, which required 15 consecutive months, returned no reading.
`sahm_rule_reading` now averages over calendar months, leaving a missing
month out of its 3-month windows and requiring at least 2 of 3 months per
window. With no gap it is the same computation, and UNRATE has no gaps in
2000–2020, so the results above are unchanged.

---
type: entity
title: macro-filter
tags:
  - module
  - macro
  - point-in-time
created: '2026-09-27T09:30:12.036Z'
---
`src/macro_filter/` (ADR-0220) scales how much of the book is invested in equities. It is a portfolio-level exposure multiplier computed from point-in-time macro series, and it never picks stocks. It is built on the ALFRED store described in [[data-infra]] and [[point-in-time]].

- `config.py`: `MacroFilterConfig` freezes every threshold, window, staleness limit, pre-archive fallback lag and the exposure mapping. Its content-hash version changes on any edit, and an edit after results are seen counts as a new trial.
- `series.py`: `PointInTimeMacroSeries` answers in-memory as-of reads, taking the latest vintage known at the as-of time. A series that is never revised gets one extra rule: an observation older than the first archived vintage becomes known at `observation_date + max observed lag`.
- `signals.py`: `MacroSignalEngine` computes ten risk-off flags per checkpoint and caches them: VIX percentile, the 10y−3m and 10y−2y curves, a Baa credit-spread jump, the real-time Sahm rule, a 2y rate shock, a broad-dollar squeeze, NFCI > 0, a jobless-claims rise, and gold beating SPY. A flag with missing or stale inputs is `None` and never counts as risk-off. `ExposureRule` maps flags to an exposure level: the baseline, the combined count mapping (0–1 → 100%, 2 → 75%, 3+ → 50%), or a single signal (50% while active).
- `strategy.py`: `MacroExposureStrategy` holds SPY at that exposure through the unmodified [[backtest]] engine. It trades on exposure changes and on 2.5-point drift.

Validation happens only in the research window, through `scripts/run_macro_filter_validation.py` and `run_macro_filter_validation.yml`. It reports continuous runs, 6-month walk-forward folds, PBO, and DSR of each rule's excess over the baseline (see [[strategy-research]]). The best possible grade is CANDIDATE. The locked TEST windows are never used. Cash earns 0%.

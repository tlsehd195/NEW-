# ADR-0238: Report an effective independent-trial count alongside the DSR trial count

**Status:** Accepted
**Date:** 2026-10-08
**Deciders:** account owner (delegated the choice of which recommendations to adopt), Claude Code session

## Context

An open-source review (Qlib, VectorBT, MlFinLab, Lean, yfinance; report `reports/open-source-deep-analysis-2026-10-08.md`) found one gap that matters for every verdict: `compute_dsr_for_all_candidates` sets `num_trials = len(candidates) + zero_sharpe_trials`. Highly correlated candidates (many price factors are) are counted as independent trials, so the deflation term can be mis-sized in either direction. MlFinLab's public repo is stubs under a proprietary licence, so nothing was copied; the idea (cluster/decorrelate the trial set) is re-derived here.

## Decision

1. `effective_trial_count(fold_returns_by_candidate)` returns N_eff = N² / Σᵢⱼ ρᵢⱼ², the participation ratio of the fold-return correlation matrix (identical series give 1, uncorrelated give N). Pure arithmetic, deterministic, no new dependency, fixed before looking at results.
2. `compute_dsr_for_all_candidates(..., effective_trials=None)` accepts an optional N_eff used only in the expected-max-Sharpe term, floored at 0 deflation. Default path and `num_trials` are unchanged; `DsrResult.effective_num_trials` records what was used.
3. `scripts/compute_pbo_dsr_from_report.py` prints and stores N_eff as a supplementary field. It does not change any verdict or evidence level.

## Consequences

- No existing verdict changes. N_eff is information for a human reading a report; adopting it as the gating trial count would be a separate ADR.
- Not done: cumulative-ledger N_eff across past reports (`trial_ledger.py`), because prior reports' fold returns are not all aligned.
- Other review recommendations (cross-sectional normalisation, turnover control, portfolio allocator) were deferred until a candidate signal exists, since tooling does not fix the absence of an out-of-sample signal.

## Tests

`tests/strategy_research/test_pbo_dsr.py::TestEffectiveTrialCount`.

# ADR-0234: White Reality Check and Hansen SPA as supplementary diagnostics

**Status:** Accepted
**Date:** 2026-10-02
**Deciders:** account owner, Claude Code session

## Context

A prior thread ("테스트 구간 고갈 관련 논문 조사") surveyed the held-out
TEST-window exhaustion problem and recommended two classic data-snooping
tests already used in the backtest-overfitting literature this project
already cites (`pbo_dsr.py` -- Bailey/Lopez de Prado): White's (2000)
Reality Check and Hansen's (2005) Superior Predictive Ability (SPA)
test. CPCV was considered and explicitly skipped in that thread because
the project's candidates are rule-based factors, not models with
per-observation feature importances CPCV was designed to probe.

Both tests ask a question this project has so far only asked
informally via `verdict_against_buy_and_hold`
(`scripts/run_long_horizon_validation.py`, ADR-0228): does a
candidate's apparent edge over the same-names buy-and-hold baseline
survive, once the fact that *several* candidates were compared is
accounted for? `pbo_dsr.py`'s existing PBO/DSR already partially answers
a related question (does the in-sample winner's rank persist OOS; what
is its Sharpe once deflated for the trial pool size) but neither
directly bootstraps "best candidate's excess mean over the benchmark"
under the null that no candidate truly beats it, which is what White
and Hansen's tests do.

## Decision

Add `src/strategy_research/reality_check_spa.py`:
`white_reality_check` and `hansen_spa`, both built on a stationary
bootstrap (Politis & Romano 1994) over each candidate's per-fold NET
excess return vs. the `buy_and_hold` benchmark's per-fold NET return
(the same fold-level granularity `pbo_dsr.py` already uses, for the
same reason -- each fold is an independent out-of-sample window, not a
finer period needing purging/embargo).

Wire this into `scripts/compute_pbo_dsr_from_report.py`: whenever a
report's prequalified candidates include `buy_and_hold`, compute both
tests' p-values over every other prequalified candidate's excess return
vs. it, and record the result as a new top-level
`reality_check_spa_result` field. This is **supplementary only**:

- It never changes any existing `evidence_assessment`, PASS/FAIL
  verdict, or the `pbo_dsr_result` field already written by this
  script.
- It is silently skipped when no `buy_and_hold` is among the
  prequalified candidates (too few valid folds), or when fewer than 2
  non-benchmark candidates remain to compare -- both tests require at
  least 2 candidates to make "best of several" a meaningful question.

## Consequences

- Every future `compute_pbo_dsr_from_report.py` run against a report
  that includes `buy_and_hold` (which `run_long_horizon_validation.py`
  always includes as a reference baseline) now also reports Reality
  Check and SPA p-values for free, as additional evidence a human
  reviewing a candidate can weigh alongside PBO/DSR -- without
  re-running any backtest.
- Low p-values from these new fields are NOT by themselves grounds to
  promote a candidate past its existing evidence level; they are one
  more data-snooping check, not a new gate. `docs/research/
  walk-forward-pbo-deflated-sharpe.md`-style adoption discipline
  (adopt as a diagnostic now, decide separately and explicitly if/when
  it should ever gate a verdict) applies here too.
- No held-out TEST window is touched or newly used by this change --
  it recomputes from folds already persisted in an existing report.

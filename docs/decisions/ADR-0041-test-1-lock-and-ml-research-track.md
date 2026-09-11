# ADR-0041: TEST-1 permanent lock + ML Research Track governance

**Status:** Accepted

## Context

Phase 32 ("40종목 결과 심층분석 + ML RESEARCH TRACK 설계"), executed
per explicit user instruction after consulting external advice on
next-direction (rule-based strategy expansion vs. ML track). Two
things needed a durable, code-level (not just documentation-level)
answer:

1. The 2023-04-28..2026-08-27 held-out TEST window has now been
   observed by all 4 rule-based strategies (`STRATEGY-VALIDATION-
   REPORT.md`'s "40-Symbol Re-Validation" section), and two of those
   4 strategies' signal-window computation was subsequently corrected
   (ADR-0038) *after* that observation. Nothing in the codebase
   previously prevented that same window from being reused, by
   accident or convenience, as training/validation/test data for a
   future strategy or ML model.
2. Whether to pursue further rule-based strategies or begin an ML
   research track needed a governance answer before any ML code is
   written, not decided implicitly by whichever gets started first.

## Decision 1 -- `TEST-1` is a permanent, code-level lock

Added `src/strategy_research/locked_windows.py`:
`TEST_1 = LockedWindow(start=2023-04-28T14:24Z, end=2026-08-27T00:00Z,
observed_by=(4 strategy names), ...)` and
`overlaps_any_locked_window(start, end) -> tuple[LockedWindow, ...]`.
Recorded verbatim from the actual report's `chronological_split`
values (not re-derived from `build_chronological_split`'s current
defaults, so this constant cannot silently drift if those defaults
ever change).

This is a lookup/guard utility a future script is expected to call
explicitly, the same opt-in-library-call pattern this project's other
point-in-time guards already use (`AsOfDataView`, `available_time <=
as_of_time`) -- not a runtime that makes reuse structurally
impossible. Binding on ANY future data split, rule-based or ML, per
`locked_windows.py`'s own docstring reasoning: reusing an
already-observed TEST window for a *different* model is still
evaluating against an already-seen answer key.

9 new regression tests (`tests/strategy_research/
test_locked_windows.py`) verify the constant's recorded values and the
overlap-detection logic (identical range, partial overlap at either
edge, fully-contained range, non-overlapping ranges before/after, and
exact-boundary touching).

## Decision 2 -- ML Research Track: design/governance now, no implementation yet

Added `docs/research/ML-RESEARCH-PROTOCOL.md`: audits existing
ML-adjacent infrastructure (`src/predict/`, `src/learning/`,
`src/evolution/`, `src/regime/features.py` -- see that document's
section 1 for what each actually does and, more importantly, does
NOT do), defines the ML Track's goal precisely ("does historical
market data contain out-of-sample predictive signal" -- not "maximize
backtest return"), and specifies leakage prevention, TRAIN/VALIDATION/
TEST structure (reusing `build_chronological_split`, never inventing a
second splitting mechanism), experiment governance/hyperparameter
budget tracking, model-selection-as-multiple-testing (feeding future
ML fold returns into the *existing* `compute_pbo`/
`compute_dsr_for_all_candidates` functions rather than inventing a new
statistic), feature/target/model registry schemas, reproducibility
requirements, risk-control requirements, and dependency policy.

**Explicitly not done in this Phase**: no ML model trained, no
feature/target/model registry implemented, no ML dependency added
(`numpy`/`scipy`/`scikit-learn`/etc. -- per ADR-0039's already-
established reasoning, applied here identically: a dependency decision
waits for a specific, justified model family being actually
implemented). This mirrors the governing instructions' own emphasis
(sections 34, 42): design and requirements definition first, minimal
code footprint, no premature implementation.

## Decision 3 -- Track A: rule-based-strategy deep-dive tooling, built; full analysis, partially blocked by data location

Added `src/strategy_research/result_analysis.py` +
`scripts/analyze_long_horizon_result.py`: decomposes an existing
`long_horizon_validation.json` report into fold-return distribution,
regime-conditional performance (walk-forward TRAIN+VALIDATION region
only -- the report schema does not carry a regime label for the
held-out TEST result), gross-to-net cost drag, and (when present --
older reports predate these fields) drawdown-duration and per-security
concentration. Explicitly reports Signal IC and upside/downside
capture as `NOT_COMPUTABLE_FROM_REPORT` rather than silently omitting
or approximating them (both need either a live `DataRepository` or the
full portfolio value time series, neither of which the report JSON
contains).

**Why this is tooling, not a completed analysis**: this sandboxed
session's own repository checkout has no real 40-symbol report file
(`data/` is `.gitignore`d and empty here -- confirmed by direct
search, not assumed) -- the actual report exists only in the user's
own environment. The interpretive Track A narrative in
`STRATEGY-VALIDATION-REPORT.md`'s Phase 32 addendum is built from the
data actually relayed into this conversation (the full `held_out_test`
breakdown per strategy, `evidence_assessment` blocks); the
fold-distribution/regime-conditional breakdowns this new script
computes require the user to run it against their own report file and
relay the output, continuing this project's established real-data
workflow.

## Track A resolution addendum -- TEST-2 Option A

Per `ML-RESEARCH-PROTOCOL.md` section 3, Option A (wait for real
future data) is the resolved default: `build_chronological_split`'s
TEST region is mechanically the most recent 20% of whatever
`[start, end]` a future run specifies, so any re-run with a later
`--end` date automatically produces a new, not-yet-observed TEST
region without any manual TEST-2 selection. Option B (a pre-registered
historical TEST-2 carved out of the current TRAIN+VALIDATION region)
remains documented as a fallback, not selected, since it is not yet
needed.

## Consequences

- `overlaps_any_locked_window` is available for any future script
  (rule-based or ML) to check before building a new data split; no
  existing script currently calls it, since none currently builds a
  *new* split that could conflict (the existing `run_long_horizon_
  validation.py` always reconstructs the same TEST-1 range from the
  same `--start`/`--end`/split-fraction defaults).
- No `src/broker/`, `src/risk/`, `src/backtest/engine.py`, or any
  existing strategy's signal-generation code touched by this ADR.
- Full suite passing (see PROJECT_STATUS.md Phase 32 entry for the
  exact count).

## Addendum -- Signal IC came back near-zero; next hypothesis chosen before its own result exists

The user ran `compute_signal_ic_from_catalog.py --strategy
long_term_momentum` against the real catalog:
`mean_ic=-0.0078, ic_information_ratio=-0.031, positive_ic_ratio=51.9%`
over 79 walk-forward observations -- essentially no rank-predictive
power (see `STRATEGY-VALIDATION-REPORT.md` Section G/Q2 for full
interpretation). This reframes the project's most consequential open
question from "did portfolio construction ruin a good signal" to "was
the signal itself ever informative."

Per this same discipline (a new hypothesis must be committed BEFORE
its own result exists, not chosen by searching for whatever would look
good against this specific finding), two further diagnostics were
built and are documented here as decided *before* being run:

1. **`strategy_research.factor_scores.low_volatility_score`** +
   `compute_signal_ic_from_catalog.py --strategy low_volatility` --
   the low-volatility anomaly, a well-documented, independently
   pre-existing hypothesis (decades old in the literature), not a
   cosmetic variant of momentum. Chosen specifically because it is
   cheap to test (reuses `trim_to_lookback`/`annualized_volatility`,
   no new dependency) -- the deliberate next step BEFORE investing in
   a full ML build-out, matching `ML-RESEARCH-PROTOCOL.md`'s
   dependency-policy reasoning (adopt heavier machinery only once a
   specific need is justified, not speculatively).
2. **`strategy_research.signal_ic.bucket_return_analysis`** +
   `scripts/compute_filter_bucket_returns_from_catalog.py` -- the
   boolean-filter analog of IC (mean forward return of filter-passing
   vs. filter-failing groups), for `trend_volatility`'s
   `_passes_filter`, which has no continuous score for Spearman IC to
   apply to. `trend_volatility` is the one candidate that cleared the
   fold-consistency bar, making whether its filter carries real
   information the single most decision-relevant open question left.

Both reuse the identical TEST-1 hard-refusal guard (no override flag)
as the original IC script, for the identical reason: their underlying
window computations were also corrected by this same ADR's Decision-1
fix, so evaluating them against TEST-1 would test whether the fix
helped using the already-observed window. 15 new tests
(`bucket_return_analysis` unit tests, `low_volatility_score` unit
tests against the synthetic FLATLOW/FLATHIGH pair, and both scripts'
CLI tests including the refusal path). Neither has been run against
the real catalog yet -- both remain open, pre-committed next steps.

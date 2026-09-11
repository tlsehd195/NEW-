# ADR-0031: Long-Horizon Walk-Forward Validation (Phase 25)

**Status:** Accepted

## Context

Phase 24's real-data run (`scripts/run_first_real_strategy_evaluation.py`)
gave this project its first-ever real performance numbers -- but a
single window with no train/validation/test split and no walk-forward
re-test. Phase 25's instruction is explicit that a single good-looking
backtest must never be read as evidence of alpha, and requires building
the infrastructure to assess a strategy's *generalization*: chronological
train/validation/test discipline, rolling walk-forward re-testing across
multiple independent windows, and an explicit, structurally-enforced
distinction between "we have not looked yet," "we have a little
evidence," and "a human should review this as a candidate" -- with no
code path in this project ever allowed to self-declare "validated" or
"alpha found."

## Decision 1 -- Walk-forward folds run without touching `backtest.engine` at all

`AsOfDataView.get_bars(security_id, start, end)` (Phase 2, unmodified)
binds to `self._clock.current_time` for its own lookback query,
independent of `BacktestConfig.start_date`/`end_date` -- those fields
only bound which checkpoints the engine builds, never what history a
strategy's own `data.get_bars(...)` call can see. This means a fold's
own out-of-sample TEST window can be run as the backtest's entire
`start_date`/`end_date`, and a strategy with (say) a 12-month lookback
still sees genuine prior history the moment its first checkpoint fires
-- with zero new plumbing. `src/strategy_research/walk_forward_evaluation.py`
is built entirely on this observation: `run_walk_forward_evaluation`
calls `strategy_research.runner.run_gross_and_net` (Phase 23, unmodified)
once per fold with `start_date=window.test_start`, `end_date=window.test_end`
-- never `window.train_start`. `train_window_months` is therefore a
documentation/sanity parameter (how much prior history this evaluation
assumes exists), not a second backtest phase this module runs. This was
the only design considered: adding a train-then-test two-phase runner
inside `BacktestEngine` itself would have duplicated logic the point-in-time
architecture already provides for free.

Each fold starts from a fresh `initial_capital` -- walk-forward's
purpose here is checking consistency of an edge across independent
periods, not simulating one continuous multi-decade compounding run
(instruction section 12).

## Decision 2 -- Regime classification reuses Phase 5's `RegimeDetector` unchanged

Section 13 of the instruction asks which market regime each fold's test
window fell in. `src/regime/detector.py`'s `RegimeDetector.compute_composite`
plus `make_single_point_view` (both Phase 5, unmodified) already produce
a BULL/BEAR/NEUTRAL `TrendState` for a subject as of a point in time.
`run_walk_forward_evaluation` calls these once per fold, against
`regime_subject_id` (typically the benchmark symbol) as of each fold's
`test_end`, and records the result on `WalkForwardFoldResult.regime_trend_state`.
Building a second, walk-forward-specific regime model was considered
and rejected -- it would have been an unmotivated duplicate of an
already-tested Phase 5 component.

## Decision 3 -- `EvidenceLevel` is a separate vocabulary from `CandidateClassification`, and structurally cannot reach `VALIDATED`

Phase 23's `CandidateClassification` (`REJECTED`/`INCONCLUSIVE`/
`PROMISING_CANDIDATE`) grades a single run. Phase 25 needed a different
axis entirely: how *strong* is the accumulated multi-fold evidence
itself, independent of whether any one fold looked good.
`src/strategy_research/evidence.py`'s `EvidenceLevel` enum
(`INSUFFICIENT_EVIDENCE`/`PRELIMINARY`/`ROBUSTNESS_PENDING`/`CANDIDATE`/
`VALIDATED`) and `classify_evidence_level(aggregate, *, is_real_data,
pbo_dsr_applied)` were added alongside, not merged into, the existing
classification module -- the two questions ("what does this run
suggest" vs. "how much do we actually know yet") are genuinely
different and conflating them would have made both harder to reason
about.

`classify_evidence_level` is structurally incapable of ever returning
`EvidenceLevel.VALIDATED` -- there is no code path, no threshold
combination, that produces it. The highest level the function can
itself award is `CANDIDATE`, gated on real (never synthetic) data,
>= `MIN_FOLDS_FOR_ROBUSTNESS` (6) real folds, PBO/Deflated-Sharpe having
actually been applied, a positive-fold ratio >= 60%, and evidence
spanning >= 2 distinct known market regimes. `VALIDATED` exists in the
enum only as a documented target state a human reviewer can assign
after review this module cannot perform -- mirroring this project's
existing pattern of `CandidateClassification` never having a
`PROVEN_ALPHA` member (instruction section 20's "AI가 알파를 찾았다고
말하지 않는다," enforced structurally rather than left to good
intentions).

`is_real_data=False` forces `INSUFFICIENT_EVIDENCE` regardless of fold
count or how good the numbers look -- a synthetic-fixture run is a
pipeline-correctness check, never evidence about real-world strategy
performance (instruction rule 0.4).

## Decision 4 -- PBO/Deflated Sharpe stays deferred; this phase only checks *whether* its adoption trigger has fired

`docs/research/walk-forward-pbo-deflated-sharpe.md` (Phase 18) already
named PBO/DSR's adoption trigger: multiple candidate strategies being
compared for the same promotion decision, each with enough real
out-of-sample evidence to rank meaningfully. `assess_pbo_dsr_applicability`
checks exactly that (>= `min_candidates` candidates logged in a
`ResearchLog`, each with >= `min_folds_per_candidate` real walk-forward
folds) and reports `applicable: bool` plus its reasoning -- it does
**not** compute PBO or Deflated Sharpe itself. Actually implementing
that computation remains a future phase's decision, consistent with the
existing DECISION REQUIRED framing in the Phase 18 document; nothing in
Phase 25 changes that. Consequently `classify_evidence_level`'s
`pbo_dsr_applied` argument is always `False` in this phase's own CLI run
(`scripts/run_long_horizon_validation.py`) -- no strategy evaluated by
this phase's own tooling can reach `CANDIDATE`, only as high as
`ROBUSTNESS_PENDING`, which is the honest ceiling given PBO/DSR is not
yet actually computed anywhere in this codebase.

## Decision 5 -- `scripts/run_long_horizon_validation.py`: chronological split reserves TEST, walk-forward runs across TRAIN+VALIDATION only

`strategy_research.splits.build_chronological_split` (Phase 23,
unmodified) divides the real ingested window into TRAIN/VALIDATION/TEST.
The CLI script runs `run_walk_forward_evaluation` across
`[train_start, validation_end)` only (the "developmental" region this
script is free to examine via multiple folds), and separately runs one
single `run_gross_and_net` call across `[test_start, test_end]` --
labeled `held_out_test` in its report, distinct from the walk-forward
`folds` -- evaluated exactly once. This gives genuinely both pieces the
instruction asks for (chronological TRAIN/VALIDATION/TEST discipline,
*and* multi-fold walk-forward) without starving either of the limited
real history currently ingested (2023-2024, ~2 years): with the
project's only real data this short, running walk-forward across the
*entire* range and treating the whole thing as a single implicit "test"
would have quietly abandoned the TEST-window-touched-once discipline
the instruction explicitly requires (section 24, "TEST 구간은 마지막에
딱 한 번만 사용한다").

Every strategy still uses its existing default `*Parameters` dataclass
-- no grid search, and nothing in this script reads its own prior
output before choosing what to run next (RULE 0.8: parameters fixed
before evaluation, never re-tuned afterward). The script's own argparse
defaults for `--train-window-months`/`--test-window-months`/`--step-months`
were chosen before ever running against real data, not tuned against
any result.

Like `scripts/run_first_real_strategy_evaluation.py` before it, this
script is never imported by the automated test suite (it reads a real,
already-ingested DuckDB catalog the test suite never has, and its
runtime scales with how much real history exists).

## Consequences

- This project can now honestly grade "how much do we actually know"
  about a strategy candidate, separately from "did this one run look
  good" -- and no automated code path in this codebase can produce the
  words "validated" or "alpha" as a classification result.
- With only ~2 years of real history currently ingested, most or all
  real evidence assessments from this phase's own run are expected to
  land at `INSUFFICIENT_EVIDENCE` or `PRELIMINARY`/`ROBUSTNESS_PENDING`
  -- this is the correct, honest outcome given the data actually
  available, not a defect in the walk-forward machinery itself (see
  `docs/research/STRATEGY-VALIDATION-REPORT.md` for the actual run's
  results and the external command needed to gather more real history).
- PBO/Deflated Sharpe remains unimplemented; this phase only adds the
  ability to check whether its documented adoption trigger has fired,
  consistent with Phase 18's DECISION REQUIRED framing.

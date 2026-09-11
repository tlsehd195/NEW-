# ADR-0035: PBO / Deflated Sharpe Ratio Implementation

**Status:** Accepted

## Context

`docs/research/walk-forward-pbo-deflated-sharpe.md` (Phase 18-20) left
PBO/Deflated Sharpe Ratio (DSR) implementation deliberately DEFERRED,
naming a specific, checkable trigger condition for the
`strategy_research` walk-forward track (distinct from that document's
own `evolution`/`learning` model-training track, which has its own,
separate trigger conditions unrelated to this decision):
`strategy_research.evidence.assess_pbo_dsr_applicability` returns
`applicable=True` once multiple real candidates each have enough real
out-of-sample folds to make a selection-bias question meaningful.

That trigger fired for the first time this session: the user obtained
real 2010-2026 Tiingo data in their own network-enabled environment
(outside this sandboxed session) and ran
`scripts/run_long_horizon_validation.py --data-status REAL` against
all 4 existing strategies, producing 76 real walk-forward folds per
candidate. `assess_pbo_dsr_applicability` correctly reported
`applicable=True` (4 candidates, each with 76 >= the 6-fold minimum).
Per this project's own trigger-condition contract
(`walk-forward-pbo-deflated-sharpe.md` section 9.1, condition 2), this
is exactly the moment DEFER should end for this track.

Result before this ADR: `trend_volatility` was the only one of the 4
strategies whose fold-level win rate (53/76 = 69.7%) cleared the
existing `MIN_POSITIVE_FOLD_RATIO_FOR_CANDIDATE` bar -- but whether
that reflects a genuine, persistent edge or simply "the best of 4
compared candidates" was, until this phase, unanswerable.

## Decision 1 -- Implement PBO via CSCV and DSR now, in `strategy_research.pbo_dsr`

Built per the two primary sources cited in the design doc (Bailey,
Borwein, Lopez de Prado, Zhu 2015 for PBO; Bailey & Lopez de Prado 2014
for DSR), with formulas transcribed directly from those papers, not
from a secondary summary -- the design doc's own section 4 warned that
an approximate/unverified implementation would be worse than none.

**Adaptation, stated explicitly**: both papers operate on a matrix of
per-PERIOD (typically daily) returns; this project's walk-forward folds
are already independent, non-overlapping, genuinely out-of-sample
periods (Phase 25). `compute_pbo`/`compute_dsr_for_all_candidates`
therefore treat each FOLD as one CSCV observation directly rather than
sub-dividing into finer periods -- a faithful, conservative reading of
the same question ("does the in-sample-best candidate's edge persist
out-of-sample"), documented rather than silently assumed.

**No new dependency**: both `math.erf`-family normal CDF/inverse-CDF
needs are met entirely by the stdlib `statistics.NormalDist` (Python
3.8+, already `>=3.11` required by this project) -- `numpy`/`scipy`
are not installed in this environment and were not added. Skewness/
kurtosis (needed for the Probabilistic Sharpe Ratio term inside DSR)
are implemented directly from their standard formulas; the raw
(non-excess) kurtosis convention is used deliberately, matching the
published PSR formula's `(gamma4 - 1) / 4` term exactly (documented
in-code so a future edit does not "fix" this into a bug by subtracting
3).

**Validated against known-labeled synthetic cases before ever being
applied to anything real** (`tests/strategy_research/test_pbo_dsr.py`):
a candidate with a consistently, meaningfully better return in every
fold gets PBO near 0 and DSR near 1; four candidates with identical
(zero) true edge, differing only by noise, get PBO > 0.5 and DSR near
0 for all four. This is the specific verification the design doc's
"Alternatives Considered" section demanded before trusting any
implementation.

## Decision 2 -- CANDIDATE now additionally requires passing PBO/DSR thresholds, additively

`classify_evidence_level` gained two new optional parameters
(`pbo_probability`, `deflated_sharpe_ratio`, both `None` by default).
When a caller supplies both, CANDIDATE additionally requires
`pbo_probability < 0.5` (better than a coin flip) and
`deflated_sharpe_ratio >= 0.95` (the conventional bar for "probably not
just the best of N noisy trials") -- both thresholds fixed here, before
being applied to any real candidate's actual PBO/DSR numbers, never
tuned against an observed result (this project's RULE 0.8 discipline).

Every pre-existing caller (tests, and `run_long_horizon_validation.py`
before this phase) that only ever set `pbo_dsr_applied=True` without
supplying the actual numbers is unaffected -- omitting the new
parameters preserves the exact prior "trust the caller's flag"
behavior. This was necessary to avoid breaking or weakening any
pre-existing test (confirmed: all pre-existing evidence tests pass
unmodified).

## Decision 3 -- Fixed a real bug found while wiring this in: applicability was computed but never applied

`scripts/run_long_horizon_validation.py` already called
`assess_pbo_dsr_applicability` after evaluating all 4 strategies and
printed its result -- but every strategy's own
`classify_evidence_level` call, made earlier in the same loop, always
passed the literal constant `pbo_dsr_applied=False`. This meant every
real run's evidence was silently capped at `ROBUSTNESS_PENDING`
regardless of what applicability found, since the printed applicability
line was never fed back into the classification that actually
determines each strategy's `EvidenceLevel`.

Fixed by restructuring into two passes: (1) run every strategy's
walk-forward + held-out TEST and record it in the `ResearchLog`; (2)
check applicability, and -- only when applicable and the run is REAL
(never synthetic) -- actually compute PBO/DSR from the real per-fold
net returns already collected in pass 1; (3) classify each strategy's
evidence using the real computed numbers. Regression-tested via new AST
wiring tests (`tests/strategy_research/test_run_long_horizon_validation_wiring.py::TestPboDsrActuallyAppliedNotJustPrinted`)
proving `classify_evidence_level` is never called with the hardcoded
constant `False` again, and that PBO computation only happens inside
an `is_real_data` guard.

## Decision 4 -- A standalone script to apply this to an already-completed real run without re-running the backtest

The user's actual real walk-forward run (76 folds x 4 strategies, real
2010-2026 Tiingo data, run in their own network-enabled environment)
took roughly an hour. Every per-fold net return PBO/DSR needs is
already persisted in that run's `long_horizon_validation.json` report
(`results[name]["walk_forward"]["folds"][i]["net"]["cumulative_return"]`).
Rather than requiring a full re-run just to add PBO/DSR,
`scripts/compute_pbo_dsr_from_report.py` reads an existing report,
reconstructs enough of each candidate's `WalkForwardAggregate` from the
already-persisted aggregate fields to re-run
`classify_evidence_level`, computes PBO/DSR from the already-persisted
per-fold returns, and writes an updated report -- a pure, fast
statistics computation with no network access and no backtest re-run.
Refuses to run against anything but `data_status: "REAL"`, matching
this project's `is_real_data` discipline everywhere else. Because it
makes no network call, it is directly exercised end-to-end by the
automated test suite, unlike `run_long_horizon_validation.py` itself.

## Decision 5 -- What this does NOT decide

This ADR does not resolve `walk-forward-pbo-deflated-sharpe.md`
section 7's still-open DECISION REQUIRED (Option A: hard gate before a
human considers `APPROVED` for Live capital, vs. Option B:
informational context) -- that question concerns the `evolution`/
`learning` model-promotion boundary and Live-capital stakes, which
remains untouched and structurally unaffected by this phase. This ADR
only concerns the `strategy_research` walk-forward evidence track's own
`CANDIDATE` bar, a research-evidence classification with no connection
to order submission, `evaluate_safety_gate`, or any Live/Toss/broker
code (none of which was touched -- confirmed via `git diff --stat`
scope check).

## Consequences

- Every future real `run_long_horizon_validation.py --data-status REAL`
  run with >= 2 candidates each carrying >= 6 real folds now
  automatically computes and applies real PBO/DSR -- no further wiring
  needed.
- The user's already-completed real run can get its true evidence
  classification (including whether `trend_volatility`'s apparent edge
  survives PBO/DSR scrutiny) by running
  `scripts/compute_pbo_dsr_from_report.py --report
  <path-to-long_horizon_validation.json>` against the report their
  Codespaces run already produced -- no re-run of the expensive
  walk-forward required.
- `MAX_PBO_FOR_CANDIDATE`/`MIN_DSR_FOR_CANDIDATE` are this project's
  first-ever fixed statistical significance thresholds for strategy
  evidence; like every other named threshold in `evidence.py`, they are
  documented, fixed before use, and open to revision only via a future,
  separately-justified decision -- never silently loosened to make a
  disappointing result pass.

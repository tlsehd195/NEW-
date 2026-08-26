# Research: Walk-Forward Validation / Purged K-Fold / Embargo / PBO / Deflated Sharpe Ratio

Phase 18 (instruction section 13). This is a research and documentation
task only -- **nothing in this document is implemented this phase**.
No code in `src/learning/*`, `src/evolution/*`, or `src/backtest/*` was
changed as a result of this research.

## 1. What design decision requires this evidence?

`docs/decisions/ADR-0017-model-evolution.md` decision 3 already
deferred this exact question once (Phase 11): `evolution.criteria.
evaluate_transition`'s gates check that a candidate's train/validation/
test metrics *exist*, have a *sufficient sample count*, and are
*finite* -- proof the pipeline ran end to end without a degenerate
result, never a claim of statistical robustness against overfitting.
`docs/operations/PRODUCTION-READINESS-MATRIX.md`'s "Walk Forward" row
(Phase 17) restates the same gap as still open and names it a
`DECISION REQUIRED`.

The concrete decision this research exists to inform:

> Should `evolution.criteria`'s promotion gates (or a Live-activation
> precondition) require Walk-Forward / Purged-K-Fold / PBO / Deflated
> Sharpe evidence before a candidate model is trusted enough to reach
> `OOS_TESTED` (the highest state this codebase's automation can ever
> reach on its own -- `APPROVED`/`DEPLOYED` always require a human,
> `docs/decisions/ADR-0017` decision 2), or before a human approves a
> model for Live?

This is a **methodology adoption decision**, not an implementation
detail -- it changes what "the pipeline ran correctly" is allowed to
mean, and it directly affects whether a future model's apparent skill
should be trusted. It is not decided by this document; the
Recommendation in section 6 is a recommendation, not an adoption.

## 2. What each technique actually is (with citations)

### 2.1 Walk-Forward Validation

Re-fits a model on a rolling or expanding historical window and tests
it on the immediately following out-of-sample window, repeated forward
through time -- the classical alternative to a single train/test split
for time-ordered data. This codebase already has the *structural*
prerequisite for walk-forward testing: `learning.config.SplitConfig`
performs a **chronological** train/validation/test split
(`learning/dataset.py::build_training_dataset`, sorted by
`sample_as_of_time`, never shuffled -- instruction section 10's "random
shuffle을 기본값으로 사용하지 않는다" is already honored). What is
**not** built is the *repetition* across multiple rolling windows with
a fresh model fit each time, or any aggregation of the resulting
out-of-sample performance distribution.

### 2.2 Purged K-Fold Cross-Validation and Embargo

Developed by Marcos López de Prado (*Advances in Financial Machine
Learning*, 2018) to fix a specific leakage failure mode in ordinary
k-fold cross-validation applied to overlapping, label-dependent
financial samples:

- **Purging**: removes from the training set any observation whose
  label-formation window overlaps the time range of a test-set label,
  so the model cannot train on information that will be used to
  evaluate it.
- **Embargoing**: a further, smaller exclusion window placed
  immediately after each test fold, to catch a subtler leak -- an
  observation that does not literally overlap the test fold but is
  still causally contaminated by it (e.g. market reaction lag).

(Source: [Purged cross-validation, Wikipedia](https://en.wikipedia.org/wiki/Purged_cross-validation),
summarizing López de Prado's original method; primary source is
*Advances in Financial Machine Learning*, Wiley, 2018, chapter 7.)

This project's own point-in-time discipline (`backtest.asof.
AsOfDataView`, `data_infra` availability-time filtering, and
`learning.dataset._filter_by_cutoff`'s `as_of_cutoff`) already
addresses the *simpler* form of this leakage (never seeing a sample
before its `decision_time`). Purging/embargo address the *harder*
form: overlapping *label* windows between folds when the same
underlying time series is cross-validated with k-fold rather than a
single chronological split. Since this codebase does not currently
perform any k-fold cross-validation at all (only a single chronological
train/validation/test split), purging/embargo are not yet applicable --
they would become relevant only if a future phase adopted k-fold
cross-validation for hyperparameter selection or model comparison.

### 2.3 Probability of Backtest Overfitting (PBO)

Bailey, Borwein, López de Prado, and Zhu, *"The Probability of
Backtest Overfitting,"* Journal of Computational Finance (2015),
[SSRN 2326253](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253),
mathematical appendix at
[SSRN 2568435](https://papers.ssrn.com/sol3/Delivery.cfm/SSRN_ID2568435_code434076.pdf?abstractid=2568435&type=2).
Estimates, via a numerical method called Combinatorially Symmetric
Cross-Validation (CSCV), the probability that the *best-performing*
strategy among many tried in-sample will underperform the *median*
strategy out-of-sample -- directly targeting "repeated-selection bias,"
the exact failure mode `docs/decisions/ADR-0017` section 3 already
named as its reason for not attempting an unvalidated implementation
in Phase 11. PBO requires comparing **multiple** candidate
configurations against each other over the **same** data, which
presumes `evolution.comparison.compare_candidates`-style multi-candidate
evaluation already exists (it does, Phase 11) -- but PBO itself, the
CSCV resampling procedure, is not implemented anywhere in this
codebase today.

### 2.4 Deflated Sharpe Ratio (DSR)

Bailey and López de Prado, *"The Deflated Sharpe Ratio: Correcting for
Selection Bias, Backtest Overfitting, and Non-Normality,"* Journal of
Portfolio Management, 40(5), pp. 94-107 (2014),
[SSRN 2460551](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551).
Built on the Probabilistic Sharpe Ratio (PSR), DSR corrects a reported
Sharpe ratio for two specific inflation sources: (a) **selection bias
under multiple testing** -- the more strategy variants tried, the more
likely one clears a given Sharpe threshold by chance alone -- and (b)
**non-normal returns** (skew, fat tails). It replaces a fixed benchmark
Sharpe with a *deflated* (trial-count-adjusted) one. This project's own
`broker.paper.performance.sharpe_ratio`/`sortino_ratio` (Phase 18) and
`backtest.metrics.sharpe_ratio` (Phase 2) both report a raw Sharpe
ratio with no such correction -- entirely consistent with
`PROJECT_MASTER_PLAN.md` section 1.1's "단일 높은 수익률만으로 모델
우위를 주장하지 않는다" discipline already being honored at the
*reporting* level (no ranking/winner field anywhere,
`docs/decisions/ADR-0017` decision 4), but the DSR's specific
correction is not computed anywhere.

## 3. How these would apply to this project's current architecture

| Technique | Where it would plug in | What's already in place | What's missing |
|---|---|---|---|
| Walk-Forward | `evolution.pipeline`/a new orchestration layer re-running `learning.dataset.build_training_dataset` + `evolution.trainer` across rolling `as_of_cutoff` windows | Chronological split (`learning.config.SplitConfig`), point-in-time cutoff (`as_of_cutoff`) | Repetition across multiple windows; aggregation/reporting of the resulting distribution of out-of-sample metrics |
| Purged K-Fold / Embargo | Would replace or supplement the current single chronological split, if k-fold CV is ever adopted | Point-in-time filtering (single-split case) | Not applicable until k-fold CV itself is adopted -- no current use case |
| PBO | A new module comparing the in-sample-best candidate's out-of-sample rank across resampled combinations of `evolution.comparison`'s candidate set | Multi-candidate comparison (`evolution.comparison.compare_candidates`), no ranking/winner field (by design) | The CSCV resampling procedure and probability estimate themselves |
| Deflated Sharpe Ratio | A correction applied to `broker.paper.performance.PaperPerformanceReport.sharpe_ratio` or `backtest.metrics.PerformanceReport.sharpe_ratio`, parameterized by the number of trials/candidates evaluated | Raw Sharpe ratio, honestly `None` on insufficient data (Phase 18) | The trial-count tracking and deflation formula |

## 4. Cost and risk of implementing now

All four require nontrivial new statistical code with real correctness
risk if rushed:

- PBO and DSR both require tracking **how many strategy variants were
  actually tried** -- a number this codebase does not currently record
  anywhere (`evolution.lineage.ModelLineageRecord` tracks parent/
  generation, not a trial *count* across a comparison set). Getting
  this count wrong produces a confidently-wrong probability/ratio,
  arguably worse than reporting nothing.
- Walk-forward requires re-running the full train/evaluate pipeline
  many times, which is a new orchestration capability, not a formula.
- None of these has this codebase's own existing "baseline first, prove
  the pipeline" precedent to fall back on the way
  `MeanRewardBaselineTrainer`/`TrailingWindowMeanTrainer` did for Phase
  9/11 -- there is no trivial, hand-verifiable version of PBO or DSR to
  build first.

## 5. Alternatives Considered

1. **Implement a simplified/approximate PBO or DSR now.** Rejected --
   an approximate implementation of a statistical correction is exactly
   the "plausible-looking but potentially misleading number" ADR-0017
   decision 3 already warned against; a wrong PBO/DSR is worse than an
   honestly absent one.
2. **Adopt walk-forward validation only, deferring PBO/DSR.** Considered
   viable as a smaller first step (it requires no new trial-count
   bookkeeping), but still requires new orchestration work spanning
   multiple phases' worth of pipeline re-runs -- left to the
   Recommendation below rather than decided here.
3. **Do nothing and leave the gap silently unaddressed.** Rejected --
   `docs/operations/PRODUCTION-READINESS-MATRIX.md`'s existing "Walk
   Forward" row already flags this; silence would contradict that
   row's own "Human Decision Required: Yes."

## 6. Recommendation (not a decision -- see DECISION REQUIRED below)

Do not implement any of the four this phase or unilaterally. If a
future phase takes this on, walk-forward validation is the most
tractable first step (no new trial-count bookkeeping, reuses the
existing chronological-split machinery), with PBO and DSR following
only once a real, recorded trial count exists to parameterize them
correctly. Purged K-Fold/Embargo should be revisited only if/when
k-fold cross-validation is separately adopted -- they solve a leakage
problem this codebase does not currently have, since it never
cross-validates with overlapping folds.

## 7. DECISION REQUIRED

```
DECISION REQUIRED
Problem: Phase 9 (ADR-0015) and Phase 11 (ADR-0017) both deliberately
deferred any overfitting-robustness validation (Walk-Forward/Purged
K-Fold/Embargo/PBO/Deflated Sharpe) for a candidate model. Today,
evolution.criteria.evaluate_transition's gates prove a candidate's
train/evaluate pipeline ran end-to-end without a degenerate result --
they prove nothing about whether its apparent skill would survive
out-of-sample scrutiny beyond the single chronological test split
already used.
Current Design: A candidate can reach CandidateModelStatus.OOS_TESTED
(the highest state this codebase's own automation can reach) without
ever passing a walk-forward re-test, a PBO check, or a Deflated Sharpe
correction. Reaching APPROVED/DEPLOYED beyond that always requires a
human (structurally enforced, ADR-0017 decision 2) -- this document
does not touch that boundary.
Option A: Require Walk-Forward validation (and, once feasible, PBO/DSR)
as a new, additional promotion gate before a human is even asked to
consider approving a candidate -- raising the evidentiary bar before a
human decision is requested at all.
Option B: Leave the current gates as-is (structural pipeline-health
proof only) and treat Walk-Forward/PBO/DSR as informational context a
human reviewer can request separately, case by case, rather than a
hard gate.
Recommendation: No recommendation between A and B is made here -- this
is a methodology-adoption decision about how much statistical rigor
this project requires before trusting a model, which belongs to
whoever is accountable for capital risk, not to this research
document.
Impact: Until decided, any candidate model this project ever produces
carries an honestly-documented, unquantified overfitting risk beyond
what a single chronological OOS split reveals -- consistent with every
prior phase's own disclosure of the same limitation, not a new risk
introduced this phase.
```

## Sources

- [The Probability of Backtest Overfitting (SSRN 2326253)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253) -- Bailey, Borwein, López de Prado, Zhu (2015)
- [Mathematical Appendices to "The Probability of Backtest Overfitting" (SSRN 2568435)](https://papers.ssrn.com/sol3/Delivery.cfm/SSRN_ID2568435_code434076.pdf?abstractid=2568435&type=2)
- [The Deflated Sharpe Ratio: Correcting for Selection Bias, Backtest Overfitting, and Non-Normality (SSRN 2460551)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551) -- Bailey, López de Prado (2014), Journal of Portfolio Management 40(5)
- [Purged cross-validation, Wikipedia](https://en.wikipedia.org/wiki/Purged_cross-validation) -- summary of López de Prado's purging/embargo method (primary source: *Advances in Financial Machine Learning*, Wiley, 2018)

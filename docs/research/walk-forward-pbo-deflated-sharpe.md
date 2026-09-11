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
evaluation already exists (it does, Phase 11). **Since implemented
(ADR-0035, ADR-0115 correction of this section's earlier "not
implemented anywhere in this codebase today" claim)**: the CSCV
resampling procedure and PBO/Deflated Sharpe Ratio computation now
live in `src/strategy_research/pbo_dsr.py`, used by
`scripts/compute_pbo_dsr_from_report.py` and cross-checked against
external statistical libraries (ADR-0046) -- see
`docs/research/STRATEGY-VALIDATION-REPORT.md` for real PBO/DSR results
computed against real walk-forward reports.

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

## 8. Phase 19 classification: IMPLEMENT NOW / DEFER / DECISION REQUIRED

Phase 19 required a specific classification, not just a restatement of
the open question. Analysis:

- **Is it required for the Live Safety Gate specifically?** No.
  `evaluate_safety_gate`'s job is structural execution safety (broker
  capability, human approval, kill switch, reconciliation, account/
  position state) -- a fail-closed gate about whether it is safe to
  *submit an order at all* right now. Walk-Forward/PBO/DSR answer a
  different question -- "should this specific model be trusted" -- which
  belongs to the model validation pipeline
  (`evolution.criteria`/`CandidateModelStatus`), not the order-submission
  gate. Conflating the two would blur a boundary this project has kept
  deliberately clean since Phase 13 (`docs/decisions/ADR-0019` and every
  subsequent broker-layer ADR: the broker layer never re-implements
  Decision/Risk/model-quality logic).
- **Does it conflict with the existing backtest/validation
  architecture?** No -- it would extend `learning.config.SplitConfig`'s
  existing chronological split, not replace or contradict it.
- **Does it duplicate the current validation protocol?** Partially --
  OOS testing (a single chronological held-out split) already exists;
  PBO/DSR would add a new statistical layer on top, not re-implement
  the split itself.
- **Is there anything to apply it to right now?** No. Every trainer
  this codebase has ever shipped (`MeanRewardBaselineTrainer`, Phase 9;
  `TrailingWindowMeanTrainer`, Phase 11) is an explicitly-documented
  null-hypothesis/pipeline-exercise baseline, never claimed to have real
  forecasting skill. Applying PBO or a Deflated Sharpe correction to a
  baseline that was never meant to look skillful in the first place
  would produce a real number about a question nobody is asking.
- **Implementation risk**: unchanged from section 4 -- PBO/DSR both
  need a real, recorded trial count this codebase does not track
  anywhere yet; building that tracking incorrectly would be worse than
  not building it.

**Classification: DEFER.** Not `IMPLEMENT NOW` (nothing to apply it to,
not required for the safety gate) and not itself a fresh
`DECISION REQUIRED` beyond the one already on record in section 7 above
(that one concerns whether to adopt this *at all* for a future
candidate; this section only concerns *timing*, and concludes there is
no urgency forcing that decision now). This is a technical/
architectural scheduling judgment ("is this the right time to build
statistical-validation infrastructure nothing yet needs"), not a
financial-policy number, so Phase 19 makes it directly rather than
escalating it.

## 9. Phase 20 addendum — trigger conditions, first applicable model, Live-activation linkage

Phase 20's instruction (section 18) asks for three specific things
beyond Phase 19's DEFER classification: a concrete trigger condition
for when DEFER should end, which model would be the first this applies
to, and how adoption would connect to Live activation gating. None of
this changes the classification itself (still **DEFER**, confirmed
again below) — it makes the *conditions for revisiting it* concrete
rather than leaving "someday" unspecified.

### 9.1 Trigger conditions — when DEFER should end

DEFER should end and section 7's DECISION REQUIRED should be
re-escalated for an actual adoption decision when **any** of the
following first becomes true:

1. **A trainer that claims genuine predictive skill is introduced.**
   Every trainer today (`MeanRewardBaselineTrainer`, Phase 9;
   `TrailingWindowMeanTrainer`, Phase 11) is explicitly documented as a
   null-hypothesis/pipeline-exercise baseline — this is *why* section 8
   concluded "nothing to apply it to." The trigger is the first trainer
   whose own documentation claims real forecasting skill rather than
   exercising the pipeline. See 9.2 below for what that model would
   concretely be.
2. **Multiple candidate variations are being compared for the same
   promotion decision.** PBO's entire premise (Bailey et al. 2015) is
   evaluating a *selection among trials* — it is not meaningful for a
   single, non-competing candidate. The trigger is the first time
   `evolution.criteria`/the model registry is asked to choose among more
   than one seriously-considered candidate for the same slot, since that
   is the first moment a trial count and a selection-bias question both
   concretely exist.
3. **A human is about to make an `APPROVED` decision for a candidate
   whose target is Live capital**, not Paper Trading continuation. Paper
   Trading is itself the system's own designed-in overfitting check (an
   unseen forward period, per `docs/decisions/ADR-0021-paper-trading.md`)
   — the stakes that justify PBO/DSR's implementation cost (section 4)
   are specifically real-capital stakes.

None of these three conditions is true today: both existing trainers
are explicit null-hypothesis baselines, no multi-candidate selection
has ever occurred, and Live is independently blocked regardless (Toss
capability gap). **This confirms, rather than merely restates, that
DEFER remains correct as of Phase 20** — the trigger conditions exist
and are checkable, and none has fired.

### 9.2 Which model this would first apply to

No such model exists yet, by name — this section states what it would
look like, not what it is. The first applicable model is: **the first
trainer registered in `evolution.*`/`learning.*` whose own
documentation and evaluation criteria claim actual out-of-sample
predictive skill for a real trading signal**, as opposed to exercising
the train -> evaluate -> `CandidateModelStatus` pipeline end-to-end
(which is all `MeanRewardBaselineTrainer` and `TrailingWindowMeanTrainer`
are documented to do). Until a skill-claiming trainer exists, applying
PBO/DSR to either current trainer would produce a real statistical
number answering a question neither trainer's own documentation asks —
exactly the risk section 8 already flagged, restated here as a positive
identification criterion rather than a negative one.

### 9.3 How this would connect to Live activation gating

Phase 19 (section 8) already established Walk-Forward/PBO/DSR are not
part of `evaluate_safety_gate` — that gate answers "is it safe to
submit an order right now" (broker capability, human approval, kill
switch, reconciliation, account/position state), a structurally
different and deliberately narrower question than "should this model's
apparent skill be trusted." That boundary is not revisited here.

The connection this section adds: **if/when Option A of section 7 is
adopted (Walk-Forward/PBO/DSR required before a human considers
approving a candidate), the natural integration point is evidence
attached to the human `APPROVED` decision itself**
(`docs/decisions/ADR-0017-model-evolution.md` decision 2 — reaching
`APPROVED`/`DEPLOYED` already structurally requires a human, never
automation) — not a new automated precondition inside
`evaluate_safety_gate` or `evaluate_transition`. Concretely: a
Walk-Forward/PBO/DSR report would be evidence a human reviewer expects
to have in hand before approving a candidate targeting Live capital,
the same way a Paper Trading Performance Report (Phase 18) already is
today — not a new automated gate that blocks `OOS_TESTED` from being
reached, and not a new automated blocker inside `LiveTradingSession`.
This keeps the existing clean separation (broker layer never
re-implements Decision/Risk/model-quality logic, restated in section 8)
intact for any future adoption, and requires no architecture change to
support — `evolution.criteria` and the human-approval boundary already
have a natural place for additional evidence to be attached (a
candidate's existing documentation/metrics bundle) without a new gate
mechanism.

This is a proposed integration pattern for *if* Option A is ever
chosen, not itself an adoption decision — section 7's DECISION REQUIRED
(adopt at all, Option A vs. B) remains exactly as open as Phase 19 left
it.

### 9.4 No architecture conflict with future adoption — reconfirmed

Section 8 already confirmed this ("would extend
`learning.config.SplitConfig`'s existing chronological split, not
replace or contradict it"; "would add a new statistical layer... not
re-implement the split itself"). Nothing in Phase 20's real-market-data
work changes that: `learning.dataset.build_training_dataset` and
`evolution.criteria` are both untouched this phase, and the new
`data_infra.providers.tiingo`/`backtest.total_return` modules sit
entirely below the model-training layer, feeding it real price data
through the same `PriceBar`/`DataRepository` interfaces a future
walk-forward re-fit loop would also consume — no new incompatibility is
introduced.

### 9.5 Classification (reconfirmed): DEFER

Unchanged from Phase 19, now grounded in checkable trigger conditions
(9.1) rather than a general "not yet" — **DEFER**. Re-evaluate the
instant any condition in 9.1 becomes true; do not re-evaluate on a
calendar schedule absent one of those conditions.

## Sources

- [The Probability of Backtest Overfitting (SSRN 2326253)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253) -- Bailey, Borwein, López de Prado, Zhu (2015)
- [Mathematical Appendices to "The Probability of Backtest Overfitting" (SSRN 2568435)](https://papers.ssrn.com/sol3/Delivery.cfm/SSRN_ID2568435_code434076.pdf?abstractid=2568435&type=2)
- [The Deflated Sharpe Ratio: Correcting for Selection Bias, Backtest Overfitting, and Non-Normality (SSRN 2460551)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551) -- Bailey, López de Prado (2014), Journal of Portfolio Management 40(5)
- [Purged cross-validation, Wikipedia](https://en.wikipedia.org/wiki/Purged_cross-validation) -- summary of López de Prado's purging/embargo method (primary source: *Advances in Financial Machine Learning*, Wiley, 2018)

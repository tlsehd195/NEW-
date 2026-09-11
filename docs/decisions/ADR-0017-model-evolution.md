# ADR-0017: Model Evolution

**Status:** Accepted

## Context

`PROJECT_MASTER_PLAN.md` §18.1 lists Phase 11 as "Model Evolution."
Phase 9's Learning Engine (ADR-0015) already reserved
`learning.enums.CandidateModelStatus`'s full state machine
(`CANDIDATE -> BACKTESTED -> VALIDATED -> OOS_TESTED -> PAPER_TESTED ->
APPROVED -> DEPLOYED`) but only ever produced `CANDIDATE`. Phase 10's
counterfactual work (ADR-0016 §7) explicitly deferred
`alternative_action_1`/`alternative_action_2` — comparing the trade's
selected action against a different, actually-runnable model/strategy's
hypothetical decision — to this phase, reasoning that orchestrating a
full alternate decision pipeline and registering/tracking it as a
comparable "candidate decision process" is precisely what a named
"Model Evolution" phase is for. Phase 9's own spec (§2.2, §22) already
named "Model Registry completion" as Phase 11 scope.

This session's Git/Branch Integrity Check (see
`docs/specifications/PHASE-11-model-evolution.md` §0) found the assigned
working branch had been created from `main` rather than the real Phase
0-10 lineage, and re-rooted it (no history rewrite — the branch had no
work of its own yet) onto
`origin/claude/phase-10-counterfactual-attribution-ubum6u`.

## Decision

### 1. Extend `learning.enums.CandidateModelStatus` transitions via a new
   append-only `ModelStatusTransition` type, not by mutating
   `CandidateModelArtifact.status`

`CandidateModelArtifact` (Phase 9) is a frozen dataclass whose `status`
field its own trainer only ever sets to `CANDIDATE` — by design
(Phase 9 spec, "always `CandidateModelStatus.CANDIDATE`, produced by
this phase"). Rather than introduce mutation (which would break that
Phase 9 invariant and its own boundary test) or a new mutable-status
type, Phase 11 layers `evolution.models.ModelStatusTransition` — an
append-only audit record of every *attempted* transition, passing or
failing — on top of the immutable artifact, exactly mirroring how
`trade_journal.models.PostTradeAnalysis`/`CounterfactualRecord`/
`AttributionResult` already layer append-history analysis on top of an
immutable `TradeRecord`/`ExperienceRecord` (Phase 3/10). A candidate's
current status is derived at query time as the `to_status` of its most
recent *passed* transition. This keeps Phase 9's source untouched
(zero lines changed) while still giving Model Evolution a real,
queryable, auditable status progression.

### 2. `next_status` is a closed mapping that structurally cannot reach
   `APPROVED`/`DEPLOYED`

`PROJECT_MASTER_PLAN.md` §11.5 is explicit: "`APPROVED` 상태로의 전이만은
사람이 명시적으로 승인해야 한다. Claude Code나 AI가 스스로 `APPROVED`를
부여하지 않는다." Rather than relying on a convention or a runtime check,
`evolution.criteria._NEXT_STATUS` is a Python `dict` literal with three
entries (`CANDIDATE`→`BACKTESTED`, `BACKTESTED`→`VALIDATED`,
`VALIDATED`→`OOS_TESTED`) and no others; `next_status(OOS_TESTED)` raises
rather than returning anything. `tests/evolution/test_evolution_boundary.py`
additionally AST-scans every file in `evolution.*` for any
`.APPROVED`/`.DEPLOYED` attribute reference at all (the same technique
`tests/learning/test_learning_boundary.py` already used for Phase 9),
so even a future edit that tried to add a fourth mapping entry referencing
either value would fail a test immediately, not just at review time.

### 3. Validation criteria check completeness/validity, not
   overfitting-robustness — PBO/Deflated Sharpe/Walk-Forward remain
   deferred

Phase 9 spec §13 already flagged PBO/Deflated Sharpe/Walk-Forward
validation (`PROJECT_MASTER_PLAN.md` §13.5) as out of scope. Model
Evolution is exactly where a naive implementation of "does this
candidate beat the others" would be most tempting to add — and most
dangerous, per the same section's warning about repeated-selection bias.
Rather than attempt an unvalidated implementation that would produce a
plausible-looking but potentially misleading number,
`evolution.criteria.evaluate_transition`'s gates are deliberately
narrow: each target status requires the relevant split's metrics to
exist, have a sufficient (configurable) sample count, and be finite —
proof the train→evaluate chain ran end-to-end without a degenerate
result, not a claim of statistical robustness against overfitting. The
one comparative check available (`PromotionConfig.
max_test_mae_over_baseline_ratio`) is `None` by default — no threshold
is invented; a caller who wants one sets it explicitly.

### 4. `evolution.comparison.compare_candidates` has no `winner`/
   `is_better`/`champion` field

Continuing the discipline `learning.models.EvaluationResult` already
established (Phase 9 spec §13-14: no `candidate_is_better` field,
"단일 높은 수익률만으로 모델 우위를 주장하지 않는다") and
`baseline.report`'s own no-ranking-field design (Phase 4), `evolution.
models.CandidateComparison` is a pure ranking projection — informational,
never a deployment decision. A test asserts the type has no such field
by name.

### 5. `TrailingWindowMeanTrainer` as the second candidate generator, not
   a real ML model

`pyproject.toml` declares only `duckdb`/`pyarrow` as dependencies —
introducing an ML library (numpy/scikit-learn/etc.) to build a "real"
second model would be a dependency decision this phase should not make
unilaterally, and `PROJECT_MASTER_PLAN.md` §1.1 forbids adopting "임의의
AI 모델 하나"를 앞서 구현하는 것 in general. Instead, a second
deterministic, hand-verifiable trainer (mean of only the most recent
`window` TRAIN samples, vs. Phase 9's whole-TRAIN-split mean) gives
Model Evolution's comparison/validation/lineage machinery genuinely
different candidates to exercise, at zero new dependency cost — the
same "baseline first, prove the pipeline, not the model" precedent every
prior phase's own reference implementation has followed
(`RandomWalkPredictor`, `MeanRewardBaselineTrainer`, etc.).

### 6. `alternative_action_1`/`alternative_action_2` reuse Phase 3/10's
   return-calculation functions verbatim, with no new position-sizing
   model

`compute_candidate_decision_alternative` turns a candidate's
`DecisionAction` into a return figure by calling Phase 3's
`compute_hold_counterfactual` (long) or Phase 10's
`compute_cash_counterfactual` (flat) unchanged, negating the former's
result for a SELL (short). Building a proper position-sized return
calculation would require Position Sizing/Risk Engine output threaded
through a purely-analytical, retrospective function — a scope and
correctness burden (Phase 8's own Known Issue already documents an
`average_cost` proxy limitation) far beyond what "which action would a
different model have picked" needs to answer honestly. This mirrors
exactly the reasoning Alternatives Considered #2 in ADR-0016 gave for
not attempting a full Brinson-Fachler `timing`/`selection` split in
Phase 10.

### 7. `ModelLineageRecord.generation` is always derived from a parent
   record, never caller-supplied directly

`evolution.lineage.derive_lineage(candidate, parent=None, ...)` computes
`generation = 0 if parent is None else parent.generation + 1`. During
test development this surfaced a real defect: two `CandidateTrainer`
instances (e.g. `MeanRewardBaselineTrainer()` and
`TrailingWindowMeanTrainer(window=3)`), each carrying its own
in-process id allocator restarting at `CAND-000001`, can produce two
different candidates that happen to share the same `candidate_id` before
a storage-layer sequence assigns a real, persisted id — the exact same
class of bug ADR-0015 §6 already found and fixed for Learning Engine
persistence (`TrainingDataset.dataset_id`/`CandidateModelArtifact.
candidate_id` colliding across independent pipeline runs). Rather than
only fix it at the storage layer (Phase 11's DuckDB repositories already
avoid it the same way Phase 9's do — natural-key dedup, not blind
insert), `ModelLineageRecord.__post_init__` now also rejects a record
whose `candidate_id` equals its own `parent_candidate_id` structurally,
so an in-memory, pre-persistence lineage chain cannot silently become
self-referential either. See the completion report's Bugs Found section
and `tests/evolution/test_model_lineage.py::
TestModelLineageRecordValidation::test_self_referential_parent_rejected`.

### 8. No new leakage surface, one new guarded call site

`evolution.criteria`/`evolution.comparison`/`evolution.lineage` make no
`DataRepository` call at all — the same "reuse the existing guard, add
no new surface" property ADR-0016 §8 established for Phase 10.
`evolution.counterfactual.compute_candidate_decision_alternative` is the
one exception (it must run a live predictor at `decision_time`), and it
reuses `backtest.asof.AsOfDataView`/`backtest.clock.BacktestClock`
unchanged — the identical point-in-time guard every prior phase's live
decision path already uses — rather than inventing a new one.

## Alternatives Considered

1. **Mutate `CandidateModelArtifact.status` in place as it advances.**
   Rejected — breaks Phase 9's own frozen-dataclass invariant and
   boundary test; loses the audit trail of *failed* transition attempts
   a purely append-only design keeps for free.
2. **A full walk-forward/PBO validation harness for Phase 11's status
   gates.** Rejected for this phase — see decision 3; a substantially
   larger, separate piece of work with real risk of a subtly-wrong
   number, the same reasoning Phase 9 §13 and ADR-0016 Alternative #2
   already applied to `timing` attribution.
3. **Add a "recommended candidate"/`winner` field to
   `CandidateComparison` for convenience.** Rejected — see decision 4;
   conflicts directly with `PROJECT_MASTER_PLAN.md` §1.1's "백테스트
   성능이 높다는 이유만으로 모델을 채택하지 않는다."
4. **Introduce a real ML dependency for a second trainer.** Rejected for
   this phase — see decision 5; not this phase's decision to make
   unilaterally, and unnecessary to exercise the comparison/validation/
   lineage machinery this phase actually needs to prove.
5. **A dedicated "Model Registry" service/module distinct from
   `ModelLineageRecord`/`ModelStatusTransition`.** Rejected — Phase 9's
   own comment already scoped "Model Registry completion" to mean
   exactly this persisted lineage/version/status data
   (`PROJECT_MASTER_PLAN.md` §11.3's field list — `model_id`, `version`
   ≈ `candidate_id`/`generation`, `training_dataset`, `feature_version`,
   `metrics`, `approval_status`, `created_at` — is already covered by
   `CandidateModelArtifact` + `EvaluationResult` + `ModelLineageRecord` +
   `ModelStatusTransition` combined); a separate service/API is
   Phase 12+ infrastructure work, not this phase's data model.

## Consequences

### Positive

- Zero modifications to Phase 1-10 source files; `git diff | grep '^-'`
  on `src/storage/schema.py` and `src/storage/serialization.py` shows no
  deleted/changed lines, only additions.
- `alternative_action_1`/`alternative_action_2` — reserved since Phase 3
  — is now filled in, without touching `trade_journal.models`.
- `CandidateModelStatus.BACKTESTED`/`VALIDATED`/`OOS_TESTED` — reserved
  since Phase 9 — are now real, reachable, auditable states.
- No code path anywhere in `evolution.*` can construct
  `APPROVED`/`DEPLOYED`, verified structurally (AST scan), not just by
  convention.
- A real defect (lineage self-reference from independent in-process id
  allocators) was found and fixed with a structural guard plus a
  regression test, before it could reach persisted data.

### Negative / Trade-offs

- `evolution.criteria`'s gates are honest but modest — passing
  `OOS_TESTED` is proof of a valid, non-degenerate evaluation, not proof
  the candidate is good or safe to deploy. A future phase that wants a
  real overfitting-robustness bar (PBO/Deflated Sharpe/Walk-Forward)
  still has that work ahead of it.
- `TrailingWindowMeanTrainer` is, like Phase 9's own trainer, not a
  claim of forecasting skill — it exists to exercise the pipeline, not
  to be adopted as a real strategy.
- The candidate-model counterfactual's return calculation (decision 6)
  is a documented simplification (no position sizing); a caller reading
  `hypothetical_return` as a precisely realistic backtest of the
  alternative model needs to know that limitation.

# Phase 11 — Model Evolution

## 0. Git / Branch Integrity Check (performed before any implementation)

This session ("Session 12") started from a fresh container. `git branch
-a` / `git log -1` showed the designated working branch
(`claude/phase-11-model-evolution-7hpibr`) contained only `Initial
commit` (`c3abad0`) — it had been created from `main`, not from the real
Phase 0-10 lineage. `git branch -r` also showed the previously-existing
remote branch of the same name had already been deleted. `git fetch
origin` located the actual Phase 0-10 lineage on
`origin/claude/phase-10-counterfactual-attribution-ubum6u`, whose HEAD
(`483600fb571c2f392bcc193f7ebbe733b6122a4b`, "Phase 10: Counterfactual /
Attribution") carries a single linear history of 13 commits (Initial
commit → Phase 0 → … → Phase 10), zero merge commits, `main` and every
other listed origin branch each an ancestor of it or unrelated stale
work. The handoff's stated Phase 10 commit hash
(`483600fb571c2f392bccbe73f7ebbe733b6122a4b`) has 42 hex characters —
one more than a real 40-character SHA-1 — and does not match any object
in the repository; the actual commit at that same short prefix and
subject line is `483600fb571c2f392bcc193f7ebbe733b6122a4b`, treated as a
handoff transcription error rather than a repository problem.

Since the assigned branch had no work of its own yet (`git status`
clean, identical to `main`/`Initial commit`), it was safely re-rooted
with `git checkout -B claude/phase-11-model-evolution-7hpibr
origin/claude/phase-10-counterfactual-attribution-ubum6u` — no history
was rewritten or discarded, and nothing was force-pushed. Dependencies
(`duckdb`/`pyarrow`/`pytest`, not preinstalled in this container) were
installed, and the full suite was run before any Phase 11 code was
written: **607/607 tests passed** on the corrected HEAD. See the Phase
11 completion report for the exact commands run.

## 1. Scope

Per `PROJECT_MASTER_PLAN.md` §18.1 (Phase 11 = "Model Evolution") and
the deferred items Phase 9/10 explicitly assigned here (ADR-0015 §1/§10,
Phase 9 spec §2.2/§22 "Model Registry completion (Phase 11)"; ADR-0016
§7, Phase 10 spec §5's "`alternative_action_1`/`alternative_action_2` …
deferred to Phase 11 (Model Evolution)"), this phase implements:

- **Candidate generation**: a second, genuinely different
  `learning.trainer.CandidateTrainer` implementation
  (`evolution.trainer.TrailingWindowMeanTrainer`) plus a thin batch
  helper (`evolution.pipeline.generate_candidate_batch`) so more than
  one candidate can be produced from the same `TrainingDataset`.
- **Candidate comparison**: `evolution.comparison.compare_candidates` —
  ranks candidates evaluated on the same dataset by one explicitly named
  metric. Never a "winner"/deployment verdict (§6 below).
- **Validation / status transitions**: `evolution.criteria` advances
  `learning.enums.CandidateModelStatus` through `CANDIDATE ->
  BACKTESTED -> VALIDATED -> OOS_TESTED` under explicit, versioned,
  numeric criteria (§5). Never reaches `APPROVED`/`DEPLOYED` — those
  require human approval (`PROJECT_MASTER_PLAN.md` §11.5), which this
  phase does not implement any code path for.
- **Model Registry (lineage/versioning)**: `evolution.lineage` +
  `evolution.models.ModelLineageRecord` track which candidate a given
  candidate evolved from and how many generations deep it is
  (`PROJECT_MASTER_PLAN.md` §11.3, §4.5 lineage). `evolution.models.
  ModelStatusTransition` is the append-only audit trail for every
  attempted (passing or failing) status transition.
- **Candidate-model counterfactual**: `evolution.counterfactual.
  compute_candidate_decision_alternative` runs an actually-existing,
  runnable alternative decision process (`predict.predictor.Predictor` +
  `decision.agent.DecisionAgent`) at a trade's own `decision_time` and
  reports what it would have decided — filling the
  "alternative_action_1"/"alternative_action_2" slot
  `PROJECT_MASTER_PLAN.md` §33 and Phase 3/10 reserved for this phase.
- **Persistence**: two new DuckDB tables
  (`model_status_transitions`, `model_lineage`) in Phase 4's existing
  catalog.

### 1.1 Explicitly out of scope

- **`APPROVED`/`DEPLOYED` transitions, or anything that could produce
  them.** `evolution.criteria.next_status` has no entry mapping to
  either value; no function anywhere in `evolution.*` accepts an
  "approve"/"deploy" action. Human approval is a UI/process concern this
  phase does not build.
- **Model Registry as a Phase 12+/AI-Gateway-adjacent subsystem** (a
  separate service, API, or UI for browsing/promoting models). What
  *is* in scope here is the narrower, already-scoped-by-Phase-9/10
  piece: persisted candidate lineage/versioning records
  (`ModelLineageRecord`) and status-transition audit records
  (`ModelStatusTransition`) — the data Phase 9's own comment already
  called "Model Registry completion (Phase 11)".
- **PBO / Deflated Sharpe / Walk-Forward cross-validation**
  (`PROJECT_MASTER_PLAN.md` §13.5). Phase 9 spec §13 explicitly deferred
  these; this phase does not attempt them either — a shaky, unvalidated
  implementation would produce a plausible-looking but potentially wrong
  number, which conflicts with this project's "never estimate a value it
  cannot actually compute" discipline (ADR-0009 point 4, re-affirmed by
  every phase since). `evolution.criteria`'s gates are honest,
  completeness/validity-only checks (§5), not a claim of
  overfitting-robustness.
- **Sector/factor/timing attribution.** Unchanged from Phase 8/10 — no
  new data source for either exists yet.
- **AI Gateway (Phase 12), Toss Securities Adapter (Phase 13),
  Monitoring/Drift (Phase 14), Paper Trading (Phase 15), Live Trading
  (Phase 16).** No real AI API call, broker call, or order is created
  anywhere in this phase.

## 2. Architecture boundary

This phase sits entirely within the existing "Learning / Model
Evolution" layer (`PROJECT_MASTER_PLAN.md` §2's architecture diagram,
§3's module table). It reads `learning.models.CandidateModelArtifact` /
`EvaluationResult` / `TrainingDataset` (Phase 9, unmodified) and
`trade_journal.models.AlternativeOutcome` / `CounterfactualRecord`
(Phase 3/10, unmodified) and produces new records layered on top of
them. It never reaches into Position Sizing, Risk Engine, Order
Validator, or Broker Adapter — `tests/evolution/test_evolution_boundary.py`
verifies structurally (reflection + AST scan) that no order/broker/
risk-mutation field or method exists anywhere in `evolution.*`.

## 3. Candidate Generation

`evolution.trainer.TrailingWindowMeanTrainer(window)` implements the
`learning.trainer.CandidateTrainer` Protocol structurally (duck-typed,
no import of the Protocol needed) so it is a drop-in alternative to
Phase 9's `MeanRewardBaselineTrainer` anywhere a `CandidateTrainer` is
accepted, including `learning.pipeline.run_learning_pipeline`'s
`trainer` parameter. It "trains" the mean `label_value` over only the
most recent `window` TRAIN-split samples (chronological order), rather
than the whole split — a deterministic, ML-free (the project has no ML
dependency; `pyproject.toml` declares only `duckdb`/`pyarrow`)
hyperparameter axis that produces genuinely different candidates from
one dataset. `evolution.pipeline.generate_candidate_batch`/
`evaluate_candidate_batch` are thin composition helpers proving this
end to end — no persistence, no decision authority, the same
"return objects, caller decides what to do with them" separation
`learning.pipeline.run_learning_pipeline` already established.

## 4. Candidate Comparison

`evolution.comparison.compare_candidates(evaluations, metric=...)`
ranks a set of `EvaluationResult`s — all required to share the same
`dataset_id`/`dataset_version`, or it raises — by one explicitly named
metric (`test_mean_absolute_error` by default). It returns
`evolution.models.CandidateComparison`, which has **no
`winner`/`is_better`/`champion` field** (verified by
`tests/evolution/test_evolution_comparison.py::
TestCompareCandidates::test_has_no_winner_or_is_better_field`) — the
same discipline `learning.models.EvaluationResult` already established
by omitting `candidate_is_better` (Phase 9 spec §13-14,
`PROJECT_MASTER_PLAN.md` §13.6 "복잡한 AI가 정말 가치가 있는지
확인한다"). It is a research/review aid, not a deployment decision.

## 5. Status Transitions (Validation)

`evolution.criteria.next_status(current)` is the only source of truth
for what status a candidate may move to next:

```
CANDIDATE -> BACKTESTED -> VALIDATED -> OOS_TESTED
```

There is no entry for `OOS_TESTED` (raises `ValueError` — "no automated
transition exists … APPROVED/DEPLOYED require human approval"), and
`APPROVED`/`DEPLOYED` never appear as a value anywhere in this mapping.

`evolution.criteria.evaluate_transition(candidate, evaluation,
current_status, config)` attempts exactly the one transition
`next_status(current_status)` allows, and **always returns a
`ModelStatusTransition`** — passing or failing, never raising for a
failed gate (mirrors `learning.cleaning.DataCleaner`'s "never silently
drop" discipline, Phase 9, applied to status transitions instead). Every
check it ran is recorded verbatim in `ModelStatusTransition.criteria`
(a `dict`), so a failure is always auditable, not just a boolean.

Gates, by target status (each documented, `PromotionConfig`-controlled
where a numeric threshold is involved — no hardcoded magic numbers):

| Target | Split checked | Criteria |
|---|---|---|
| `BACKTESTED` | TRAIN | sample_count > 0, MAE finite, MSE finite |
| `VALIDATED` | VALIDATION | sample_count ≥ `min_validation_sample_count`, MAE finite, MSE finite |
| `OOS_TESTED` | TEST | sample_count ≥ `min_test_sample_count`, MAE finite, MSE finite, plus optionally: TEST MAE ≤ baseline MAE × `max_test_mae_over_baseline_ratio` (only when that config value is explicitly set — `None` by default, i.e. no comparative bar is invented) |

Before any of the above, `evaluate_transition` checks referential
integrity: `evaluation.candidate_id == candidate.candidate_id` and
`evaluation.dataset_version == candidate.dataset_version`. A mismatch
fails immediately (`reason="evaluation_matches_candidate"`) without
reading any metric — an evaluation computed for a different candidate
or dataset is never treated as evidence for this one.

A candidate's *current* status is never stored by mutating
`CandidateModelArtifact.status` (frozen, and Phase 9's trainer only ever
sets it to `CANDIDATE`) — it is always derived as the `to_status` of the
candidate's most recent **passed** transition (or `CANDIDATE` if none),
via `ModelStatusTransitionRepository.get_current_status`. This mirrors
`trade_journal.models.PostTradeAnalysis`/`CounterfactualRecord`'s
append-history-layered-on-an-immutable-base pattern (Phase 3/10)
applied to status instead of analysis.

## 6. Model Lineage / Versioning

`evolution.models.ModelLineageRecord(candidate_id, parent_candidate_id,
generation, lineage_basis, dataset_id, dataset_version, provenance)`
tracks Model Evolution's candidate tree. `evolution.lineage.
derive_lineage(candidate, parent=None, lineage_basis=...)` computes
`generation` from `parent.generation + 1` — never a caller-supplied
value — so a lineage chain cannot have an inconsistent depth.
`generation=0` with `parent_candidate_id=None` marks a root candidate.
The dataclass's `__post_init__` additionally rejects a record whose
`candidate_id` equals its own `parent_candidate_id` (a self-referential
lineage) — a real defect class this phase found and fixed during test
development (§10 below / the completion report's Bugs Found section):
independent `CandidateTrainer` instances each allocate their own
in-process id sequence starting at `CAND-000001`, so two candidates
trained by two different trainer instances can collide on id before a
storage-layer sequence (the same class of problem ADR-0015 §6 already
fixed for Learning Engine persistence) assigns them a real, unique id.

## 7. Candidate-Model Counterfactual (`alternative_action_1`/`alternative_action_2`)

`PROJECT_MASTER_PLAN.md` §33 reserves comparing the trade's selected
action against "a different model's or strategy's hypothetical
decision." Phase 3 (spec §7.2) and ADR-0016 §7 both concluded this
requires "that alternative to actually exist and be runnable," and
assigned it here.

`evolution.counterfactual.compute_candidate_decision_alternative`:

1. Pins a `backtest.clock.BacktestClock` to exactly `decision_time` and
   wraps it in a `backtest.asof.AsOfDataView` — the exact point-in-time
   guard every other phase's live decision path already uses (Phase
   2/5/6/7), not a new one invented here.
2. Calls the supplied `predict.predictor.Predictor.predict(...)` against
   that view, then the supplied `decision.agent.DecisionAgent.decide(...)`
   with the trade's own (already-known, historical-fact)
   `PortfolioView` — an actually-existing, runnable alternative decision
   process, per ADR-0016 §7's requirement.
3. Turns the resulting `DecisionAction` into a return figure by *reusing*
   Phase 3's `compute_hold_counterfactual` (BUY: unchanged; SELL:
   negated, i.e. a short) or Phase 10's `compute_cash_counterfactual`
   (HOLD/EXIT/NO_TRADE: no new exposure) verbatim — no new price-fetch
   logic is written, and no position sizing/quantity is modeled (the
   same documented simplicity HOLD/CASH already have).

`evolution.counterfactual.append_candidate_alternatives(record,
candidate_alternatives)` appends one or more candidate-driven
`AlternativeOutcome`s onto an existing `CounterfactualRecord` (e.g. the
`(HOLD, CASH)` record Phase 10's `build_counterfactual_record` already
produces) via `dataclasses.replace` — no Phase 3/10 source is touched.
`trade_journal.models.CounterfactualRecord.alternatives` was already an
arbitrary-length tuple built for exactly this;
"`alternative_action_1`/`alternative_action_2`" is a slot count from the
master plan's prose, not a fixed-width schema.
`tests/integration/test_evolution_lineage.py::
TestCandidateAlternativeComposesWithPhase10Counterfactual` proves the
extended record still flows into the Learning Engine's Experience
Dataset via `trade_journal.experience.build_experience_records`
unchanged — the same "zero code change needed" property Phase 10 itself
established for its own additions.

## 8. Point-in-Time / Leakage Protection

- `evolution.criteria`/`evolution.comparison`/`evolution.lineage`
  perform no data-repository access at all — they read only
  already-computed `CandidateModelArtifact`/`EvaluationResult` fields, so
  they introduce zero new leakage surface (the same "no new call site to
  re-audit" property ADR-0016 §8 established for Phase 10's
  attribution).
- `evolution.counterfactual.compute_candidate_decision_alternative` is
  the one function in this phase that *does* query market data. It is
  point-in-time safe by construction: the `Predictor`/`DecisionAgent`
  only ever see an `AsOfDataView` whose clock is pinned to
  `decision_time`, never `evaluation_time`
  (`tests/evolution/test_evolution_point_in_time.py::
  TestCandidatePredictionIsBoundToDecisionTimeNotEvaluationTime` asserts
  this at the call-site level, not just behaviorally). A leakage
  regression test additionally verifies that adding many more bars
  *after* `decision_time` to the repository does not change the
  resulting hypothetical decision.
  measuring the *return* of that decision (once it is already known,
  historically) does use `evaluation_time` — exactly the same
  "retrospective analysis after the window has already elapsed, not
  look-ahead bias" reasoning Phase 3/10 already established for
  HOLD/CASH.

## 9. Persistence

Two new tables in Phase 4's existing DuckDB catalog file
(`src/storage/schema.py`, purely additive — `git diff | grep '^-'`
shows zero deleted/changed lines):

- `model_status_transitions` — seq-ordered append history (mirrors
  Phase 3/10's `post_trade_analyses`/`counterfactuals`/
  `attribution_results` tables), one row per attempted transition,
  passing or failing.
- `model_lineage` — one row per `candidate_id` (`candidate_id PRIMARY
  KEY`), idempotent on record.

`evolution.repository`'s Protocols + `InMemory*` reference
implementations, and `storage.evolution_repository`'s DuckDB
implementations, follow the identical Protocol/idempotency/restart
discipline every prior phase's repository layer already established.
`ModelStatusTransitionRepository.get_current_status` is derived purely
from the (already-persisted) transition history at query time — no
extra "current status" column is maintained redundantly.

## 10. Reproducibility

No module in `evolution.*` imports `random` or calls
`datetime.now()`/`datetime.utcnow()`
(`tests/evolution/test_evolution_reproducibility.py::
TestNoRandomOrWallClockCalls`, an AST scan, not just a behavioral
check). An end-to-end reproducibility test
(`TestDeterministicEndToEnd`) runs the full generate → evaluate →
compare → validate → derive-lineage chain twice from identical inputs
and asserts byte-identical output at every stage.

## 11. Lineage Traceability

```
TrainingDataset -> CandidateModelArtifact -> EvaluationResult
   -> ModelStatusTransition (append history)
CandidateModelArtifact -> ModelLineageRecord (parent chain)
```

`tests/integration/test_evolution_lineage.py::
TestModelEvolutionLineageEndToEnd` proves this is SQL-joinable across
five tables in one DuckDB catalog
(`candidate_models`⋈`training_datasets`⋈`evaluation_results`⋈
`model_lineage`⋈`model_status_transitions`) and survives a process
restart.

## 12. Test Strategy

| Category | File |
|---|---|
| Candidate generation | `tests/evolution/test_evolution_trainer.py` |
| Comparison | `tests/evolution/test_evolution_comparison.py` |
| Validation / status transitions | `tests/evolution/test_evolution_criteria.py` |
| Version / lineage | `tests/evolution/test_model_lineage.py` |
| Candidate counterfactual | `tests/evolution/test_evolution_counterfactual.py` |
| Point-in-time / leakage | `tests/evolution/test_evolution_point_in_time.py` |
| Boundary | `tests/evolution/test_evolution_boundary.py` |
| Reproducibility | `tests/evolution/test_evolution_reproducibility.py` |
| Persistence / restart / idempotency | `tests/storage/test_evolution_repository.py` |
| Integration lineage | `tests/integration/test_evolution_lineage.py` |

## 13. Definition of Done

- [x] Implementation matching this spec
- [x] Unit + integration tests, all passing (see completion report for exact counts)
- [x] Error handling: every failure path (out-of-order transition,
      referential mismatch, insufficient samples, mismatched-dataset
      comparison, non-positive window) raises or returns an auditable
      `passed=False` record — nothing is silently accepted
- [x] Logging/audit: `ModelStatusTransition.criteria`/`reason` is the
      audit trail for every attempted transition
- [x] Documentation: this spec + ADR-0017
- [x] Configuration: `PromotionConfig` — no hardcoded thresholds
- [x] Validation: structural boundary tests confirm no order/broker/
      risk mutation and no path to `APPROVED`/`DEPLOYED`

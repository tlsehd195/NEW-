# PHASE 9 SPECIFICATION — Learning Engine

**Status:** ACTIVE (design confirmed, reference implementation complete)
**Phase:** Phase 9 — Learning Engine
**Depends on:** `PROJECT_MASTER_PLAN.md`, `docs/decisions/ADR-0001`
through `ADR-0014`, Phase 1 (`src/data_infra/*`), Phase 2
(`src/backtest/*`), Phase 3 (`src/trade_journal/*`, especially
`ExperienceRecord`/`build_experience_records`), Phase 4 (`src/storage/*`,
especially `ExperienceRepository`), Phase 5 (`src/regime/*`), Phase 6
(`src/predict/*`), Phase 7 (`src/decision/*`), Phase 8 (`src/risk/*`)
**Produces ADRs:** ADR-0015 (learning engine architecture)

---

## 0. Git / Branch Integrity Check (prerequisite, performed before any Phase 9 work)

Per this session's explicit instruction, the repository's Git/branch/
phase lineage was re-verified from scratch — the prior phase's PASS
result was **not** reused — before any Phase 9 code was written.

```
Current Branch: claude/phase-4-baseline-storage-tuavwk
Current HEAD (at verification time): 05ac338 (Phase 8: Position Sizing + Portfolio Risk Engine)

Ancestry re-checked individually via `git merge-base --is-ancestor <commit> HEAD`:
  Initial (c3abad0): YES        Phase 0 (e00cfb1): YES
  Phase 1 (194efc4): YES        Phase 2 (926189a): YES
  Phase 3 (e329716): YES        Preserve-Phase0-prompt (4583707): YES
  Phase 4 (44eff48): YES        Phase 5 (d386420): YES
  Phase 6 (6c0b0f6): YES        Phase 7 (6a1c937): YES
  Phase 8 (05ac338): YES

- Single linear chain, `git log --merges HEAD` empty -- no merge commits.
- origin/main HEAD = c3abad0 -- true ancestor, 0 commits on main missing
  from HEAD, current branch 10 commits ahead of main (Phase 0-8).
- origin/claude/autonomous-ai-investment-system-wvscwe HEAD = 4583707 --
  true ancestor, 0 commits missing from HEAD, current branch 5 commits
  ahead (Phase 4-8).
- All Phase 0-8 files/tests present; 483/483 tests passing; working tree
  clean at verification time.

GIT / BRANCH INTEGRITY: PASS
```

Phase 9 work began only after this fresh PASS result and after
re-reading `PROJECT_MASTER_PLAN.md`, `docs/PROJECT_STATUS.md`, the Phase
8 spec/ADR, and the actual Phase 3/4/5/6/7/8 source (Trade Journal
`ExperienceRecord`, `ExperienceRepository`, `RegimeDetector`,
`Predictor`, `DecisionAgent`, `PositionSizer`/`PortfolioRiskEngine`) to
confirm current implementation state before designing against it.

---

## 1. Purpose of This Document

`PROJECT_MASTER_PLAN.md` §11.1 defines the Learning Engine pipeline:
`Experience → Data Cleaning → Labeling → Training Dataset → Candidate
Training → Evaluation`. Phase 9 builds exactly these five stages,
ending at a `CANDIDATE`-status model artifact — never `APPROVED` or
`DEPLOYED` (§11.2, §11.5, §1.5's constitutional guarantee that a
learning result is never automatically applied to Live). The phase
exists to prove the pipeline itself — data flows from the Trade
Journal's Experience Dataset through cleaning, labeling, dataset
construction, a deterministic baseline trainer, and evaluation, all the
way to persisted, reproducible artifacts — not to produce a model
anyone should trade on yet.

---

## 2. Scope

### 2.1 In scope for Phase 9

- `DataCleaner`, validating raw `ExperienceRecord`s into `VALID`/
  `INVALID`/`EXCLUDED`/`UNKNOWN` `CleaningResult`s, never silently
  dropping a sample (§7).
- `Labeler`, turning `VALID` results into `LabeledSample`s using each
  trade's own already-realized `realized_return` as the label — the
  minimum viable label this phase implements (§8).
- `build_training_dataset`, orchestrating cleaning → labeling → a
  chronological (non-random) train/validation/test split into one
  versioned, reproducible `TrainingDataset` (§9, §10).
- `MeanRewardBaselineTrainer`, a deterministic, no-AI/ML "trainer" that
  only ever produces `CandidateModelStatus.CANDIDATE` artifacts (§11,
  §12).
- `Evaluator`, computing MAE/MSE per split plus a trivial baseline
  comparison point, never claiming candidate superiority (§13, §14).
- Four new persistent repositories (`TrainingDatasetRepository`,
  `CandidateModelRepository`, `EvaluationRepository`,
  `LearningExperimentRepository`) + DuckDB implementations extending
  Phase 4's storage layer (§15).
- `LearningExperimentTracker`, tying dataset/candidate/evaluation
  together into a `LearningExperimentRecord`, following (not reusing
  literally — see ADR-0015 §1) `backtest.experiment.ExperimentTracker`'s
  id-allocation pattern (§16).
- `run_learning_pipeline`, the single orchestration function proving
  the full Experience → ... → Experiment persistence chain end to end
  (§12 of this doc's Test Strategy table).
- Point-in-time protection for dataset construction itself: an
  `as_of_cutoff` parameter excluding any experience whose decision
  cannot be resolved to have happened before that cutoff (§5).
- Strict provenance isolation: `build_training_dataset`'s `provenance`
  parameter has no default, and `DataCleaner` marks any
  provenance-mismatched record `INVALID` (§6).

### 2.2 Out of scope for Phase 9

Per the instruction, none of the following are built in this phase:
Counterfactual Analysis, Performance Attribution (Phase 10), Model
Evolution, Model Registry completion (Phase 11), AI Gateway (Phase 12),
Toss Securities Adapter (Phase 13), Monitoring/Drift/Safety (Phase 14),
Paper Trading (Phase 15), Live Trading (Phase 16). No code path assigns
`CandidateModelStatus.APPROVED`/`DEPLOYED` — those transitions require
a human approval step (`PROJECT_MASTER_PLAN.md` §11.5) this phase never
performs. No order, broker call, or risk/position-limit mutation exists
anywhere in `learning.*` (§19 of the instruction;
`tests/learning/test_learning_boundary.py`).

### 2.3 Changes to Phase 1-8 code

**None.** Phase 9 is fully additive: four new tables in
`storage/schema.py` (`training_datasets`, `candidate_models`,
`evaluation_results`, `learning_experiments`) plus four new DuckDB
sequences, and additive serialization functions in
`storage/serialization.py`. No existing table's schema changed and no
Phase 1-8 source file was modified (verified: `git diff` against the
prior Phase 8 HEAD touches only `src/storage/schema.py` and
`src/storage/serialization.py`, both pure additions — zero deleted or
changed lines in either).

---

## 3. Learning Loop

```
Experience → Data Cleaning → Labeling → Training Dataset
   → Candidate Training → Evaluation → Candidate Result
```

Every stage's output is a plain, versioned, immutable dataclass — no
stage mutates a Phase 3/4 record, and no stage has any authority over
Live deployment (`run_learning_pipeline` returns objects; persisting or
acting on them is entirely the caller's choice, the same separation
`baseline.runner.run_baseline` already uses for Experiment/Experience
persistence, Phase 4).

---

## 4. Experience Dataset

`DataCleaner`/`Labeler`/`build_training_dataset` read
`trade_journal.models.ExperienceRecord` and `TradeJournalRepository`
exactly as they exist today (Phase 3/5/6) — no new field is invented.
`state`/`action`/`expected_outcome`/`actual_outcome`/`reward`/
`market_regime`/`risk_state`/`prediction_error`/`counterfactual_results`
are all read as-is; a field that is `None` (e.g. `market_regime` when
`regime.experience.attach_regime_context` was never run,
`prediction_error` when no `PostTradeAnalysis` exists) is treated as
genuinely unavailable, never fabricated. `risk_state` in particular
still traces only to Phase 3's own `DecisionSnapshot.risk_state` dict
field — Phase 8's `RiskCheckedPosition` is not wired into
`ExperienceRecord` (ADR-0013 §9's precedent, unchanged by this phase;
see §10).

---

## 5. Point-in-Time / Leakage Protection

`DataCleaner` resolves each record's `sample_as_of_time` via
`journal.get_decision(record.decision_id).decision_time` — the same
lookup `regime.experience.attach_regime_context`/`predict.experience.
attach_prediction_context` already use for their own point-in-time
queries (Phase 5/6). `build_training_dataset`'s optional `as_of_cutoff`
parameter excludes any record whose decision cannot be resolved to a
time at or before the cutoff *before* Data Cleaning ever examines it —
the "future data does not exist for this query" discipline
`backtest.asof.AsOfDataView` established, applied one layer further
(ADR-0015 §4). `LabeledSample` keeps `feature_cutoff_time`/
`label_start_time`/`label_end_time` as distinct fields even though this
phase's reference label always sets `feature_cutoff_time ==
label_start_time == sample_as_of_time` — future information (the
realized outcome) is permitted into the *label*, never back into the
feature cutoff. `tests/learning/test_learning_point_in_time.py` is the
required leakage regression test: rebuilding a dataset at a fixed
cutoff after new, later experiences are added to the journal reproduces
an identical `TrainingDataset` (same `dataset_version`, same splits,
same label values).

---

## 6. Provenance Separation

`build_training_dataset`'s `provenance: TradeProvenance` parameter has
no default (`tests/learning/test_learning_provenance.py::
test_provenance_is_a_required_argument_not_defaultable_to_mixing`
verifies this via `inspect.signature`) — every dataset build must
explicitly declare exactly one category.
`DataCleaner` marks any input record whose `provenance` does not match
that declared category `INVALID` — `provenance_mismatch` — so even a
caller that accidentally passes a mixed-provenance record list never
gets a silently-blended dataset. `TrainingDataset.provenance`,
`CandidateModelArtifact.provenance`, `EvaluationResult.provenance`, and
`LearningExperimentRecord.provenance` all carry this same value through
the full lineage chain.

---

## 7. Data Cleaning

`DataCleaner.clean()` never silently drops a sample — every input
record receives exactly one `CleaningResult` with a `SampleStatus`
(`VALID`/`INVALID`/`EXCLUDED`/`UNKNOWN`) and a factual `reason`:

| Check | Status | Reason |
|---|---|---|
| provenance ≠ requested | INVALID | `provenance_mismatch` |
| duplicate `trade_id` within the batch | INVALID | `duplicate_trade_id` |
| decision cannot be resolved (no `sample_as_of_time`) | UNKNOWN | `missing_decision` |
| `reward` is NaN/infinite | INVALID | `invalid_reward_numeric` |
| `actual_outcome.realized_return` is NaN/infinite | INVALID | `invalid_realized_return_numeric` |
| `actual_outcome.realized_return` is `None` | EXCLUDED (configurable) | `no_realized_outcome` |
| everything else | VALID | `ok` |

`missing_decision` (UNKNOWN) reflects genuine uncertainty — the pipeline
cannot verify anything about the sample without a resolvable decision
time. `no_realized_outcome` (EXCLUDED) reflects a legitimate, honest
state (an opening trade with no realization yet,
`trade_journal.experience`'s own documented convention) — not a defect.

---

## 8. Labeling

`Labeler.label()` only ever reads `TradeRecord.realized_return`/
`holding_period` — never `ExperienceRecord.state` — keeping the
feature/label separation structural, not just conventional. The label
definition implemented is `actual_realized_return_v1`: the trade's own
already-realized return, with `label_horizon=None` (a variable horizon
— each trade's own holding period — not a fabricated fixed window).
`label_version`/`label_definition`/`label_generated_at` are all
recorded per sample. Per instruction section 8, no additional label
(`forward_return`, `direction`, `excess_return_vs_benchmark`,
`risk_adjusted_outcome`) is implemented this phase — the minimum viable
label the existing data actually supports, not several at once.

---

## 9. Training Dataset Versioning

`TrainingDataset` carries `dataset_id`, `dataset_version`,
`created_at`, `source_experience_ids`, `provenance`, `feature_version`,
`label_version`, `data_version`, `cleaning_config_version`/
`label_config_version`/`split_config_version`/`sampling_config_version`/
`configuration_version`, `sample_count`, `excluded_count`,
`quality_status`, `splits`, `as_of_cutoff`. `dataset_version` is a
content hash of the actual labeled sample content
(`(trade_id, label_value, sample_as_of_time)` tuples) plus
configuration/provenance/cutoff — not merely an id-list hash (ADR-0015
§5 records the self-discovered bug this fixes). Rebuilding from
identical source experiences and configuration always reproduces the
same `dataset_version` and the same split assignment.

---

## 10. Train / Validation / Test Split

Samples are sorted by `sample_as_of_time` and sliced into contiguous,
chronologically non-overlapping `TRAIN`/`VALIDATION`/`TEST` ranges per
`SplitConfig`'s fractions (default 60/20/20) — never shuffled. No
`trade_id` appears in more than one split; the maximum `TRAIN` sample
time never exceeds the minimum `TEST` sample time
(`tests/learning/test_learning_point_in_time.py::
TestTemporalSplitIntegrity`). Full Purged K-Fold/Embargo is explicitly
deferred to a later Validation-focused phase per instruction section 10
and `PROJECT_MASTER_PLAN.md` §13.5 — this phase's split only needs to
not leak across time, not to implement the complete validation
protocol.

---

## 11. Candidate Training

`CandidateTrainer` is a `Protocol`; `MeanRewardBaselineTrainer` is the
only implementation Phase 9 ships — a deterministic, no-AI/ML "trainer"
that computes the mean `label_value` over the `TRAIN` split only (never
touching `VALIDATION`/`TEST`,
`tests/learning/test_trainer.py::
test_trainer_never_touches_validation_or_test_samples` verifies this
directly) and predicts that constant. This is the same "null-hypothesis
baseline, not a claimed-good model" discipline `predict.predictor.
RandomWalkPredictor` (Phase 6) already established, one layer further.
A future real trainer implements the same Protocol as a drop-in
replacement.

---

## 12. Model Boundary

`CandidateModelArtifact.status` is always
`CandidateModelStatus.CANDIDATE` — the full master-plan state machine
(`BACKTESTED`/`VALIDATED`/`OOS_TESTED`/`PAPER_TESTED`/`APPROVED`/
`DEPLOYED`) is reserved on the enum for Phase 10/11 to assign, but no
code in `learning.*` ever constructs any of those states
(`tests/learning/test_learning_boundary.py::
test_no_code_path_in_learning_module_constructs_an_approved_or_deployed_candidate`
statically verifies this via an AST scan).

---

## 13. Evaluation

`Evaluator.evaluate()` computes `sample_count`/`mean_absolute_error`/
`mean_squared_error`/`mean_label` for each of `train_metrics`/
`validation_metrics`/`test_metrics`, plus `baseline_metrics` — a
trivial "always predict 0.0" comparison point evaluated over the same
`TEST` split. `EvaluationResult` has no `candidate_is_better`/`winner`
field — nothing in this phase declares the candidate superior to the
baseline (`tests/learning/test_evaluation.py::
TestBaselineComparison`). PBO/Deflated Sharpe/Walk-Forward validation is
explicitly out of scope this phase (instruction section 13).

---

## 14. Baseline Relationship

`EvaluationResult.baseline_metrics` exists specifically so a candidate
is always read next to a baseline, never in isolation — continuing
Phase 4/6/7/8's "compare, never auto-declare superiority" discipline
(`baseline.report`'s own no-ranking-field design, Phase 4;
`RegimeAwarePredictor`/`RiskCheckedPosition` tests never asserting
performance superiority, Phase 5/8). A benchmark-level (S&P 500)
comparison is not wired into `EvaluationResult` this phase — the
Experience Dataset samples used here are per-trade, not per-benchmark;
extending evaluation to compare against `backtest.benchmark`-derived
figures is future work, noted under Known Issues.

---

## 15. Persistence

`training_datasets`, `candidate_models`, `evaluation_results`, and
`learning_experiments` are four new DuckDB tables in Phase 4's existing
catalog file. Each `DuckDB*Repository.record()` allocates its own
storage-level id from a dedicated sequence after a natural-key dedup
check passes — never trusting the caller's in-process allocator id
(ADR-0015 §6 records the self-discovered bug this fixes, following
`DuckDBExperienceRepository`'s own precedent from Phase 4).
`get_by_version`/`get_as_of`-equivalent lookups, restart safety, and
idempotency are all verified in `tests/storage/test_learning_repository.py`.

---

## 16. Experiment Tracking

`LearningExperimentTracker` allocates `"LRN-000001"`-style ids and ties
one training run's dataset/candidate/evaluation together into a
`LearningExperimentRecord`, mirroring (not reusing literally — ADR-0015
§1) `backtest.experiment.ExperimentTracker`'s id-allocation pattern.
`DuckDBLearningExperimentRepository` dedupes on
`(dataset_version, candidate_id, evaluation_id)`, not the caller-supplied
`experiment_id`.

---

## 17. Reproducibility

`build_training_dataset`/`MeanRewardBaselineTrainer.train`/
`Evaluator.evaluate` contain no randomness anywhere (`tests/learning/
test_reproducibility.py::test_no_randomness_module_is_used_anywhere_in_learning_package`
statically verifies no file in `learning/*.py` imports Python's
`random` module). `seed` is accepted end to end (`run_learning_pipeline`
→ `CandidateModelArtifact.seed`) for interface completeness ahead of a
future stochastic trainer, and is recorded rather than silently
dropped, but is currently unused — documented, not hidden.

---

## 18. AI / LLM Usage

None. No external AI provider is called anywhere in `learning.*` — the
entire pipeline is deterministic/local, per instruction section 18.
AI Gateway remains Phase 12.

---

## 19. Safety Boundary

`learning.*` contains no order creation, no broker call, no Toss API
call, no position/risk-limit mutation, no kill-switch interaction, no
Live model replacement, no Live Trading activation, and no API billing
change — verified structurally by `tests/learning/
test_learning_boundary.py` (reflection over every public method/field
of every Learning Engine type, plus signature inspection of every
public function).

---

## 20. DECISION REQUIRED Review — Phase 3 Known Issues

- **벤치마크 return type (PRICE_RETURN vs TOTAL_RETURN)**: unrelated —
  Learning Engine never reads `backtest.benchmark` data.
- **per-decision `data_version` 미노출**: re-reviewed — `LabeledSample.
  data_version` is copied from `ExperienceRecord.data_version` exactly
  as-is (honestly `()` when the source was `None`), the same "store
  what's there, don't estimate" behavior Phase 4/5/6/7/8 already
  applied; this phase does not need per-decision precision beyond what
  Phase 3 already provides.
- **corporate-action-aware `portfolio_state` 재구성**: unrelated —
  Learning Engine never reconstructs `portfolio_state`; it only reads
  each trade's own `realized_return`/`holding_period`.

**재검토했으며 이번 Phase와 무관하여 이연.**

---

## 21. Phase 8 Known Issue Review

- **다중 포지션 `average_cost` proxy**: unrelated — Learning Engine
  never touches `risk.engine.PortfolioRiskState`.
- **sector/factor limit 데이터 부재**: unrelated — same reason.
- **`turnover` 검사 호출자 의존**: unrelated — Learning Engine has no
  Risk Engine dependency at all; `ExperienceRecord.risk_state`, when
  populated, is read as an opaque dict (never inspected for
  turnover-specific structure).

None of Phase 8's structural assumptions are required by Phase 9's
pipeline; no change was made to `src/risk/*`.

---

## 22. Phase Boundary

Per the instruction, this phase does not implement: Counterfactual
Analysis, Performance Attribution (Phase 10), Model Evolution, Model
Registry completion (Phase 11), AI Gateway (Phase 12), Toss Securities
Adapter (Phase 13), Monitoring/Drift/Safety (Phase 14), Paper Trading
(Phase 15), Live Trading (Phase 16). No structural gap between the
master plan's Phase list and this phase's implementation was found that
would require a `DECISION REQUIRED` escalation — Order Creation/
Validation (previously noted in Phase 8's own "Next Recommended Task"
as lacking an explicit dedicated Phase number in §18.1) remains
unaddressed by this phase too, consistent with not inventing a Phase 9
responsibility the master plan does not assign here.

---

## 23. Test Strategy

| Requirement | Test file |
|---|---|
| Unit: Data Cleaning | `tests/learning/test_cleaning.py` |
| Unit: Labeling | `tests/learning/test_labeling.py` |
| Unit: Dataset construction, temporal split, versioning | `tests/learning/test_dataset.py` |
| Unit: Candidate Training | `tests/learning/test_trainer.py` |
| Unit: Evaluation | `tests/learning/test_evaluation.py` |
| Leakage: cutoff filtering, feature/label separation, temporal split integrity | `tests/learning/test_learning_point_in_time.py` |
| Provenance: isolation across HISTORICAL_SIMULATION/PAPER_TRADING/LIVE_TRADING | `tests/learning/test_learning_provenance.py` |
| Boundary: no order/broker/risk mutation, candidate never auto-approved/deployed | `tests/learning/test_learning_boundary.py` |
| Reproducibility: same input/config/seed → same result | `tests/learning/test_reproducibility.py` |
| Persistence: save, reload, idempotency, restart, id-collision regression | `tests/storage/test_learning_repository.py` |
| Integration: Experience → Cleaning → Labeling → Dataset → Training → Evaluation → Experiment persistence | `tests/integration/test_learning_pipeline.py` |

All of Phase 1-8's existing tests (483) continue to pass unmodified
(`python3 -m pytest tests/ -q`); Phase 9 adds 70 new tests, for **553
total**.

---

## 24. Research Grounding

No new paper is added. The "what design decision requires evidence?"
question was asked and answered: a mean-reward baseline trainer and
MAE/MSE evaluation are standard, transparent, hand-verifiable
mechanics requiring no academic grounding beyond what
`PROJECT_MASTER_PLAN.md` §11 already registers — the same conclusion
every prior phase's own deterministic baseline component reached.

---

## 25. Definition of Done for Phase 9

- [x] Git/branch integrity re-verified PASS from scratch before any
      Phase 9 work began (§0)
- [x] Master Plan / prior ADRs / prior specs / current `src/`+`tests/`
      reviewed
- [x] This specification written
- [x] Learning Engine pipeline defined, boundary with Model Registry/
      Deployment/Order/Broker preserved structurally (§2, §12, §19)
- [x] Point-in-time correctness for dataset construction, verified
      independently (§5)
- [x] Deterministic baseline trainer implemented, no AI/ML (§11)
- [x] Data Cleaning never silently drops a sample, individually tested (§7)
- [x] Provenance never mixed, structurally enforced (§6)
- [x] Chronological, non-shuffled temporal split, verified leak-free (§10)
- [x] Full version lineage, honest values, reproducible (§9, §17)
- [x] Persistence: four new DuckDB tables, restart-safe, idempotent,
      collision-free across independent runs (§15)
- [x] DECISION REQUIRED review completed — none required resolution (§20, §21)
- [x] Full test suite passing: 553/553 (483 prior + 70 new)
- [x] `docs/PROJECT_STATUS.md` updated
- [x] `README.md` updated
- [x] Design + reference implementation committed to git
